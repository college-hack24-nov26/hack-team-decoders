"""Shared FastAPI dependencies for auth and consent enforcement.

Reusable `Annotated` aliases that other route modules import.  Later phases
(interview, documents, summaries) should depend on these rather than
re-implementing auth/consent checks.

Usage in a later module::

    from app.dependencies import ConsentedPatient, DbSession, require_consent_scope

    @router.post("/interview/sessions")
    def start_session(patient: ConsentedPatient, db: DbSession): ...

    # or, to require a specific consent scope:
    @router.post("/documents")
    def upload(patient: Annotated[Patient, Depends(require_consent_scope("documents"))]): ...
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import ConsentRecord, Patient, Physician
from app.services.jwt import decode_patient_token, decode_physician_token

# ---------------------------------------------------------------------------
# Base aliases
# ---------------------------------------------------------------------------

DbSession = Annotated[Session, Depends(get_db)]

_bearer_scheme = HTTPBearer(auto_error=False)
_BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


# ---------------------------------------------------------------------------
# Auth dependency — extract current patient from JWT
# ---------------------------------------------------------------------------


def get_current_patient(credentials: _BearerCredentials, db: DbSession) -> Patient:
    """Validate the bearer JWT and return the Patient ORM object.

    Raises 401 if the token is missing, malformed, expired, or refers to a
    patient that no longer exists.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    patient_id = decode_patient_token(credentials.credentials)
    if patient_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Patient not found",
        )
    return patient


CurrentPatient = Annotated[Patient, Depends(get_current_patient)]


# ---------------------------------------------------------------------------
# Consent enforcement
# ---------------------------------------------------------------------------


def active_consent_for(db: Session, patient_id: uuid.UUID) -> ConsentRecord | None:
    """Return the most recent non-revoked consent record for a patient, or None."""
    return (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.patient_id == patient_id,
            ConsentRecord.revoked_at.is_(None),
        )
        .order_by(ConsentRecord.given_at.desc())
        .first()
    )


def require_valid_consent(patient: CurrentPatient, db: DbSession) -> Patient:
    """Require the authenticated patient to hold a valid, current consent record."""
    if active_consent_for(db, patient.id) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No valid consent record found. Consent is required before proceeding.",
        )
    return patient


ConsentedPatient = Annotated[Patient, Depends(require_valid_consent)]


def require_consent_scope(*required_scopes: str):
    """Build a dependency that requires specific consent scopes to be granted."""

    def _dependency(patient: CurrentPatient, db: DbSession) -> Patient:
        consent = active_consent_for(db, patient.id)
        if consent is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No valid consent record found. Consent is required before proceeding.",
            )

        scope = consent.scope or {}
        missing = [s for s in required_scopes if not scope.get(s)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Consent does not cover required scope(s): {', '.join(missing)}",
            )
        return patient

    return _dependency


# ---------------------------------------------------------------------------
# Physician authentication (RBAC — Module D)
# ---------------------------------------------------------------------------


def get_current_physician(credentials: _BearerCredentials, db: DbSession) -> Physician:
    """Validate a physician bearer JWT and return the Physician row.

    Raises 401 when the token is missing, malformed, expired, minted for a
    patient rather than a physician, or refers to a physician who no longer
    exists or has been deactivated.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    physician_id = decode_physician_token(credentials.credentials)
    if physician_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired physician token",
        )

    physician = db.query(Physician).filter(Physician.id == physician_id).first()
    if physician is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Physician not found",
        )
    if not physician.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This physician account is deactivated",
        )
    return physician


CurrentPhysician = Annotated[Physician, Depends(get_current_physician)]


def require_role(*allowed_roles: str):
    """Dependency factory restricting access to specific physician roles.

    Usage::

        AdminOnly = Annotated[Physician, Depends(require_role("admin"))]
        StaffOrAdmin = Annotated[Physician, Depends(require_role("physician", "admin"))]
    """

    def _dependency(physician: CurrentPhysician) -> Physician:
        if allowed_roles and physician.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{physician.role}' may not perform this action. "
                    f"Required: {', '.join(allowed_roles)}"
                ),
            )
        return physician

    return _dependency
