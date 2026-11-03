"""Consent routes — granular, revocable, audio-confirmed consent capture.

    POST   /consent          record a consent grant
    GET    /consent/current  report whether a valid current consent exists
    DELETE /consent/{id}     revoke a consent

`GET /consent/current` is what makes the "no screen past consent" rule real:
the frontend route guard calls it and cannot proceed on client state alone.
Every action writes an audit_logs entry.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.dependencies import CurrentPatient, DbSession, active_consent_for
from app.interview import languages, tts
from app.interview.consent_script import get_consent_text
from app.models.models import ConsentRecord
from app.services.audit import log_action
from app.services.translation import translate_from_english

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consent", tags=["consent"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConsentScope(BaseModel):
    """Granular consent scope — what the patient is agreeing to.

    Stored verbatim as JSONB in consent_records.scope so the exact terms the
    patient agreed to remain auditable even if these defaults change later.
    """

    interview: bool = Field(default=True, description="AI interview data collection")
    documents: bool = Field(default=True, description="Document upload and OCR")
    abdm_push: bool = Field(default=False, description="Push summary to ABDM/ABHA record")
    share_with_physician: bool = Field(
        default=True, description="Share data with treating physician"
    )
    retention_days: int = Field(default=90, ge=1, le=365, description="Retention period in days")


#: How the terms reached the patient, in descending fidelity.
#:
#: ``audio`` is the designed path and the only one that works for a patient who
#: cannot read. The other two exist because insisting on audio in every case is
#: friction without consent value: a literate patient at a busy kiosk can read
#: faster than four clips play, and a device with no usable voice would otherwise
#: block consent entirely. What matters for an audit is that the route is
#: recorded honestly rather than every record claiming audio it never played.
ConfirmationMethod = Literal["audio", "read_by_patient", "read_by_attendant"]


class ConsentCreateRequest(BaseModel):
    scope: ConsentScope
    language: str = Field(..., min_length=2, max_length=10)
    audio_confirmed: bool = Field(
        ..., description="Patient was shown and confirmed the explanation"
    )
    confirmation_method: ConfirmationMethod = Field(
        default="audio",
        description="How the explanation reached the patient: heard, self-read, or read aloud by staff",
    )


class ConsentResponse(BaseModel):
    id: str
    patient_id: str
    scope: ConsentScope
    language: str
    audio_confirmed: bool
    given_at: str


class ConsentStatusResponse(BaseModel):
    """Authoritative answer to 'may this patient proceed?'."""

    active: bool
    consent_id: str | None = None
    scope: dict | None = None
    language: str | None = None
    audio_confirmed: bool | None = None
    given_at: str | None = None


class ConsentRevokeResponse(BaseModel):
    id: str
    revoked_at: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/audio/{section}")
async def get_consent_audio(section: str, patient: CurrentPatient, language: str | None = None):
    """Speak one consent section aloud, using the server TTS provider.

    Deliberately **not** consent-gated, unlike the interview audio route. This is
    the audio that explains consent, so requiring consent to hear it would be
    circular and would lock out every patient who cannot read the screen.
    ``CurrentPatient`` still applies, so it is not open to the internet.

    The text is looked up from a fixed server-side script rather than accepted
    from the caller: an endpoint that forwards arbitrary text to a paid TTS
    provider is an open invoice.

    Returns 503 when no TTS provider is configured, which the frontend treats as
    a signal to fall back to the browser's own speech synthesis.
    """
    spoken = language or patient.preferred_language or "en"

    text = get_consent_text(section, spoken)
    if text is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown consent section '{section}'.",
        )

    # The script is written in English and Hindi only. For any other language
    # get_consent_text falls back to English, which would have the patient read
    # their rights in a language they may not speak. Translate instead, cached
    # because the same four sections repeat for every patient.
    if languages.get(spoken).code not in {"en", "hi"}:
        rendered = await translate_from_english(text, spoken)
        if rendered:
            text = rendered
        else:
            logger.warning(
                "consent.audio: no %s translation available for '%s'; speaking English",
                spoken,
                section,
            )

    clip = await tts.synthesize(text, spoken)
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server text-to-speech is not available.",
        )

    path = tts.cached_path(clip)
    if path is None:  # pragma: no cover - synthesize just wrote it
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server text-to-speech is not available.",
        )

    return FileResponse(
        path,
        media_type=tts.media_type_for(clip),
        # The script is fixed, so the same few clips serve every patient all day.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("", response_model=ConsentResponse, status_code=status.HTTP_201_CREATED)
def create_consent(body: ConsentCreateRequest, patient: CurrentPatient, db: DbSession):
    """Record a consent grant for the authenticated patient.

    Consent is required to have been explained. `audio_confirmed` records that
    the explanation reached the patient, and `confirmation_method` records how —
    heard, read by the patient, or read aloud by staff. The DPDP-relevant point
    is that the terms were conveyed, not that a speaker was used; a patient who
    cannot read still depends on the audio route, which is why it is the default.
    """
    # Recorded, not enforced. Ticking each scope is the affirmation; the narration
    # is how the terms reach someone who cannot read them. Rejecting a consent
    # because playback did not finish punished the literate patient in a queue
    # without making the other patient any better informed — and it desynced from
    # the UI, which had already stopped requiring it, so the patient got a 400
    # from a Continue button that looked enabled.
    #
    # `audio_confirmed` and `confirmation_method` still persist, so an audit can
    # tell how the terms were conveyed in any individual case.

    if not body.scope.interview or not body.scope.share_with_physician:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Consent for 'interview' and 'share_with_physician' is required to proceed. "
                "Optional scopes (documents, abdm_push) may be declined."
            ),
        )

    consent = ConsentRecord(
        id=uuid.uuid4(),
        patient_id=patient.id,
        scope=body.scope.model_dump(),
        language=body.language,
        audio_confirmed=body.audio_confirmed,
        given_at=datetime.now(tz=UTC),
    )
    db.add(consent)
    db.flush()

    log_action(
        db,
        patient_id=patient.id,
        action="consent.grant",
        resource=f"consent:{consent.id}",
        detail={
            "scope": body.scope.model_dump(),
            "language": body.language,
            "audio_confirmed": body.audio_confirmed,
            # Kept in the audit trail rather than on the consent row: the
            # existing schema has no column for it, and audit_logs.detail is
            # already the append-only record an auditor would read.
            "confirmation_method": body.confirmation_method,
        },
    )
    db.commit()

    return ConsentResponse(
        id=str(consent.id),
        patient_id=str(consent.patient_id),
        scope=body.scope,
        language=consent.language,
        audio_confirmed=consent.audio_confirmed,
        given_at=consent.given_at.isoformat(),
    )


@router.get("/current", response_model=ConsentStatusResponse)
def current_consent(patient: CurrentPatient, db: DbSession):
    """Report whether the authenticated patient holds a valid current consent.

    Returns 200 with `active=false` (not an error) when there is none, so the
    frontend can tell "not consented" apart from "not authenticated" (401).
    """
    consent = active_consent_for(db, patient.id)
    if consent is None:
        return ConsentStatusResponse(active=False)

    return ConsentStatusResponse(
        active=True,
        consent_id=str(consent.id),
        scope=consent.scope,
        language=consent.language,
        audio_confirmed=consent.audio_confirmed,
        given_at=consent.given_at.isoformat(),
    )


@router.delete("/{consent_id}", response_model=ConsentRevokeResponse)
def revoke_consent(consent_id: str, patient: CurrentPatient, db: DbSession):
    """Revoke a consent record.

    Sets `revoked_at`, which immediately causes `require_valid_consent` (and
    therefore every consent-gated endpoint) to reject this patient until new
    consent is granted.
    """
    try:
        cid = uuid.UUID(consent_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid consent_id format",
        ) from exc

    consent = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.id == cid, ConsentRecord.patient_id == patient.id)
        .first()
    )
    if consent is None:
        # Also covers another patient's consent id — do not leak existence.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consent record not found",
        )

    if consent.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Consent already revoked",
        )

    now = datetime.now(tz=UTC)
    consent.revoked_at = now

    log_action(
        db,
        patient_id=patient.id,
        action="consent.revoke",
        resource=f"consent:{consent.id}",
        detail={"revoked_at": now.isoformat()},
    )
    db.commit()

    return ConsentRevokeResponse(
        id=str(consent.id),
        revoked_at=now.isoformat(),
        message="Consent revoked. Further data processing is blocked until new consent is given.",
    )
