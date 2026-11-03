"""Auth routes — Step 1 (Identify) of the patient journey.

    POST /auth/register        new patient, no ABHA
    POST /auth/abha/lookup     ABHA identity lookup   (MOCKED)
    POST /auth/aadhaar/lookup  Aadhaar fallback       (MOCKED)
    POST /auth/login           re-issue a session token

Every action writes an audit_logs entry.

SECURITY NOTE (demo limitation, must be fixed before any real deployment):
these endpoints issue a JWT without verifying possession of the identity —
there is no OTP challenge, because the mock AuthProvider cannot send one, and
`/auth/login` accepts a bare patient_id. See app/services/auth_provider.py.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import DbSession
from app.models.models import Doctor, Patient, Physician, Visit
from app.services.audit import log_action
from app.services.auth_provider import get_auth_provider, hash_aadhaar
from app.services.jwt import create_patient_token, create_physician_token
from app.services.password import verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """New patient registration (no ABHA)."""

    name: str = Field(..., min_length=1, max_length=200)
    age: int = Field(..., ge=0, le=150)
    gender: str = Field(..., pattern="^(male|female|other)$")
    phone: str = Field(..., min_length=10, max_length=15)
    preferred_language: str = Field(default="en", max_length=10)
    # Optional: set when the patient came through the Aadhaar fallback path.
    aadhaar: str | None = Field(default=None, min_length=12, max_length=14)


class SessionResponse(BaseModel):
    """Issued whenever a patient session starts."""

    patient_id: str
    token: str
    name: str


class AbhaLookupRequest(BaseModel):
    abha_id: str = Field(..., min_length=5, max_length=20)


class AadhaarLookupRequest(BaseModel):
    aadhaar: str = Field(..., min_length=12, max_length=14)


class LookupResponse(BaseModel):
    """Result of an identity lookup.

    `found=False` is not an error — the UI routes the patient to registration.
    """

    found: bool
    patient_id: str | None = None
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    phone: str | None = None
    token: str | None = None


class LoginRequest(BaseModel):
    patient_id: str


class ReturningLoginRequest(BaseModel):
    """Phone-based lookup for a returning patient.

    ``name`` is accepted but not required — it is only used to disambiguate if
    several patients ever share a phone, which the kiosk flow does not currently
    produce. No password: this is a walk-up kiosk, not a bank. Documented as a
    demo limitation, same as /auth/login.
    """

    phone: str = Field(..., min_length=6, max_length=15)
    name: str | None = Field(default=None, max_length=200)


class PastVisit(BaseModel):
    """One line of a returning patient's history."""

    visit_id: str
    date: str
    doctor_name: str | None
    department: str | None
    chief_complaint: str | None
    status: str


class ReturningLoginResponse(BaseModel):
    found: bool
    patient_id: str | None = None
    token: str | None = None
    name: str | None = None
    preferred_language: str | None = None
    visits: list[PastVisit] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue_session(db: Session, patient: Patient, *, action: str, detail: dict) -> str:
    """Audit the login/registration and return a fresh JWT."""
    log_action(
        db,
        patient_id=patient.id,
        action=action,
        resource=f"patient:{patient.id}",
        detail=detail,
    )
    db.commit()
    return create_patient_token(patient.id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def register_patient(body: RegisterRequest, db: DbSession):
    """Register a new patient who has no ABHA ID, and start a session."""
    patient = Patient(
        id=uuid.uuid4(),
        name=body.name,
        age=body.age,
        gender=body.gender,
        phone=body.phone,
        preferred_language=body.preferred_language,
        # Only ever a salted hash + last 4 digits; raw Aadhaar is never stored.
        aadhaar_ref=hash_aadhaar(body.aadhaar) if body.aadhaar else None,
    )
    db.add(patient)
    db.flush()

    token = _issue_session(
        db,
        patient,
        action="patient.register",
        detail={
            "method": "aadhaar_fallback" if body.aadhaar else "new_registration",
            "language": body.preferred_language,
        },
    )
    return SessionResponse(patient_id=str(patient.id), token=token, name=patient.name)


@router.post("/abha/lookup", response_model=LookupResponse)
def abha_lookup(body: AbhaLookupRequest, db: DbSession):
    """Look up a patient by ABHA ID and start a session if found.

    MOCKED — see app/services/auth_provider.py. Creates a local patient record
    the first time a given ABHA ID is seen.
    """
    result = get_auth_provider().lookup_abha(body.abha_id)

    if not result.found:
        log_action(
            db,
            patient_id=None,
            action="auth.abha_lookup.not_found",
            resource=f"abha:{body.abha_id}",
            detail={"abha_id": body.abha_id},
        )
        db.commit()
        return LookupResponse(found=False)

    patient = db.query(Patient).filter(Patient.abha_id == result.abha_id).first()
    is_new = patient is None
    if patient is None:
        patient = Patient(
            id=uuid.uuid4(),
            abha_id=result.abha_id,
            name=result.name or "Unknown",
            age=result.age,
            gender=result.gender,
            phone=result.phone,
            preferred_language="en",
        )
        db.add(patient)
        db.flush()

    token = _issue_session(
        db,
        patient,
        action="auth.abha_lookup.found",
        detail={"abha_id": result.abha_id, "created_patient": is_new, "provider": "mock"},
    )
    return LookupResponse(
        found=True,
        patient_id=str(patient.id),
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        phone=patient.phone,
        token=token,
    )


@router.post("/aadhaar/lookup", response_model=LookupResponse)
def aadhaar_lookup(body: AadhaarLookupRequest, db: DbSession):
    """Aadhaar fallback for patients without an ABHA ID.

    MOCKED — no UIDAI e-KYC is performed. If we have seen this Aadhaar
    reference before we resume that patient; otherwise we return found=False
    so the UI collects name/age/gender/phone via /auth/register.
    """
    result = get_auth_provider().lookup_aadhaar(body.aadhaar)

    if result.aadhaar_ref is None:
        # Shape validation failed (not 12 digits).
        log_action(
            db,
            patient_id=None,
            action="auth.aadhaar_lookup.invalid",
            resource="aadhaar:<redacted>",
            detail={"reason": "malformed"},
        )
        db.commit()
        return LookupResponse(found=False)

    # Match a returning patient by hashed reference — never by raw number.
    patient = db.query(Patient).filter(Patient.aadhaar_ref == result.aadhaar_ref).first()

    if patient is None:
        log_action(
            db,
            patient_id=None,
            action="auth.aadhaar_lookup.not_found",
            resource="aadhaar:<redacted>",
            detail={"provider": "mock", "next": "register"},
        )
        db.commit()
        return LookupResponse(found=False)

    token = _issue_session(
        db,
        patient,
        action="auth.aadhaar_lookup.found",
        detail={"provider": "mock"},
    )
    return LookupResponse(
        found=True,
        patient_id=str(patient.id),
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        phone=patient.phone,
        token=token,
    )


@router.post("/login", response_model=SessionResponse)
def login(body: LoginRequest, db: DbSession):
    """Re-issue a session token for an existing patient.

    SECURITY: accepts a bare patient_id with no second factor. Demo-only; a
    real build must require an OTP or ABDM-issued assertion here.
    """
    try:
        patient_uuid = uuid.UUID(body.patient_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid patient_id format",
        ) from exc

    patient = db.query(Patient).filter(Patient.id == patient_uuid).first()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found. Please register first.",
        )

    token = _issue_session(db, patient, action="auth.login", detail={"method": "patient_id"})
    return SessionResponse(token=token, patient_id=str(patient.id), name=patient.name)


def _recent_visits(db: Session, patient_id: uuid.UUID, limit: int = 10) -> list[PastVisit]:
    """The patient's most recent visits, newest first, with doctor names resolved."""
    rows = (
        db.query(Visit, Doctor)
        .outerjoin(Doctor, Visit.doctor_id == Doctor.id)
        .filter(Visit.patient_id == patient_id)
        .order_by(Visit.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        PastVisit(
            visit_id=str(visit.id),
            date=visit.created_at.isoformat() if visit.created_at else "",
            doctor_name=doctor.name if doctor else None,
            department=visit.department,
            chief_complaint=visit.chief_complaint,
            status=visit.status,
        )
        for visit, doctor in rows
    ]


@router.post("/login/returning", response_model=ReturningLoginResponse)
def login_returning(body: ReturningLoginRequest, db: DbSession):
    """Look up a returning patient by phone and resume their record.

    SECURITY: phone alone, no OTP. Acceptable for a walk-up kiosk MVP and no
    worse than /auth/login, but a real deployment must add a second factor —
    anyone who knows a phone number could otherwise pull that patient's history.

    ``found=False`` is not an error: the UI routes the patient to registration.
    """
    phone = body.phone.strip()
    query = db.query(Patient).filter(Patient.phone == phone)
    if body.name:
        # Only used to disambiguate; harmless when it matches nobody, because the
        # branch below still falls through to the phone-only match.
        named = query.filter(Patient.name == body.name.strip()).first()
        patient = named or query.first()
    else:
        patient = query.first()

    if patient is None:
        log_action(
            db,
            patient_id=None,
            action="auth.returning_login.not_found",
            resource="patient:unknown",
            detail={"phone_len": len(phone)},  # never log the number itself
        )
        db.commit()
        return ReturningLoginResponse(found=False)

    token = _issue_session(db, patient, action="auth.returning_login", detail={"method": "phone"})
    return ReturningLoginResponse(
        found=True,
        patient_id=str(patient.id),
        token=token,
        name=patient.name,
        preferred_language=patient.preferred_language,
        visits=_recent_visits(db, patient.id, limit=10),
    )


# ---------------------------------------------------------------------------
# Physician login (Phase 4 — dashboard)
# ---------------------------------------------------------------------------


class PhysicianLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class PhysicianLoginResponse(BaseModel):
    token: str
    physician_id: str
    name: str
    email: str
    role: str


@router.post("/physician/login", response_model=PhysicianLoginResponse)
def physician_login(body: PhysicianLoginRequest, db: DbSession):
    """Issue a physician JWT for the dashboard.

    The frontend has called this route since the dashboard shipped; it did not
    exist, so every real login attempt failed and only the demo bypass worked.

    Unlike the patient routes above, this one does verify a credential. The same
    401 is returned for an unknown email and a wrong password, so the response
    cannot be used to enumerate which clinicians have accounts.
    """
    physician = db.query(Physician).filter(Physician.email == body.email.strip().lower()).first()

    if physician is None or not verify_password(body.password, physician.hashed_password):
        log_action(
            db,
            action="physician.login_failed",
            resource="physician:unknown",
            detail={"email": body.email.strip().lower()},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not physician.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This physician account is deactivated",
        )

    token = create_physician_token(physician.id)

    log_action(
        db,
        action="physician.login",
        resource=f"physician:{physician.id}",
        detail={"email": physician.email, "role": physician.role},
    )

    return PhysicianLoginResponse(
        token=token,
        physician_id=str(physician.id),
        name=physician.full_name,
        email=physician.email,
        role=physician.role,
    )
