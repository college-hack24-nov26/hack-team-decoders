"""Seed demo data — 3 patients for the live demo.

Run:
    docker compose exec backend python scripts/seed_demo_data.py

Creates:
  1. Ramesh Kumar (ABHA 91-1234-5678-9012) — chest pain, RED FLAGGED
     Completed interview with high-severity answers, one document (lab report
     with abnormal HbA1c), AYUSH mode NOT used.

  2. Priya Sharma (ABHA 91-9876-5432-1098) — fever, AYUSH mode
     Completed interview in AYUSH mode, one prescription document.

  3. Anil Verma (new registration, no ABHA) — abdominal pain, normal
     Completed interview, two documents (prescription + lab report, all normal).

All three have consent records granted and completed interviews ready for the
physician dashboard to view and summarise.
"""

import sys
import uuid
from datetime import UTC, datetime, timedelta

# Must run from the backend directory or with PYTHONPATH set.
sys.path.insert(0, "/app")

from app.db.session import SessionLocal
from app.models.models import (
    ConsentRecord,
    Document,
    DocumentEntity,
    InterviewAnswer,
    InterviewSession,
    Patient,
    RedFlag,
)

db = SessionLocal()


def _uuid():
    return uuid.uuid4()


def _now(offset_minutes=0):
    return datetime.now(tz=UTC) - timedelta(minutes=offset_minutes)


# ---------------------------------------------------------------------------
# Patient 1: Ramesh Kumar — chest pain, RED FLAGGED
# ---------------------------------------------------------------------------

p1 = Patient(
    id=_uuid(),
    abha_id="91-1234-5678-9012",
    name="Ramesh Kumar",
    age=45,
    gender="male",
    phone="9876543210",
    preferred_language="en",
)
db.add(p1)

db.add(
    ConsentRecord(
        id=_uuid(),
        patient_id=p1.id,
        scope={
            "interview": True,
            "documents": True,
            "abdm_push": True,
            "share_with_physician": True,
            "retention_days": 90,
        },
        language="en",
        audio_confirmed=True,
        given_at=_now(30),
    )
)

s1 = InterviewSession(
    id=_uuid(),
    patient_id=p1.id,
    chief_complaint="chest_pain",
    mode="general",
    status="red_flagged",
    started_at=_now(25),
    completed_at=_now(15),
)
db.add(s1)

for field, value in [
    ("chief_complaint", {"answer": "chest_pain"}),
    ("hpi.site", {"answer": "central"}),
    ("hpi.onset", {"answer": "hours"}),
    ("hpi.character", {"answer": "crushing"}),
    ("hpi.radiation", {"answer": "left_arm"}),
    ("hpi.severity", {"answer": 9}),
    ("hpi.associated_symptoms", {"answer": ["breathlessness", "sweating"]}),
    ("past_medical.conditions", {"answer": ["diabetes", "hypertension"]}),
    ("drug_history.current_meds", {"answer": "Metformin 500mg BD, Amlodipine 5mg OD"}),
    ("allergy.known", {"answer": False}),
]:
    db.add(
        InterviewAnswer(id=_uuid(), session_id=s1.id, field=field, value=value, input_mode="touch")
    )

db.add(
    RedFlag(
        id=_uuid(),
        session_id=s1.id,
        symptom="cardiac_chest_pain_dyspnoea",
        severity="critical",
        triggered_at=_now(20),
        triage_notified=False,
    )
)

d1 = Document(
    id=_uuid(),
    patient_id=p1.id,
    file_uri="[DEMO]",
    doc_type="lab_report",
    ocr_status="done",
    document_date=datetime(2025, 7, 22).date(),
    uploaded_at=_now(18),
)
db.add(d1)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d1.id,
        entity_type="investigation_value",
        value={"test": "HbA1c", "value": 8.9, "unit": "%", "reference_range": "4.0-5.6"},
        is_abnormal=True,
    )
)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d1.id,
        entity_type="investigation_value",
        value={
            "test": "Fasting Glucose",
            "value": 142,
            "unit": "mg/dL",
            "reference_range": "70-100",
        },
        is_abnormal=True,
    )
)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d1.id,
        entity_type="medication",
        value={"drug": "Metformin", "dose": "500mg", "frequency": "BD"},
        is_abnormal=None,
    )
)

# ---------------------------------------------------------------------------
# Patient 2: Priya Sharma — fever, AYUSH mode
# ---------------------------------------------------------------------------

p2 = Patient(
    id=_uuid(),
    abha_id="91-9876-5432-1098",
    name="Priya Sharma",
    age=32,
    gender="female",
    phone="8765432109",
    preferred_language="hi",
)
db.add(p2)

db.add(
    ConsentRecord(
        id=_uuid(),
        patient_id=p2.id,
        scope={
            "interview": True,
            "documents": True,
            "abdm_push": False,
            "share_with_physician": True,
            "retention_days": 90,
        },
        language="hi",
        audio_confirmed=True,
        given_at=_now(45),
    )
)

s2 = InterviewSession(
    id=_uuid(),
    patient_id=p2.id,
    chief_complaint="fever",
    mode="ayush",
    status="completed",
    started_at=_now(40),
    completed_at=_now(30),
)
db.add(s2)

for field, value in [
    ("chief_complaint", {"answer": "fever"}),
    ("hpi.onset", {"answer": "days"}),
    ("hpi.character", {"answer": "intermittent, worse in evening"}),
    ("hpi.severity", {"answer": 6}),
    ("hpi.associated_symptoms", {"answer": ["body_ache", "loss_of_appetite"]}),
    ("ayush.prakriti", {"answer": "vata_pitta"}),
    ("ayush.agni", {"answer": "vishama"}),
    ("ayush.koshtha", {"answer": "krura"}),
    ("personal.diet", {"answer": "vegetarian"}),
    ("personal.sleep", {"answer": "disturbed due to fever"}),
]:
    db.add(
        InterviewAnswer(id=_uuid(), session_id=s2.id, field=field, value=value, input_mode="voice")
    )

d2 = Document(
    id=_uuid(),
    patient_id=p2.id,
    file_uri="[DEMO]",
    doc_type="prescription",
    ocr_status="done",
    document_date=datetime(2025, 6, 10).date(),
    uploaded_at=_now(35),
)
db.add(d2)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d2.id,
        entity_type="diagnosis",
        value={"diagnosis": "Jvara (Fever)"},
        is_abnormal=None,
    )
)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d2.id,
        entity_type="medication",
        value={"drug": "Sudarshan Ghanvati", "dose": "2 tabs", "frequency": "TDS"},
        is_abnormal=None,
    )
)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d2.id,
        entity_type="medication",
        value={"drug": "Mahasudarshan Kwath", "dose": "20ml", "frequency": "BD"},
        is_abnormal=None,
    )
)

# ---------------------------------------------------------------------------
# Patient 3: Anil Verma — abdominal pain, normal
# ---------------------------------------------------------------------------

p3 = Patient(
    id=_uuid(),
    name="Anil Verma",
    age=60,
    gender="male",
    phone="7654321098",
    preferred_language="en",
)
db.add(p3)

db.add(
    ConsentRecord(
        id=_uuid(),
        patient_id=p3.id,
        scope={
            "interview": True,
            "documents": True,
            "abdm_push": True,
            "share_with_physician": True,
            "retention_days": 90,
        },
        language="en",
        audio_confirmed=True,
        given_at=_now(60),
    )
)

s3 = InterviewSession(
    id=_uuid(),
    patient_id=p3.id,
    chief_complaint="abdominal_pain",
    mode="general",
    status="completed",
    started_at=_now(55),
    completed_at=_now(45),
)
db.add(s3)

for field, value in [
    ("chief_complaint", {"answer": "abdominal_pain"}),
    ("hpi.site", {"answer": "epigastric"}),
    ("hpi.onset", {"answer": "weeks"}),
    ("hpi.character", {"answer": "burning"}),
    ("hpi.exacerbating_relieving", {"answer": "worse after meals, relieved by antacids"}),
    ("hpi.severity", {"answer": 4}),
    ("past_medical.conditions", {"answer": []}),
    ("drug_history.current_meds", {"answer": "Pantoprazole 40mg OD"}),
    ("allergy.known", {"answer": False}),
    ("family.history", {"answer": "no significant history"}),
]:
    db.add(
        InterviewAnswer(id=_uuid(), session_id=s3.id, field=field, value=value, input_mode="touch")
    )

d3a = Document(
    id=_uuid(),
    patient_id=p3.id,
    file_uri="[DEMO]",
    doc_type="prescription",
    ocr_status="done",
    document_date=datetime(2025, 5, 1).date(),
    uploaded_at=_now(50),
)
db.add(d3a)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d3a.id,
        entity_type="diagnosis",
        value={"diagnosis": "GERD"},
        is_abnormal=None,
    )
)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d3a.id,
        entity_type="medication",
        value={"drug": "Pantoprazole", "dose": "40mg", "frequency": "OD"},
        is_abnormal=None,
    )
)

d3b = Document(
    id=_uuid(),
    patient_id=p3.id,
    file_uri="[DEMO]",
    doc_type="lab_report",
    ocr_status="done",
    document_date=datetime(2025, 4, 15).date(),
    uploaded_at=_now(50),
)
db.add(d3b)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d3b.id,
        entity_type="investigation_value",
        value={"test": "Hemoglobin", "value": 14.2, "unit": "g/dL", "reference_range": "13.0-17.0"},
        is_abnormal=False,
    )
)
db.add(
    DocumentEntity(
        id=_uuid(),
        document_id=d3b.id,
        entity_type="investigation_value",
        value={
            "test": "Fasting Glucose",
            "value": 92,
            "unit": "mg/dL",
            "reference_range": "70-100",
        },
        is_abnormal=False,
    )
)

# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

db.commit()
db.close()

print("=== DEMO SEED DATA CREATED ===")
print(f"  1. {p1.name} (ABHA {p1.abha_id}) — chest pain, RED FLAGGED, abnormal labs")
print(f"  2. {p2.name} (ABHA {p2.abha_id}) — fever, AYUSH mode")
print(f"  3. {p3.name} (no ABHA) — abdominal pain, all normal")
print()
print("These patients are visible on the physician dashboard (/api/v1/dashboard/queue).")
print("Use the physician login (doctor@medikiosk.in) to generate summaries.")
