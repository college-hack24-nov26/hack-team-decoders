"""Physician Dashboard API routes — Step 5 (Consult).

GET /dashboard/queue — patient list, red-flags first
GET /dashboard/patients/{id}/summary — full summary + document timeline
GET /dashboard/patients/{id}/report.pdf — PDF export

Basic physician auth: for now we accept any valid JWT (the same patient tokens).
Module D (Wave 5) adds proper RBAC with physician-specific tokens.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import CurrentPhysician, DbSession
from app.models.models import (
    Document,
    DocumentEntity,
    InterviewMessage,
    InterviewSession,
    Patient,
    RedFlag,
    Summary,
)
from app.services.audit import log_action
from app.services.summary.pdf import render_summary_pdf

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class QueuePatient(BaseModel):
    patient_id: str
    name: str
    age: int | None
    gender: str | None
    chief_complaint: str | None
    session_status: str
    has_red_flags: bool
    red_flag_count: int
    summary_status: str | None
    started_at: str | None


class QueueResponse(BaseModel):
    patients: list[QueuePatient]
    total: int


class PatientSummaryResponse(BaseModel):
    patient: dict[str, Any]
    session_id: str | None
    """The interview session this view is about.

    Returned at the top level, not nested inside `summary`, precisely because
    the client needs it when `summary` is null — that is the case where it has
    to call POST /summaries/generate. Nesting it meant the Generate button had
    nothing to send and posted an empty string.
    """

    session_status: str | None
    summary: dict[str, Any] | None
    documents: list[dict[str, Any]]
    red_flags: list[dict[str, Any]]
    transcript: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/queue", response_model=QueueResponse)
def get_queue(physician: CurrentPhysician, db: DbSession):
    """List patients ready for consult, red-flags first.

    Shows all patients with completed/red-flagged interview sessions.
    Sorted: red-flagged first, then by session start time (oldest first).

    Physician-authenticated. This shipped with no dependency at all, which made
    the entire queue — every patient's name, age, chief complaint and red-flag
    count — readable by anyone who could reach the port.
    """
    sessions = (
        db.query(InterviewSession)
        .filter(InterviewSession.status.in_(["completed", "red_flagged"]))
        .order_by(
            # Red-flagged patients sort to the top
            (InterviewSession.status == "red_flagged").desc(),
            InterviewSession.started_at.asc(),
        )
        .all()
    )

    patients: list[QueuePatient] = []
    seen_patient_ids: set[str] = set()

    for session in sessions:
        pid = str(session.patient_id)
        if pid in seen_patient_ids:
            continue
        seen_patient_ids.add(pid)

        patient = db.query(Patient).filter(Patient.id == session.patient_id).first()
        if not patient:
            continue

        red_flags = db.query(RedFlag).filter(RedFlag.session_id == session.id).all()
        summary = db.query(Summary).filter(Summary.session_id == session.id).first()

        patients.append(
            QueuePatient(
                patient_id=pid,
                name=patient.name,
                age=patient.age,
                gender=patient.gender,
                chief_complaint=session.chief_complaint,
                session_status=session.status,
                has_red_flags=len(red_flags) > 0,
                red_flag_count=len(red_flags),
                summary_status=summary.status if summary else None,
                started_at=session.started_at.isoformat() if session.started_at else None,
            )
        )

    # Audit: the queue exposes every waiting patient's name, age and chief
    # complaint, so reading it is a bulk read of patient data.
    log_action(
        db,
        action="dashboard.queue_viewed",
        resource="dashboard:queue",
        physician_id=physician.id,
        detail={"patient_count": len(patients)},
    )
    db.commit()

    return QueueResponse(patients=patients, total=len(patients))


@router.get("/patients/{patient_id}/summary", response_model=PatientSummaryResponse)
def get_patient_summary(patient_id: str, physician: CurrentPhysician, db: DbSession):
    """Full summary + document timeline for the physician view."""
    patient = db.query(Patient).filter(Patient.id == uuid.UUID(patient_id)).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Latest session
    session = (
        db.query(InterviewSession)
        .filter(InterviewSession.patient_id == patient.id)
        .order_by(InterviewSession.started_at.desc())
        .first()
    )

    # Summary for latest session
    summary = None
    if session:
        summary_obj = db.query(Summary).filter(Summary.session_id == session.id).first()
        if summary_obj:
            summary = {
                "id": str(summary_obj.id),
                "patient_id": str(summary_obj.patient_id),
                "session_id": str(summary_obj.session_id),
                "structured_content": summary_obj.structured_content,
                "generated_by": summary_obj.generated_by,
                "physician_edited": summary_obj.physician_edited,
                "status": summary_obj.status,
            }

    # Red flags
    red_flags = []
    if session:
        flags = db.query(RedFlag).filter(RedFlag.session_id == session.id).all()
        red_flags = [
            {
                "symptom": f.symptom,
                "severity": f.severity,
                "triggered_at": f.triggered_at.isoformat() if f.triggered_at else None,
            }
            for f in flags
        ]

    # Documents
    docs = (
        db.query(Document)
        .filter(Document.patient_id == patient.id)
        .order_by(Document.document_date.desc().nullslast())
        .all()
    )
    documents = []
    for doc in docs:
        entities = db.query(DocumentEntity).filter(DocumentEntity.document_id == doc.id).all()
        documents.append(
            {
                "id": str(doc.id),
                "doc_type": doc.doc_type,
                "document_date": doc.document_date.isoformat() if doc.document_date else None,
                "ocr_status": doc.ocr_status,
                "entities": [
                    {
                        "entity_type": e.entity_type,
                        "value": e.value,
                        "is_abnormal": e.is_abnormal,
                    }
                    for e in entities
                ],
            }
        )

    # Transcript
    transcript = []
    if session:
        messages = (
            db.query(InterviewMessage)
            .filter(InterviewMessage.session_id == session.id)
            .order_by(InterviewMessage.created_at.asc())
            .all()
        )
        for msg in messages:
            transcript.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "input_mode": msg.input_mode,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )

    # A physician reading a patient's full record is exactly what the DPDP audit
    # trail exists to capture. This needs its own commit: the request otherwise
    # makes no writes, so without it the entry is discarded on session close.
    log_action(
        db,
        action="dashboard.patient_viewed",
        resource=f"patient:{patient.id}",
        patient_id=patient.id,
        physician_id=physician.id,
        detail={"session_id": str(session.id) if session else None},
    )
    db.commit()

    return PatientSummaryResponse(
        patient={
            "id": str(patient.id),
            "name": patient.name,
            "age": patient.age,
            "gender": patient.gender,
            "preferred_language": patient.preferred_language,
        },
        session_id=str(session.id) if session else None,
        session_status=session.status if session else None,
        summary=summary,
        documents=documents,
        red_flags=red_flags,
        transcript=transcript,
    )


@router.get("/patients/{patient_id}/report")
def get_report_pdf(patient_id: str, physician: CurrentPhysician, db: DbSession):
    """Generate and download an A4 PDF of the summary.

    Renders the structured summary through reportlab (see summary/pdf.py): a real
    clinical document with the standard history sections, abnormal values in red,
    red flags boxed, and a signature line — not the plain-text dump this used to
    return under a .pdf route name.
    """
    patient = db.query(Patient).filter(Patient.id == uuid.UUID(patient_id)).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    session = (
        db.query(InterviewSession)
        .filter(InterviewSession.patient_id == patient.id)
        .order_by(InterviewSession.started_at.desc())
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="No interview session found")

    summary = db.query(Summary).filter(Summary.session_id == session.id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="No summary generated yet")

    pdf_bytes = render_summary_pdf(
        patient=patient,
        summary=summary,
        content=summary.structured_content or {},
        physician_name=physician.full_name or physician.email,
    )

    # Audit: exporting the record off the platform is the most sensitive read
    # in the system, so it gets its own audit action rather than reusing view.
    log_action(
        db,
        action="dashboard.report_exported",
        resource=f"summary:{summary.id}",
        patient_id=patient.id,
        physician_id=physician.id,
        detail={"format": "pdf"},
    )
    db.commit()

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'attachment; filename="medikiosk_report_{patient_id[:8]}.pdf"')
        },
    )
