"""Clinic flow — doctor selection, visits, and patient history (F2).

    GET  /doctors                 list selectable doctors, filterable by department
    POST /visits                  book a visit, issue a per-day token number
    GET  /visits/{id}             visit status and its linked records
    GET  /patients/{id}/history   a returning patient's full record

These sit between identify (auth) and the interview. A Visit is created when the
patient picks a doctor, and the interview/summary link back to it as they happen.

All routes are patient-authenticated and enforce ownership: a patient token only
reaches that patient's own visits and history. Listing doctors is the one
exception — it is public catalogue data — but still requires a valid patient
token, because by the time a doctor is chosen the patient has already identified.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentPatient, DbSession
from app.interview.red_flags import RULES_BY_ID
from app.models.models import (
    Doctor,
    Document,
    Patient,
    RedFlag,
    Summary,
    Visit,
)
from app.models.models import (
    InterviewSession as Session_,
)
from app.services.audit import log_action

router = APIRouter(tags=["Clinic"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DoctorItem(BaseModel):
    id: str
    name: str
    department: str
    specialization: str | None
    available: bool
    queue_count: int
    photo_url: str | None


class DoctorsResponse(BaseModel):
    doctors: list[DoctorItem]


class CreateVisitRequest(BaseModel):
    doctor_id: str | None = None
    department: str | None = Field(default=None, max_length=50)
    chief_complaint: str | None = None


class VisitResponse(BaseModel):
    id: str
    patient_id: str
    doctor_id: str | None
    doctor_name: str | None
    department: str | None
    status: str
    token_number: int
    chief_complaint: str | None
    interview_session_id: str | None
    summary_id: str | None
    created_at: str | None
    completed_at: str | None


class HistoryVisit(BaseModel):
    visit_id: str
    date: str
    doctor_name: str | None
    department: str | None
    chief_complaint: str | None
    status: str


class HistorySummary(BaseModel):
    summary_id: str
    date: str
    chief_complaint: str
    hpi_narrative: str


class HistoryDocument(BaseModel):
    document_id: str
    doc_type: str
    date: str | None


class HistoryRedFlag(BaseModel):
    name: str
    severity: str
    date: str


class PatientHistoryResponse(BaseModel):
    patient_info: dict
    visits: list[HistoryVisit]
    summaries: list[HistorySummary]
    documents: list[HistoryDocument]
    red_flags: list[HistoryRedFlag]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _visit_response(visit: Visit, doctor: Doctor | None) -> VisitResponse:
    return VisitResponse(
        id=str(visit.id),
        patient_id=str(visit.patient_id),
        doctor_id=str(visit.doctor_id) if visit.doctor_id else None,
        doctor_name=doctor.name if doctor else None,
        department=visit.department,
        status=visit.status,
        token_number=visit.token_number,
        chief_complaint=visit.chief_complaint,
        interview_session_id=(
            str(visit.interview_session_id) if visit.interview_session_id else None
        ),
        summary_id=str(visit.summary_id) if visit.summary_id else None,
        created_at=visit.created_at.isoformat() if visit.created_at else None,
        completed_at=visit.completed_at.isoformat() if visit.completed_at else None,
    )


def _next_token_number(db: DbSession) -> int:
    """The next token for today. Restarts at 1 each calendar day.

    Counts visits created since midnight UTC rather than using a global sequence,
    so a morning queue reads #1, #2, #3 instead of #418. Two simultaneous
    bookings could in theory compute the same number — acceptable for a kiosk
    demo; a production build would use a per-day counter row with a locked update.
    """
    start_of_day = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    todays = db.query(Visit).filter(Visit.created_at >= start_of_day).count()
    return todays + 1


def _owned_visit(visit_id: str, patient: Patient, db: DbSession) -> Visit:
    try:
        parsed = uuid.UUID(visit_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Visit not found") from None
    visit = db.query(Visit).filter(Visit.id == parsed, Visit.patient_id == patient.id).first()
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/doctors", response_model=DoctorsResponse)
def list_doctors(patient: CurrentPatient, db: DbSession, department: str | None = None):
    """List doctors, optionally filtered by department.

    Patient-authenticated: the kiosk only reaches this after the patient has
    identified. Ordered available-first, then by queue length, so the shortest
    real wait surfaces at the top.
    """
    query = db.query(Doctor)
    if department:
        query = query.filter(Doctor.department == department)

    doctors = query.order_by(Doctor.available.desc(), Doctor.queue_count.asc()).all()
    return DoctorsResponse(
        doctors=[
            DoctorItem(
                id=str(d.id),
                name=d.name,
                department=d.department,
                specialization=d.specialization,
                available=d.available,
                queue_count=d.queue_count,
                photo_url=d.photo_url,
            )
            for d in doctors
        ]
    )


@router.post("/visits", response_model=VisitResponse, status_code=status.HTTP_201_CREATED)
def create_visit(body: CreateVisitRequest, patient: CurrentPatient, db: DbSession):
    """Book a visit and issue a per-day token number.

    A doctor is optional at this point — a patient may pick only a department and
    have a doctor assigned later — but if a doctor is named, their queue grows by
    one so the next patient sees an honest wait.
    """
    doctor: Doctor | None = None
    if body.doctor_id:
        try:
            doctor = db.query(Doctor).filter(Doctor.id == uuid.UUID(body.doctor_id)).first()
        except ValueError:
            raise HTTPException(status_code=422, detail="doctor_id must be a UUID") from None
        if doctor is None:
            raise HTTPException(status_code=404, detail="Doctor not found")

    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        doctor_id=doctor.id if doctor else None,
        department=body.department or (doctor.department if doctor else None),
        status="registered",
        token_number=_next_token_number(db),
        chief_complaint=body.chief_complaint,
    )
    db.add(visit)

    if doctor is not None:
        doctor.queue_count += 1

    log_action(
        db,
        patient_id=patient.id,
        action="visit.created",
        resource=f"visit:{visit.id}",
        detail={
            "doctor_id": str(doctor.id) if doctor else None,
            "department": visit.department,
            "token_number": visit.token_number,
        },
    )
    db.commit()
    db.refresh(visit)
    return _visit_response(visit, doctor)


@router.get("/visits/{visit_id}", response_model=VisitResponse)
def get_visit(visit_id: str, patient: CurrentPatient, db: DbSession):
    """Return one visit and its linked records. Owned by the caller only."""
    visit = _owned_visit(visit_id, patient, db)
    doctor = (
        db.query(Doctor).filter(Doctor.id == visit.doctor_id).first() if visit.doctor_id else None
    )
    return _visit_response(visit, doctor)


@router.get("/patients/{patient_id}/history", response_model=PatientHistoryResponse)
def patient_history(patient_id: str, patient: CurrentPatient, db: DbSession):
    """A returning patient's full record: visits, past summaries, documents, red flags.

    Ownership is enforced as a 404: a patient token may only read its own history,
    and a mismatched id is indistinguishable from a missing one. The physician
    dashboard has its own routes for cross-patient views.
    """
    try:
        parsed = uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Patient not found") from None

    if parsed != patient.id:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Visits, newest first, with doctor names.
    visit_rows = (
        db.query(Visit, Doctor)
        .outerjoin(Doctor, Visit.doctor_id == Doctor.id)
        .filter(Visit.patient_id == parsed)
        .order_by(Visit.created_at.desc())
        .all()
    )
    visits = [
        HistoryVisit(
            visit_id=str(v.id),
            date=v.created_at.isoformat() if v.created_at else "",
            doctor_name=d.name if d else None,
            department=v.department,
            chief_complaint=v.chief_complaint,
            status=v.status,
        )
        for v, d in visit_rows
    ]

    # Past summaries — brief: chief complaint + HPI narrative only.
    #
    # Ordered by the interview session's start time, because Summary itself has
    # no creation timestamp — confirmed_at is null for drafts, so it cannot
    # order the list. The session's started_at is the summary's effective date.
    summary_rows = (
        db.query(Summary, Session_.started_at)
        .join(Session_, Summary.session_id == Session_.id)
        .filter(Summary.patient_id == parsed)
        .order_by(Session_.started_at.desc())
        .all()
    )
    summaries = []
    for s, started_at in summary_rows:
        content = s.structured_content or {}
        hpi = content.get("hpi") or {}
        summaries.append(
            HistorySummary(
                summary_id=str(s.id),
                date=started_at.isoformat() if started_at else "",
                chief_complaint=content.get("chief_complaint", ""),
                hpi_narrative=(hpi.get("narrative", "") if isinstance(hpi, dict) else ""),
            )
        )

    # Documents.
    doc_rows = (
        db.query(Document)
        .filter(Document.patient_id == parsed)
        .order_by(Document.uploaded_at.desc())
        .all()
    )
    documents = [
        HistoryDocument(
            document_id=str(doc.id),
            doc_type=doc.doc_type,
            date=doc.document_date.isoformat() if doc.document_date else None,
        )
        for doc in doc_rows
    ]

    # Red flags across all of this patient's sessions.
    flag_rows = (
        db.query(RedFlag)
        .join(Session_, RedFlag.session_id == Session_.id)
        .filter(Session_.patient_id == parsed)
        .order_by(RedFlag.triggered_at.desc())
        .all()
    )
    red_flags = [
        HistoryRedFlag(
            name=RULES_BY_ID[f.symptom].name if f.symptom in RULES_BY_ID else f.symptom,
            severity=f.severity,
            date=f.triggered_at.isoformat() if f.triggered_at else "",
        )
        for f in flag_rows
    ]

    log_action(
        db,
        patient_id=parsed,
        action="patient.history_viewed",
        resource=f"patient:{parsed}",
        detail={"visits": len(visits), "summaries": len(summaries)},
    )
    db.commit()

    return PatientHistoryResponse(
        patient_info={
            "name": patient.name,
            "age": patient.age,
            "gender": patient.gender,
            "phone": patient.phone,
            "abha_id": patient.abha_id,
            "preferred_language": patient.preferred_language,
        },
        visits=visits,
        summaries=summaries,
        documents=documents,
        red_flags=red_flags,
    )
