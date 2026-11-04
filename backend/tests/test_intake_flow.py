"""Tests for the kiosk intake flow joining up end to end.

Covers the pieces that connect a patient's intake to the doctor: the patient's
own review of their answers, the finished interview being tied to the visit
(and so to the doctor the patient picked), the dashboard showing doctors, and
the offline demo OCR engine.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.models.models import Doctor, Visit
from app.services.entity_extraction import extract_entities
from app.services.jwt import create_patient_token
from app.services.ocr import DemoOcrEngine, get_ocr_engine


@pytest.fixture()
def doctor(sql_db):
    row = Doctor(
        id=uuid.uuid4(),
        name="Dr. Rajesh Reddy",
        department="Cardiology",
        specialization="Interventional Cardiology",
        queue_count=0,
    )
    sql_db.add(row)
    sql_db.commit()
    return row


@pytest.fixture()
def visit(sql_db, seeded_patient, doctor):
    row = Visit(
        id=uuid.uuid4(),
        patient_id=seeded_patient["patient_id"],
        doctor_id=doctor.id,
        department="Cardiology",
        status="registered",
        token_number=7,
    )
    sql_db.add(row)
    sql_db.commit()
    return row


class TestPatientReview:
    def test_answers_come_back_as_labels_in_interview_order(
        self, sql_client, seeded_patient, patient_headers
    ):
        sid = seeded_patient["session_id"]
        res = sql_client.get(
            f"/api/v1/interview/sessions/{sid}/review?language=en", headers=patient_headers
        )
        assert res.status_code == 200, res.text
        body = res.json()
        by_field = {item["field_id"]: item for item in body["items"]}

        assert body["items"][0]["field_id"] == "chief_complaint"
        assert by_field["chief_complaint"]["answer"] == "Chest pain"
        assert by_field["hpi.site"]["answer"] == "Centre of chest"
        assert by_field["hpi.severity"]["answer"] == "9 / 10"
        assert by_field["past_medical.conditions"]["answer"] == "Diabetes, High blood pressure"
        assert by_field["allergy.known"]["skipped"] is True
        assert by_field["hpi.site"]["question"].startswith("Where exactly")

    def test_hindi_patient_gets_hindi_labels(self, sql_client, seeded_patient, patient_headers):
        sid = seeded_patient["session_id"]
        res = sql_client.get(
            f"/api/v1/interview/sessions/{sid}/review?language=hi", headers=patient_headers
        )
        assert res.status_code == 200, res.text
        cc = res.json()["items"][0]
        assert cc["answer"] != "Chest pain"
        assert res.json()["language"] == "hi"

    def test_another_patient_cannot_read_it(self, sql_client, sql_db, seeded_patient):
        from app.models.models import ConsentRecord, Patient

        other = uuid.uuid4()
        sql_db.add_all(
            [
                Patient(id=other, name="Other", age=30, gender="male", phone="8888888888"),
                ConsentRecord(
                    id=uuid.uuid4(),
                    patient_id=other,
                    scope={"interview": True},
                    language="en",
                    audio_confirmed=True,
                ),
            ]
        )
        sql_db.commit()
        headers = {"Authorization": f"Bearer {create_patient_token(other)}"}
        sid = seeded_patient["session_id"]
        res = sql_client.get(f"/api/v1/interview/sessions/{sid}/review", headers=headers)
        assert res.status_code == 404


class TestVisitLinking:
    def test_completing_the_interview_links_the_booked_visit(
        self, sql_client, sql_db, seeded_patient, patient_headers, visit
    ):
        sid = seeded_patient["session_id"]
        res = sql_client.post(f"/api/v1/interview/sessions/{sid}/complete", headers=patient_headers)
        assert res.status_code == 200, res.text

        sql_db.refresh(visit)
        assert visit.interview_session_id == sid
        assert visit.status == "waiting"
        assert visit.chief_complaint == "chest_pain"

    def test_queue_shows_the_chosen_doctor_and_token(
        self, sql_client, seeded_patient, patient_headers, physician_headers, visit
    ):
        sid = seeded_patient["session_id"]
        sql_client.post(f"/api/v1/interview/sessions/{sid}/complete", headers=patient_headers)

        res = sql_client.get("/api/v1/dashboard/queue", headers=physician_headers)
        assert res.status_code == 200, res.text
        row = res.json()["patients"][0]
        assert row["doctor_name"] == "Dr. Rajesh Reddy"
        assert row["department"] == "Cardiology"
        assert row["token_number"] == 7

    def test_dashboard_doctors_count_their_waiting_patients(
        self, sql_client, seeded_patient, patient_headers, physician_headers, visit, doctor
    ):
        sid = seeded_patient["session_id"]
        sql_client.post(f"/api/v1/interview/sessions/{sid}/complete", headers=patient_headers)

        res = sql_client.get("/api/v1/dashboard/doctors", headers=physician_headers)
        assert res.status_code == 200, res.text
        rows = {d["id"]: d for d in res.json()}
        assert rows[str(doctor.id)]["waiting"] == 1

    def test_dashboard_doctors_requires_a_physician(self, sql_client, patient_headers):
        res = sql_client.get("/api/v1/dashboard/doctors", headers=patient_headers)
        assert res.status_code in (401, 403)


class TestDemoOcr:
    def test_selected_by_setting(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "ocr_engine", "demo")
        assert isinstance(get_ocr_engine(), DemoOcrEngine)
        assert isinstance(get_ocr_engine(handwriting=True), DemoOcrEngine)

    def test_sample_text_is_labelled_and_extractable(self, tmp_path):
        text = DemoOcrEngine().extract_text(tmp_path / "anything.jpg")
        assert text.startswith("[DEMO OCR")
        result = extract_entities(text, gender="male")
        tests = {
            e.value["test"]: e.is_abnormal
            for e in result.entities
            if e.entity_type == "investigation_value"
        }
        assert tests["HbA1c"] is True
        assert any(e.entity_type == "medication" for e in result.entities)

    def test_upload_on_sqlite_reads_and_extracts(
        self, sql_client, patient_headers, monkeypatch, tmp_path
    ):
        """An upload whose OCR returns text must not 500 on SQLite.

        The vector-embedding insert needs pgvector; on SQLite it used to fail and
        take the upload down the moment any OCR engine produced text.
        """
        settings = get_settings()
        monkeypatch.setattr(settings, "ocr_engine", "demo")
        monkeypatch.setattr(settings, "file_storage_backend", "local")
        monkeypatch.setattr(settings, "file_storage_root", str(tmp_path))

        res = sql_client.post(
            "/api/v1/documents",
            headers=patient_headers,
            files={"file": ("lab.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            data={"doc_type": "unknown"},
        )
        assert res.status_code == 201, res.text
        assert res.json()["ocr_status"] == "done"

        entities = sql_client.get(
            f"/api/v1/documents/{res.json()['id']}/entities", headers=patient_headers
        )
        assert entities.status_code == 200, entities.text
        assert any(e["entity_type"] == "investigation_value" for e in entities.json())
