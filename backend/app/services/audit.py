"""Audit logging helper — reusable by every module from Phase 1 onward.

DPDP Act 2023 compliance requires an append-only trail of every read/write of
patient data.  All auth and consent actions call `log_action`; later modules
(interview, documents, summaries, dashboard) should do the same.

Actor modelling
---------------
`audit_logs.actor_id` is a FK to `physicians`, so it cannot hold a patient id.
Rather than introduce a polymorphic FK, patient-initiated actions record the
patient in `detail.patient_id` and leave `actor_id` NULL.  Physician-initiated
actions (Phase 5) pass `physician_id` and populate the FK properly.
This is documented in docs/design/03-data-model.md.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.models import AuditLog


def log_action(
    db: Session,
    *,
    action: str,
    resource: str,
    patient_id: uuid.UUID | None = None,
    physician_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """Append one audit entry.

    Flushes but does not commit — the caller commits as part of its own
    transaction so the audit entry and the action it describes land atomically.

    Parameters
    ----------
    action:
        Short dotted verb, e.g. "patient.register", "consent.grant".
    resource:
        Target identifier, e.g. "patient:<uuid>" or "consent:<uuid>".  Never
        put raw identifiers such as Aadhaar numbers here.
    patient_id:
        Patient who performed / was the subject of the action, if any.
    physician_id:
        Physician actor, if any. Populates the actor_id FK.
    detail:
        Extra JSON context for forensics. Must not contain secrets or raw PII.
    """
    payload: dict = dict(detail or {})
    if patient_id is not None:
        payload["patient_id"] = str(patient_id)

    entry = AuditLog(
        id=uuid.uuid4(),
        actor_id=physician_id,
        action=action,
        resource=resource,
        detail=payload or None,
        timestamp=datetime.now(tz=UTC),
    )
    db.add(entry)
    db.flush()
    return entry
