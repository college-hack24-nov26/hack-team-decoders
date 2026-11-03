"""Tests for F2 — returning-patient login, doctors, visits, and history.

These cover the flow spine: a returning patient signs in by phone, picks a
doctor, gets a token, and can read their own past record — and cannot read
anyone else's.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.models import Doctor, Visit


@pytest.fixture()
def doctors(sql_db):
    """Two Ayurveda doctors and one cardiologist to select from."""
    rows = [
        Doctor(
            id=uuid.uuid4(),
            name="Dr. Meera Patel",
            department="Ayurveda",
            specialization="Kayachikitsa",
            queue_count=2,
        ),
        Doctor(
            id=uuid.uuid4(),
            name="Dr. Anita Joshi",
            department="Ayurveda",
            specialization="Panchakarma",
            queue_count=0,
        ),
        Doctor(
            id=uuid.uuid4(),
            name="Dr. Rajesh Reddy",
            department="Cardiology",
            specialization="Interventional",
            queue_count=5,
        ),
    ]
    sql_db.add_all(rows)
    sql_db.commit()
    return {d.name: d.id for d in rows}


class TestReturningLogin:
    def test_known_phone_returns_a_token(self, sql_client, seeded_patient):
        """seeded_patient has phone 9999999999."""
        res = sql_client.post("/api/v1/auth/login/returning", json={"phone": "9999999999"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["found"] is True
        assert body["token"]
        assert body["preferred_language"] == "hi"
        assert isinstance(body["visits"], list)

    def test_unknown_phone_is_found_false_not_an_error(self, sql_client):
        res = sql_client.post("/api/v1/auth/login/returning", json={"phone": "1231231231"})
        assert res.status_code == 200
        assert res.json()["found"] is False
        assert res.json()["token"] is None

    def test_past_visits_appear_newest_first(self, sql_client, sql_db, seeded_patient, doctors):
        from datetime import UTC, datetime, timedelta

        pid = seeded_patient["patient_id"]
        older = Visit(
            id=uuid.uuid4(),
            patient_id=pid,
            department="Ayurveda",
            status="completed",
            token_number=1,
            chief_complaint="acidity",
            created_at=datetime.now(tz=UTC) - timedelta(days=2),
        )
        newer = Visit(
            id=uuid.uuid4(),
            patient_id=pid,
            department="Cardiology",
            status="registered",
            token_number=4,
            chief_complaint="chest pain",
            created_at=datetime.now(tz=UTC),
        )
        sql_db.add_all([older, newer])
        sql_db.commit()

        res = sql_client.post("/api/v1/auth/login/returning", json={"phone": "9999999999"})
        visits = res.json()["visits"]
        assert [v["chief_complaint"] for v in visits[:2]] == ["chest pain", "acidity"]


class TestDoctors:
    def test_lists_all_doctors(self, sql_client, patient_headers, doctors):
        res = sql_client.get("/api/v1/doctors", headers=patient_headers)
        assert res.status_code == 200, res.text
        assert len(res.json()["doctors"]) == 3

    def test_filters_by_department(self, sql_client, patient_headers, doctors):
        res = sql_client.get("/api/v1/doctors?department=Ayurveda", headers=patient_headers)
        names = {d["name"] for d in res.json()["doctors"]}
        assert names == {"Dr. Meera Patel", "Dr. Anita Joshi"}

    def test_shortest_queue_surfaces_first(self, sql_client, patient_headers, doctors):
        res = sql_client.get("/api/v1/doctors?department=Ayurveda", headers=patient_headers)
        first = res.json()["doctors"][0]
        assert first["name"] == "Dr. Anita Joshi"  # queue_count 0 < 2

    def test_requires_a_patient_token(self, sql_client, doctors):
        assert sql_client.get("/api/v1/doctors").status_code == 401


class TestVisits:
    def test_booking_issues_token_one_and_grows_the_queue(
        self, sql_client, sql_db, patient_headers, doctors
    ):
        doc_id = str(doctors["Dr. Anita Joshi"])
        res = sql_client.post(
            "/api/v1/visits",
            json={"doctor_id": doc_id, "department": "Ayurveda", "chief_complaint": "acidity"},
            headers=patient_headers,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["token_number"] == 1
        assert body["doctor_name"] == "Dr. Anita Joshi"
        assert body["status"] == "registered"

        doctor = sql_db.query(Doctor).filter(Doctor.id == doctors["Dr. Anita Joshi"]).one()
        assert doctor.queue_count == 1  # was 0

    def test_token_numbers_increment_within_the_day(self, sql_client, patient_headers, doctors):
        doc_id = str(doctors["Dr. Anita Joshi"])
        first = sql_client.post(
            "/api/v1/visits", json={"doctor_id": doc_id}, headers=patient_headers
        )
        second = sql_client.post(
            "/api/v1/visits", json={"doctor_id": doc_id}, headers=patient_headers
        )
        assert first.json()["token_number"] == 1
        assert second.json()["token_number"] == 2

    def test_department_only_visit_needs_no_doctor(self, sql_client, patient_headers):
        res = sql_client.post(
            "/api/v1/visits", json={"department": "General Medicine"}, headers=patient_headers
        )
        assert res.status_code == 201
        assert res.json()["doctor_id"] is None
        assert res.json()["department"] == "General Medicine"

    def test_unknown_doctor_is_404(self, sql_client, patient_headers):
        res = sql_client.post(
            "/api/v1/visits", json={"doctor_id": str(uuid.uuid4())}, headers=patient_headers
        )
        assert res.status_code == 404

    def test_a_patient_cannot_read_another_patients_visit(
        self, sql_client, sql_db, patient_headers, seeded_patient
    ):
        from app.models.models import Patient

        other = Patient(id=uuid.uuid4(), name="Other", preferred_language="en")
        other_visit = Visit(
            id=uuid.uuid4(), patient_id=other.id, status="registered", token_number=1
        )
        sql_db.add_all([other, other_visit])
        sql_db.commit()

        res = sql_client.get(f"/api/v1/visits/{other_visit.id}", headers=patient_headers)
        assert res.status_code == 404


class TestPatientHistory:
    def test_patient_reads_their_own_history(self, sql_client, patient_headers, seeded_patient):
        pid = seeded_patient["patient_id"]
        res = sql_client.get(f"/api/v1/patients/{pid}/history", headers=patient_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["patient_info"]["name"].startswith("SYNTHETIC")
        # seeded_patient has a red-flagged chest-pain session
        assert any(
            "chest" in rf["name"].lower() or rf["severity"] == "critical"
            for rf in body["red_flags"]
        )

    def test_a_patient_cannot_read_another_patients_history(self, sql_client, patient_headers):
        res = sql_client.get(f"/api/v1/patients/{uuid.uuid4()}/history", headers=patient_headers)
        assert res.status_code == 404
