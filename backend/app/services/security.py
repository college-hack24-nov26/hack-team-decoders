"""Centralized Security Layer — Module D.

Every AI call (ASR, OCR, entity extraction, LLM summariser) and every write or
export of patient data goes through this component. It is the one place that
answers "is this operation allowed for this patient right now?" and records that
the operation happened.

Why it exists as an object rather than a FastAPI dependency
-----------------------------------------------------------
`require_consent_scope(...)` in app/dependencies.py gates a *route* on the
consent of the *caller*. That is the right check when the patient is the caller
(interview, document upload), but it cannot express two cases Module D needs:

  1. A physician calls an endpoint that processes a *patient's* data
     (summary generation, ABDM push). The caller has no consent record; the
     patient does. The check has to be against the patient the data belongs to.
  2. An operation needs a scope check partway through a request, not at the
     door — e.g. only push to ABDM if `abdm_push` was granted.

So the dependency stays as the outer gate, and this layer is the inner gate that
travels with the data. Defence in depth, and the only way the physician-facing
endpoints can be consent-checked at all.

Usage
-----
Patient-initiated (caller is the patient)::

    security = SecurityLayer(db, patient)
    security.authorize("interview")

Physician-initiated (caller acts on a patient's record)::

    security = SecurityLayer.for_patient(db, session.patient_id, physician_id=physician.id)
    security.authorize("interview")            # 403 if patient revoked consent
    ...
    security.audit("summary.generated", resource=f"summary:{s.id}")
    db.commit()                                 # caller commits

Audit entries are flushed, not committed — the caller commits so the audit row
and the action it describes land in the same transaction. An entry flushed after
the final commit is silently discarded, so always audit before committing.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import ConsentRecord, Patient
from app.services.audit import log_action


class ConsentDenied(HTTPException):
    """Raised when an operation is not covered by a valid consent record.

    A subclass of HTTPException so routes need no special handling, but a
    distinct type so tests and callers can assert on the reason.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class SecurityLayer:
    """Consent enforcement + audit for one patient, within one request."""

    def __init__(
        self,
        db: Session,
        patient: Patient,
        *,
        physician_id: uuid.UUID | None = None,
    ) -> None:
        self._db = db
        self._patient = patient
        self._physician_id = physician_id

    # ── Construction ──────────────────────────────────────────────────────

    @classmethod
    def for_patient(
        cls,
        db: Session,
        patient_id: uuid.UUID,
        *,
        physician_id: uuid.UUID | None = None,
    ) -> SecurityLayer:
        """Build a layer for a patient id, for physician-initiated operations.

        Raises 404 if the patient does not exist — an operation on a missing
        patient is a bug, not a permission problem.
        """
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if patient is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found",
            )
        return cls(db, patient, physician_id=physician_id)

    # ── State ─────────────────────────────────────────────────────────────

    @property
    def patient(self) -> Patient:
        return self._patient

    @property
    def patient_id(self) -> uuid.UUID:
        return self._patient.id

    def active_consent(self) -> ConsentRecord | None:
        """The most recent consent for this patient that has not been revoked."""
        return (
            self._db.query(ConsentRecord)
            .filter(
                ConsentRecord.patient_id == self._patient.id,
                ConsentRecord.revoked_at.is_(None),
            )
            .order_by(ConsentRecord.given_at.desc())
            .first()
        )

    # ── Enforcement ───────────────────────────────────────────────────────

    def authorize(self, *required_scopes: str) -> ConsentRecord:
        """Assert the patient has current consent covering every named scope.

        Returns the consent record so callers can inspect terms such as
        `retention_days`. Raises ConsentDenied (403) otherwise.
        """
        consent = self.active_consent()

        if consent is None:
            raise ConsentDenied("No valid consent record for this patient. Operation blocked.")

        scope = consent.scope or {}
        missing = [s for s in required_scopes if not scope.get(s)]
        if missing:
            raise ConsentDenied(f"Consent does not cover: {', '.join(missing)}. Operation blocked.")

        return consent

    def is_authorized(self, *required_scopes: str) -> bool:
        """Non-raising form of authorize(), for branching rather than gating."""
        try:
            self.authorize(*required_scopes)
        except ConsentDenied:
            return False
        return True

    # ── Audit ─────────────────────────────────────────────────────────────

    def audit(self, action: str, resource: str, detail: dict | None = None) -> None:
        """Record an audit entry attributed to this patient (and physician, if any).

        Flushes only — the caller must commit.
        """
        log_action(
            self._db,
            action=action,
            resource=resource,
            patient_id=self._patient.id,
            physician_id=self._physician_id,
            detail=detail,
        )

    def authorize_and_audit(
        self,
        *required_scopes: str,
        action: str,
        resource: str,
        detail: dict | None = None,
    ) -> ConsentRecord:
        """Check consent, then record that the operation was performed."""
        consent = self.authorize(*required_scopes)
        self.audit(action, resource, detail)
        return consent
