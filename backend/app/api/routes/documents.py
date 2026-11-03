"""Document routes — upload, OCR, entity extraction, timeline.

    POST   /documents                              upload (multipart)
    GET    /documents/{id}                         metadata + entities
    GET    /documents/{id}/entities                entities only
    GET    /patients/{patient_id}/documents/timeline   chronological

All endpoints require auth AND the "documents" consent scope.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.dependencies import require_consent_scope
from app.models.models import Document, DocumentEntity, Patient
from app.services.audit import log_action
from app.services.embeddings import generate_embedding
from app.services.entity_extraction import extract_entities
from app.services.ocr import get_ocr_engine
from app.services.storage import get_storage_backend

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

# Type alias: patient who has consented to document processing
DocumentsPatient = Annotated[Patient, Depends(require_consent_scope("documents"))]
Db = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DocumentResponse(BaseModel):
    id: str
    patient_id: str
    file_uri: str
    doc_type: str
    document_date: str | None
    ocr_status: str
    uploaded_at: str


class EntityResponse(BaseModel):
    id: str
    entity_type: str
    value: dict
    is_abnormal: bool | None


class DocumentDetailResponse(DocumentResponse):
    entities: list[EntityResponse]


class TimelineItem(BaseModel):
    id: str
    doc_type: str
    document_date: str | None
    uploaded_at: str
    ocr_status: str
    entity_count: int
    abnormal_count: int


class TimelineResponse(BaseModel):
    patient_id: str
    documents: list[TimelineItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    patient: DocumentsPatient,
    db: Db,
    file: UploadFile = File(...),  # noqa: B008
    doc_type: str = Form(default="unknown"),  # noqa: B008
):
    """Upload a document image for OCR and extraction.

    Accepts JPEG, PNG, PDF, TIFF.  The file is stored via the storage backend,
    then OCR + entity extraction run synchronously (MVP — a real deployment
    should use a background task queue for large batches).
    """
    allowed = {"image/jpeg", "image/png", "image/tiff", "application/pdf"}
    content_type = file.content_type or ""
    if content_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {content_type}. Allowed: {', '.join(sorted(allowed))}",
        )

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20 MB)")

    # Store blob
    storage = get_storage_backend()
    file_uri = storage.save(data, file.filename or "document", patient.id)

    # Create record
    doc = Document(
        id=uuid.uuid4(),
        patient_id=patient.id,
        file_uri=file_uri,
        doc_type=doc_type if doc_type != "unknown" else "unknown",
        ocr_status="pending",
        uploaded_at=datetime.now(tz=UTC),
    )
    db.add(doc)
    db.flush()

    # OCR
    #
    # Every OcrEngine is synchronous, and this handler is async. Running the
    # engine inline blocks the event loop for its whole duration, which stalls
    # every other in-flight kiosk request — including the 3s red-flag path.
    # That was already wrong for Tesseract on a large scan; with Sarvam's
    # polling job API it would hold the loop for the length of the job.
    ocr_text = ""
    try:
        engine = get_ocr_engine(handwriting=False)
        file_path = storage.resolve_path(file_uri)
        ocr_text = await run_in_threadpool(engine.extract_text, file_path)
        doc.ocr_status = "done"
    except Exception:
        logger.warning("documents: OCR failed for %s", file_uri, exc_info=True)
        doc.ocr_status = "failed"

    entity_count = 0

    # Entity extraction
    if ocr_text:
        result = extract_entities(ocr_text, gender=patient.gender)

        if result.doc_type != "unknown" and doc.doc_type == "unknown":
            doc.doc_type = result.doc_type
        if result.document_date:
            doc.document_date = result.document_date

        for entity in result.entities:
            db.add(
                DocumentEntity(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    entity_type=entity.entity_type,
                    value=entity.value,
                    is_abnormal=entity.is_abnormal,
                )
            )
        entity_count = len(result.entities)

        # Embedding
        embedding = generate_embedding(ocr_text)
        db.execute(
            text(
                "INSERT INTO document_embeddings (id, document_id, patient_id, embedding) "
                "VALUES (:id, :document_id, :patient_id, cast(:embedding AS vector))"
            ),
            {
                "id": str(uuid.uuid4()),
                "document_id": str(doc.id),
                "patient_id": str(patient.id),
                "embedding": str(embedding),
            },
        )

    log_action(
        db,
        patient_id=patient.id,
        action="document.upload",
        resource=f"document:{doc.id}",
        detail={"doc_type": doc.doc_type, "ocr_status": doc.ocr_status, "entities": entity_count},
    )
    db.commit()

    return DocumentResponse(
        id=str(doc.id),
        patient_id=str(doc.patient_id),
        file_uri=doc.file_uri,
        doc_type=doc.doc_type,
        document_date=doc.document_date.isoformat() if doc.document_date else None,
        ocr_status=doc.ocr_status,
        uploaded_at=doc.uploaded_at.isoformat(),
    )


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(document_id: str, patient: DocumentsPatient, db: Db):
    """Document metadata + all extracted entities."""
    doc = _get_patient_document(document_id, patient.id, db)
    entities = db.query(DocumentEntity).filter(DocumentEntity.document_id == doc.id).all()

    # Audit: read of patient health data (DPDP compliance)
    log_action(
        db,
        action="document.read",
        resource=f"document:{doc.id}",
        patient_id=patient.id,
    )
    db.commit()

    return DocumentDetailResponse(
        id=str(doc.id),
        patient_id=str(doc.patient_id),
        file_uri=doc.file_uri,
        doc_type=doc.doc_type,
        document_date=doc.document_date.isoformat() if doc.document_date else None,
        ocr_status=doc.ocr_status,
        uploaded_at=doc.uploaded_at.isoformat(),
        entities=[
            EntityResponse(
                id=str(e.id), entity_type=e.entity_type, value=e.value, is_abnormal=e.is_abnormal
            )
            for e in entities
        ],
    )


@router.get("/documents/{document_id}/entities", response_model=list[EntityResponse])
def get_document_entities(document_id: str, patient: DocumentsPatient, db: Db):
    """Extracted entities only."""
    doc = _get_patient_document(document_id, patient.id, db)
    entities = db.query(DocumentEntity).filter(DocumentEntity.document_id == doc.id).all()

    # Audit: read of extracted patient health entities
    log_action(
        db, action="document.entities_read", resource=f"document:{doc.id}", patient_id=patient.id
    )
    db.commit()
    return [
        EntityResponse(
            id=str(e.id), entity_type=e.entity_type, value=e.value, is_abnormal=e.is_abnormal
        )
        for e in entities
    ]


@router.get("/patients/{patient_id}/documents/timeline", response_model=TimelineResponse)
def get_patient_timeline(patient_id: str, patient: DocumentsPatient, db: Db):
    """Chronologically ordered document timeline for the patient."""
    if str(patient.id) != patient_id:
        raise HTTPException(status_code=403, detail="Cannot access another patient's documents")

    # Audit: read of patient document timeline
    log_action(
        db, action="document.timeline_read", resource=f"patient:{patient.id}", patient_id=patient.id
    )
    db.commit()

    documents = (
        db.query(Document)
        .filter(Document.patient_id == patient.id)
        .order_by(Document.document_date.desc().nullslast(), Document.uploaded_at.desc())
        .all()
    )

    items: list[TimelineItem] = []
    for doc in documents:
        entities = db.query(DocumentEntity).filter(DocumentEntity.document_id == doc.id).all()
        items.append(
            TimelineItem(
                id=str(doc.id),
                doc_type=doc.doc_type,
                document_date=doc.document_date.isoformat() if doc.document_date else None,
                uploaded_at=doc.uploaded_at.isoformat(),
                ocr_status=doc.ocr_status,
                entity_count=len(entities),
                abnormal_count=sum(1 for e in entities if e.is_abnormal is True),
            )
        )

    return TimelineResponse(patient_id=str(patient.id), documents=items)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_patient_document(document_id: str, patient_id: uuid.UUID, db: Session) -> Document:
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document_id") from exc

    doc = (
        db.query(Document)
        .filter(Document.id == doc_uuid, Document.patient_id == patient_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
