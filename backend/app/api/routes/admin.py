"""Super-admin — the account that sees everything and provisions the rest.

    GET   /admin/overview        system-wide counts for the admin dashboard
    GET   /admin/patients        every patient (with visit counts)
    GET   /admin/audit           recent audit-log entries
    GET   /admin/physicians      every login account
    POST  /admin/physicians      create a physician / staff / admin login
    PATCH /admin/physicians/{id} deactivate or change a login's role
    POST  /admin/doctors         add a selectable doctor
    PATCH /admin/doctors/{id}    edit a doctor (availability, queue, details)

Every route requires a physician token whose role is ``admin``. That check is the
single gate: a regular physician or staff token gets 403, a patient token gets
401 (wrong token type). The role ladder already existed on the Physician model
and in `require_role`; this module is what finally uses the top rung.

Creating a login here is the only way clinician and admin accounts come into
being — there is no self-signup, by design, because these accounts read patient
records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.dependencies import DbSession, require_role
from app.models.models import (
    AuditLog,
    Doctor,
    Patient,
    Physician,
    RedFlag,
    Summary,
    Visit,
)
from app.models.models import (
    InterviewSession as Session_,
)
from app.services.audit import log_action
from app.services.password import hash_password

router = APIRouter(prefix="/admin", tags=["Admin"])

#: The whole module is admin-only. A physician/staff token is a 403 here.
AdminOnly = Annotated[Physician, Depends(require_role("admin"))]

_VALID_ROLES = ("physician", "staff", "admin")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OverviewResponse(BaseModel):
    patients: int
    visits_total: int
    visits_today: int
    interviews: int
    summaries_total: int
    summaries_confirmed: int
    red_flags: int
    doctors: int
    physicians: int


class AdminPatient(BaseModel):
    id: str
    name: str
    age: int | None
    gender: str | None
    phone: str | None
    abha_id: str | None
    preferred_language: str
    visit_count: int
    created_at: str | None


class AuditEntry(BaseModel):
    id: str
    actor_id: str | None
    action: str
    resource: str
    timestamp: str


class PhysicianItem(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: str | None


class CreatePhysicianRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=6, max_length=200)
    full_name: str = Field(..., min_length=1, max_length=200)
    role: str = Field(default="physician")


class UpdatePhysicianRequest(BaseModel):
    is_active: bool | None = None
    role: str | None = None


class CreateDoctorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    department: str = Field(..., min_length=1, max_length=50)
    specialization: str | None = None
    photo_url: str | None = None


class UpdateDoctorRequest(BaseModel):
    name: str | None = None
    department: str | None = Field(default=None, max_length=50)
    specialization: str | None = None
    available: bool | None = None
    queue_count: int | None = Field(default=None, ge=0)
    photo_url: str | None = None


class DoctorItem(BaseModel):
    id: str
    name: str
    department: str
    specialization: str | None
    available: bool
    queue_count: int
    photo_url: str | None


# ---------------------------------------------------------------------------
# Read — "see all the things"
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewResponse)
def overview(admin: AdminOnly, db: DbSession):
    """System-wide counts for the admin landing page."""
    start_of_day = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return OverviewResponse(
        patients=db.query(Patient).count(),
        visits_total=db.query(Visit).count(),
        visits_today=db.query(Visit).filter(Visit.created_at >= start_of_day).count(),
        interviews=db.query(Session_).count(),
        summaries_total=db.query(Summary).count(),
        summaries_confirmed=db.query(Summary).filter(Summary.status == "confirmed").count(),
        red_flags=db.query(RedFlag).count(),
        doctors=db.query(Doctor).count(),
        physicians=db.query(Physician).count(),
    )


@router.get("/patients", response_model=list[AdminPatient])
def list_patients(admin: AdminOnly, db: DbSession, limit: int = 200):
    """Every patient, newest first, with a visit count. Capped to keep it light.

    Visit counts come from one grouped query rather than a count per patient, so
    the list is a fixed two queries regardless of how many patients there are.
    """
    patients = db.query(Patient).order_by(Patient.created_at.desc()).limit(limit).all()

    counts: dict[uuid.UUID, int] = dict(
        db.query(Visit.patient_id, func.count(Visit.id)).group_by(Visit.patient_id).all()
    )

    return [
        AdminPatient(
            id=str(p.id),
            name=p.name,
            age=p.age,
            gender=p.gender,
            phone=p.phone,
            abha_id=p.abha_id,
            preferred_language=p.preferred_language,
            visit_count=counts.get(p.id, 0),
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in patients
    ]


@router.get("/audit", response_model=list[AuditEntry])
def recent_audit(admin: AdminOnly, db: DbSession, limit: int = 100):
    """The most recent audit-log entries — the compliance trail, admin-visible."""
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [
        AuditEntry(
            id=str(r.id),
            actor_id=str(r.actor_id) if r.actor_id else None,
            action=r.action,
            resource=r.resource,
            timestamp=r.timestamp.isoformat() if r.timestamp else "",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Physician (login account) management
# ---------------------------------------------------------------------------


@router.get("/physicians", response_model=list[PhysicianItem])
def list_physicians(admin: AdminOnly, db: DbSession):
    rows = db.query(Physician).order_by(Physician.created_at.desc()).all()
    return [_physician_item(p) for p in rows]


@router.post("/physicians", response_model=PhysicianItem, status_code=status.HTTP_201_CREATED)
def create_physician(body: CreatePhysicianRequest, admin: AdminOnly, db: DbSession):
    """Provision a clinician or admin login. Email is unique and lower-cased."""
    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=422, detail=f"role must be one of {', '.join(_VALID_ROLES)}"
        )
    email = body.email.strip().lower()
    if db.query(Physician).filter(Physician.email == email).first():
        raise HTTPException(status_code=409, detail="A physician with this email already exists")

    physician = Physician(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name.strip(),
        role=body.role,
        is_active=True,
    )
    db.add(physician)
    log_action(
        db,
        physician_id=admin.id,
        action="admin.physician_created",
        resource=f"physician:{physician.id}",
        detail={"email": email, "role": body.role},
    )
    db.commit()
    db.refresh(physician)
    return _physician_item(physician)


@router.patch("/physicians/{physician_id}", response_model=PhysicianItem)
def update_physician(
    physician_id: str, body: UpdatePhysicianRequest, admin: AdminOnly, db: DbSession
):
    """Deactivate a login or change its role.

    An admin cannot deactivate or demote their own account — locking the last
    admin out of the system is a footgun, and self-lockout is the common way it
    happens.
    """
    physician = _get_physician(physician_id, db)

    if physician.id == admin.id and (body.is_active is False or body.role not in (None, "admin")):
        raise HTTPException(
            status_code=400, detail="You cannot deactivate or demote your own admin account"
        )

    if body.role is not None:
        if body.role not in _VALID_ROLES:
            raise HTTPException(
                status_code=422, detail=f"role must be one of {', '.join(_VALID_ROLES)}"
            )
        physician.role = body.role
    if body.is_active is not None:
        physician.is_active = body.is_active

    log_action(
        db,
        physician_id=admin.id,
        action="admin.physician_updated",
        resource=f"physician:{physician.id}",
        detail={"is_active": physician.is_active, "role": physician.role},
    )
    db.commit()
    db.refresh(physician)
    return _physician_item(physician)


# ---------------------------------------------------------------------------
# Doctor (kiosk-selectable) management
# ---------------------------------------------------------------------------


@router.post("/doctors", response_model=DoctorItem, status_code=status.HTTP_201_CREATED)
def create_doctor(body: CreateDoctorRequest, admin: AdminOnly, db: DbSession):
    doctor = Doctor(
        id=uuid.uuid4(),
        name=body.name.strip(),
        department=body.department.strip(),
        specialization=body.specialization,
        available=True,
        queue_count=0,
        photo_url=body.photo_url,
    )
    db.add(doctor)
    log_action(
        db,
        physician_id=admin.id,
        action="admin.doctor_created",
        resource=f"doctor:{doctor.id}",
        detail={"name": doctor.name, "department": doctor.department},
    )
    db.commit()
    db.refresh(doctor)
    return _doctor_item(doctor)


@router.patch("/doctors/{doctor_id}", response_model=DoctorItem)
def update_doctor(doctor_id: str, body: UpdateDoctorRequest, admin: AdminOnly, db: DbSession):
    try:
        doctor = db.query(Doctor).filter(Doctor.id == uuid.UUID(doctor_id)).first()
    except ValueError:
        raise HTTPException(status_code=404, detail="Doctor not found") from None
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")

    for field in ("name", "department", "specialization", "available", "queue_count", "photo_url"):
        value = getattr(body, field)
        if value is not None:
            setattr(doctor, field, value)

    log_action(
        db,
        physician_id=admin.id,
        action="admin.doctor_updated",
        resource=f"doctor:{doctor.id}",
        detail={"available": doctor.available, "queue_count": doctor.queue_count},
    )
    db.commit()
    db.refresh(doctor)
    return _doctor_item(doctor)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_physician(physician_id: str, db: DbSession) -> Physician:
    try:
        physician = db.query(Physician).filter(Physician.id == uuid.UUID(physician_id)).first()
    except ValueError:
        raise HTTPException(status_code=404, detail="Physician not found") from None
    if physician is None:
        raise HTTPException(status_code=404, detail="Physician not found")
    return physician


def _physician_item(p: Physician) -> PhysicianItem:
    return PhysicianItem(
        id=str(p.id),
        email=p.email,
        full_name=p.full_name,
        role=p.role,
        is_active=p.is_active,
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


def _doctor_item(d: Doctor) -> DoctorItem:
    return DoctorItem(
        id=str(d.id),
        name=d.name,
        department=d.department,
        specialization=d.specialization,
        available=d.available,
        queue_count=d.queue_count,
        photo_url=d.photo_url,
    )
