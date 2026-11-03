"""Summary API routes — Module C endpoints.

POST /summaries/generate   — trigger summarizer for a session
GET  /summaries/{id}       — fetch a structured summary
PATCH /summaries/{id}      — physician edits/amends
POST /summaries/{id}/confirm — physician confirms/accepts
POST /summaries/{id}/push-abdm — stub FHIR push (Module D replaces this)
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dependencies import CurrentPatient, CurrentPhysician, DbSession
from app.interview import tts
from app.models.models import InterviewSession, Patient, Summary
from app.services.fhir import build_fhir_bundle, push_bundle
from app.services.purge import purge_session_data
from app.services.security import SecurityLayer
from app.services.summary.retrieval import retrieve_session_context
from app.services.summary.router import generate_summary

router = APIRouter(prefix="/summaries", tags=["Summaries"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    session_id: str


class SummaryResponse(BaseModel):
    id: str
    patient_id: str
    session_id: str
    structured_content: dict[str, Any]
    generated_by: str
    physician_edited: bool
    status: str
    created_at: str | None = None
    confirmed_at: str | None = None


class EditRequest(BaseModel):
    """Partial update — only the fields the physician changed."""

    structured_content: dict[str, Any]


class ConfirmRequest(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
    rejection_reason: str | None = None


class FhirPushResponse(BaseModel):
    """Result of a FHIR push.

    The Bundle is real FHIR R4. `pushed` reports whether it actually reached a
    transport: false with transport="none" means no endpoint is configured, so
    the Bundle was generated and returned but sent nowhere.
    """

    status: str
    fhir_resource_type: str = "Bundle"
    pushed: bool
    transport: str
    message: str
    bundle: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=SummaryResponse, status_code=201)
async def generate(
    body: GenerateRequest,
    physician: CurrentPhysician,
    db: DbSession,
):
    """Trigger the summarizer for a completed interview session.

    Pulls interview answers + document entities, routes through Main API or
    Local Offline (with deterministic fallback), and stores the result.

    Physician-authenticated, because the caller is the dashboard. This first
    shipped requiring a *patient* token, which no physician has, so the Generate
    Summary button could only ever return 401.
    """
    try:
        session_uuid = uuid.UUID(body.session_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="session_id must be a valid UUID") from None

    session = db.query(InterviewSession).filter(InterviewSession.id == session_uuid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    if session.status not in ("completed", "red_flagged"):
        raise HTTPException(
            status_code=400,
            detail=f"Session must be completed before summarization (current: {session.status})",
        )

    # Check if a summary already exists for this session
    existing = db.query(Summary).filter(Summary.session_id == session.id).first()
    if existing:
        return _to_response(existing)

    # Consent gate. The caller is a physician, so the route dependency cannot
    # check consent — it belongs to the patient whose data is about to be sent
    # to an LLM. Module D requires no AI call without a covering consent record,
    # and this endpoint previously made one with no check at all.
    security = SecurityLayer.for_patient(db, session.patient_id, physician_id=physician.id)
    security.authorize("interview")

    # Retrieve context and generate
    context = retrieve_session_context(body.session_id, db)
    structured_summary, generated_by = await generate_summary(context)

    # Store. patient_id comes off the session, not off the caller — the caller is
    # now the physician.
    summary = Summary(
        id=uuid.uuid4(),
        patient_id=session.patient_id,
        session_id=session.id,
        structured_content=structured_summary.model_dump(),
        generated_by=generated_by,
        physician_edited=False,
        status="draft",
    )
    db.add(summary)
    db.flush()

    security.audit(
        "summary.generated",
        resource=f"summary:{summary.id}",
        detail={"session_id": body.session_id, "generated_by": generated_by},
    )

    db.commit()
    db.refresh(summary)

    return _to_response(summary)


@router.get("/{summary_id}", response_model=SummaryResponse)
def get_summary(
    summary_id: str,
    physician: CurrentPhysician,
    db: DbSession,
):
    """Fetch a structured summary by ID."""
    summary = db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return _to_response(summary)


@router.patch("/{summary_id}", response_model=SummaryResponse)
def edit_summary(
    summary_id: str,
    body: EditRequest,
    physician: CurrentPhysician,
    db: DbSession,
):
    """Physician edits/amends the summary.

    Physician-authenticated. This shipped with no dependency, so any caller who
    could guess or read a summary id could rewrite a clinical record.
    """
    summary = db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    if summary.status == "confirmed":
        raise HTTPException(status_code=400, detail="Cannot edit a confirmed summary")

    summary.structured_content = body.structured_content
    summary.physician_edited = True

    security = SecurityLayer.for_patient(db, summary.patient_id, physician_id=physician.id)
    security.audit(
        "summary.edited",
        resource=f"summary:{summary.id}",
        detail={"physician_edited": True},
    )

    db.commit()
    db.refresh(summary)

    return _to_response(summary)


@router.post("/{summary_id}/confirm", response_model=SummaryResponse)
def confirm_summary(
    summary_id: str,
    body: ConfirmRequest,
    physician: CurrentPhysician,
    db: DbSession,
):
    """Physician confirms or rejects the summary.

    Physician-authenticated. Confirmation is what turns an AI draft into a record
    the hospital acts on, so leaving it unauthenticated meant anyone could
    promote an unreviewed draft.
    """
    summary = db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")

    if body.decision == "reject" and not (body.rejection_reason or "").strip():
        # The rejection reason is the primary model-improvement signal (PRD E1.5),
        # so a rejection without one is refused rather than silently accepted.
        raise HTTPException(
            status_code=400, detail="A rejection_reason is required when rejecting a summary"
        )

    summary.status = "confirmed" if body.decision == "accept" else "rejected"
    if body.decision == "accept":
        summary.confirmed_by_id = physician.id
        summary.confirmed_at = datetime.now(tz=UTC)

    security = SecurityLayer.for_patient(db, summary.patient_id, physician_id=physician.id)
    security.audit(
        f"summary.{body.decision}ed",
        resource=f"summary:{summary.id}",
        detail={"decision": body.decision, "reason": body.rejection_reason},
    )

    db.commit()
    db.refresh(summary)

    return _to_response(summary)


@router.post("/{summary_id}/push-abdm", response_model=FhirPushResponse)
async def push_abdm(
    summary_id: str,
    physician: CurrentPhysician,
    db: DbSession,
):
    """Push a confirmed summary to ABDM/HIS as a FHIR R4 document Bundle.

    Requires the patient to have granted the `abdm_push` consent scope. That
    scope defaults to False, so this is the one operation in the system most
    likely to be attempted without consent — the previous stub performed it with
    no check at all, which is exactly the DPDP violation Module D exists to stop.

    Transport is only as real as `ABDM_FHIR_ENDPOINT`. See app/services/fhir.py
    for precisely what is real and what is mocked.
    """
    summary = db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    if summary.status != "confirmed":
        raise HTTPException(
            status_code=400, detail="Only confirmed summaries can be pushed to ABDM"
        )

    security = SecurityLayer.for_patient(db, summary.patient_id, physician_id=physician.id)
    security.authorize("abdm_push")

    patient = db.query(Patient).filter(Patient.id == summary.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    bundle = build_fhir_bundle(summary, patient)

    endpoint = get_settings().abdm_fhir_endpoint
    if endpoint:
        pushed, message = await push_bundle(bundle, endpoint)
        transport = endpoint
    else:
        pushed, transport = False, "none"
        message = (
            "FHIR Bundle generated but not transmitted: ABDM_FHIR_ENDPOINT is not "
            "configured. Set it to a mock or real FHIR endpoint to push."
        )

    # Only record a push that actually succeeded. Stamping pushed_to_his_at on a
    # failed transmission would make the record claim the hospital has data it
    # never received.
    if pushed:
        summary.pushed_to_his_at = datetime.now(tz=UTC)

    security.audit(
        "summary.pushed_abdm" if pushed else "summary.push_abdm_failed",
        resource=f"summary:{summary.id}",
        detail={
            "transport": transport,
            "pushed": pushed,
            "message": message,
            "bundle_entries": len(bundle.get("entry", [])),
        },
    )
    db.commit()

    # Session data purge: once the record has left for the HIS, the raw
    # artefacts that produced it are no longer needed (Module D deliverable 7).
    if pushed and get_settings().purge_after_push:
        purge_session_data(db, patient_id=summary.patient_id, session_id=summary.session_id)

    return FhirPushResponse(
        status="pushed" if pushed else "generated_not_pushed",
        fhir_resource_type="Bundle",
        pushed=pushed,
        transport=transport,
        message=message,
        bundle=bundle,
    )


@router.get("/{summary_id}/patient-audio")
async def get_patient_audio(
    summary_id: str,
    patient: CurrentPatient,
    db: DbSession,
):
    """Speak the patient-facing summary aloud, in the patient's own language.

    Patient-authenticated, not physician: this is what the VisitDone screen plays
    for the patient after the physician confirms, so the caller is the patient,
    and they may only hear their own record. Ownership is checked as a 404 rather
    than a 403 so a guessed id cannot even confirm a summary exists.

    Speaks ``patient_summary`` — the two plain sentences the model wrote in the
    patient's language — not the clinical body, which is English and full of terms
    the patient is not meant to parse. Uses the same provider chain as every other
    audio path, so it inherits the Sarvam→Azure fallback.
    """
    try:
        summary = db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).first()
    except ValueError:
        raise HTTPException(status_code=404, detail="Summary not found") from None

    if not summary or summary.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Summary not found")

    text = (summary.structured_content or {}).get("patient_summary", "").strip()
    if not text:
        # No patient summary — the deterministic tier cannot write one, and the
        # caller should fall back to showing the text rather than expecting audio.
        raise HTTPException(
            status_code=404, detail="No patient-facing summary is available for this record"
        )

    language = patient.preferred_language or "en"
    name = await tts.synthesize(text, language)
    path = tts.cached_path(name) if name else None
    if path is None:
        raise HTTPException(
            status_code=503, detail="Audio is temporarily unavailable. Please read the summary."
        )

    return StreamingResponse(
        io.BytesIO(path.read_bytes()),
        media_type=tts.media_type_for(name),
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_summary(summary_id: str, patient_id: uuid.UUID, db: Session) -> Summary:
    summary = (
        db.query(Summary)
        .filter(Summary.id == uuid.UUID(summary_id), Summary.patient_id == patient_id)
        .first()
    )
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary


def _to_response(summary: Summary) -> SummaryResponse:
    return SummaryResponse(
        id=str(summary.id),
        patient_id=str(summary.patient_id),
        session_id=str(summary.session_id),
        structured_content=summary.structured_content or {},
        generated_by=summary.generated_by,
        physician_edited=summary.physician_edited,
        status=summary.status,
        confirmed_at=summary.confirmed_at.isoformat() if summary.confirmed_at else None,
    )
