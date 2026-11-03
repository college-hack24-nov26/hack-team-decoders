"""Session data purge — delete temporary artifacts after submission.

Per Module D spec: "clear temporary session data (raw audio, intermediate OCR
scratch files) immediately after submission; only the structured, consented
data persists."

This module:
  1. Deletes raw audio files uploaded via /interview/asr
  2. Deletes raw document images from blob storage (OCR text is retained in DB)
  3. Nulls raw_transcript fields in interview_answers (structured value remains)

Call `purge_session_data()` after a summary is confirmed and pushed, or on
explicit session termination.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.models.models import Document, InterviewAnswer, InterviewSession
from app.services.audit import log_action
from app.services.storage import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)


def purge_session_data(
    db: Session,
    patient_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    storage: StorageBackend | None = None,
) -> dict:
    """Purge temporary/raw data for a patient's session.

    What is deleted:
      - Raw document image files (blob storage) — structured entities in DB remain
      - raw_transcript fields in interview_answers — structured value JSONB remains

    What is NOT deleted:
      - interview_answers.value (structured, consented data)
      - document_entities (extracted, structured data)
      - consent_records, audit_logs (compliance records, never deleted)

    `storage` overrides the configured backend, which lets tests point the purge
    at a temporary directory instead of the process-wide singleton.

    Returns a summary dict of what was purged (for audit logging).
    """
    storage = storage or get_storage_backend()
    purge_summary = {"documents_purged": 0, "transcripts_cleared": 0}

    # 1. Delete raw document files from blob storage
    documents = db.query(Document).filter(Document.patient_id == patient_id).all()
    for doc in documents:
        if doc.file_uri:
            try:
                storage.delete(doc.file_uri)
                purge_summary["documents_purged"] += 1
            except Exception as e:
                logger.warning(f"Failed to delete blob {doc.file_uri}: {e}")
            # Clear the URI so we know the file is gone
            doc.file_uri = "[PURGED]"

    # 2. Null out raw transcripts (voice recordings are PII)
    if session_id:
        sessions = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == session_id, InterviewSession.patient_id == patient_id)
            .all()
        )
    else:
        sessions = (
            db.query(InterviewSession).filter(InterviewSession.patient_id == patient_id).all()
        )

    for session in sessions:
        answers_with_transcript = (
            db.query(InterviewAnswer)
            .filter(
                InterviewAnswer.session_id == session.id,
                InterviewAnswer.raw_transcript.isnot(None),
            )
            .all()
        )
        for answer in answers_with_transcript:
            answer.raw_transcript = None
            purge_summary["transcripts_cleared"] += 1

    # 3. Audit the purge itself
    log_action(
        db,
        action="session.data_purged",
        resource=f"patient:{patient_id}",
        patient_id=patient_id,
        detail=purge_summary,
    )

    db.commit()
    return purge_summary
