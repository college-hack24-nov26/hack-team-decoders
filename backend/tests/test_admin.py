"""Tests for the super-admin surface.

The one gate is role: admin-only. A physician/staff token is 403, a patient
token is 401 (wrong token type), an admin token gets through. Plus the two
footguns worth a test each: no self-lockout, and no duplicate email.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.models import Doctor, Physician
from app.services.jwt import create_physician_token
from app.services.password import hash_password


@pytest.fixture()
def admin(sql_db) -> Physician:
    a = Physician(
        id=uuid.uuid4(),
        email="admin@medikiosk.in",
        hashed_password=hash_password("admin-pw"),
        full_name="Super Admin",
        role="admin",
        is_active=True,
    )
    sql_db.add(a)
    sql_db.commit()
    return a


@pytest.fixture()
def admin_headers(admin: Physician) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_physician_token(admin.id)}"}


class TestAdminAccessControl:
    def test_patient_token_is_401(self, sql_client, patient_headers):
        assert sql_client.get("/api/v1/admin/overview", headers=patient_headers).status_code == 401

    def test_ordinary_physician_is_403(self, sql_client, physician_headers, seeded_patient):
        """The physician fixture has role 'physician' — the admin surface is closed to it."""
        res = sql_client.get("/api/v1/admin/overview", headers=physician_headers)
        assert res.status_code == 403

    def test_anonymous_is_401(self, sql_client):
        assert sql_client.get("/api/v1/admin/overview").status_code == 401

    def test_admin_gets_through(self, sql_client, admin_headers, seeded_patient):
        res = sql_client.get("/api/v1/admin/overview", headers=admin_headers)
        assert res.status_code == 200, res.text


class TestOverview:
    def test_counts_reflect_seeded_data(self, sql_client, admin_headers, seeded_patient):
        body = sql_client.get("/api/v1/admin/overview", headers=admin_headers).json()
        assert body["patients"] >= 1
        assert body["red_flags"] >= 1  # seeded_patient has a critical flag
        assert "physicians" in body and body["physicians"] >= 1


class TestPatientListing:
    def test_lists_patients_with_visit_counts(
        self, sql_client, sql_db, admin_headers, seeded_patient
    ):
        from app.models.models import Visit

        sql_db.add(
            Visit(
                id=uuid.uuid4(),
                patient_id=seeded_patient["patient_id"],
                status="registered",
                token_number=1,
            )
        )
        sql_db.commit()

        rows = sql_client.get("/api/v1/admin/patients", headers=admin_headers).json()
        me = next(r for r in rows if r["id"] == str(seeded_patient["patient_id"]))
        assert me["visit_count"] == 1


class TestPhysicianManagement:
    def test_create_and_list_a_physician(self, sql_client, admin_headers):
        res = sql_client.post(
            "/api/v1/admin/physicians",
            json={
                "email": "newdoc@medikiosk.in",
                "password": "secret123",
                "full_name": "Dr New",
                "role": "physician",
            },
            headers=admin_headers,
        )
        assert res.status_code == 201, res.text
        assert res.json()["email"] == "newdoc@medikiosk.in"

        emails = {
            p["email"]
            for p in sql_client.get("/api/v1/admin/physicians", headers=admin_headers).json()
        }
        assert "newdoc@medikiosk.in" in emails

    def test_the_created_login_actually_works(self, sql_client, admin_headers):
        sql_client.post(
            "/api/v1/admin/physicians",
            json={
                "email": "works@medikiosk.in",
                "password": "secret123",
                "full_name": "Dr Works",
                "role": "physician",
            },
            headers=admin_headers,
        )
        login = sql_client.post(
            "/api/v1/auth/physician/login",
            json={"email": "works@medikiosk.in", "password": "secret123"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["token"]

    def test_duplicate_email_is_409(self, sql_client, admin_headers):
        body = {
            "email": "dup@medikiosk.in",
            "password": "secret123",
            "full_name": "Dr Dup",
            "role": "physician",
        }
        assert (
            sql_client.post(
                "/api/v1/admin/physicians", json=body, headers=admin_headers
            ).status_code
            == 201
        )
        assert (
            sql_client.post(
                "/api/v1/admin/physicians", json=body, headers=admin_headers
            ).status_code
            == 409
        )

    def test_admin_cannot_deactivate_their_own_account(self, sql_client, admin, admin_headers):
        """Self-lockout guard: the last admin must not be able to switch itself off."""
        res = sql_client.patch(
            f"/api/v1/admin/physicians/{admin.id}",
            json={"is_active": False},
            headers=admin_headers,
        )
        assert res.status_code == 400

    def test_admin_can_deactivate_another_login(self, sql_client, admin_headers, physician):
        res = sql_client.patch(
            f"/api/v1/admin/physicians/{physician.id}",
            json={"is_active": False},
            headers=admin_headers,
        )
        assert res.status_code == 200
        assert res.json()["is_active"] is False


class TestDoctorManagement:
    def test_create_a_doctor(self, sql_client, sql_db, admin_headers):
        res = sql_client.post(
            "/api/v1/admin/doctors",
            json={"name": "Dr. Test", "department": "ENT", "specialization": "Audiology"},
            headers=admin_headers,
        )
        assert res.status_code == 201, res.text
        assert res.json()["department"] == "ENT"
        assert sql_db.query(Doctor).filter(Doctor.name == "Dr. Test").count() == 1

    def test_update_doctor_availability(self, sql_client, sql_db, admin_headers):
        doc = Doctor(id=uuid.uuid4(), name="Dr. Flip", department="ENT", queue_count=3)
        sql_db.add(doc)
        sql_db.commit()

        res = sql_client.patch(
            f"/api/v1/admin/doctors/{doc.id}",
            json={"available": False, "queue_count": 0},
            headers=admin_headers,
        )
        assert res.status_code == 200
        assert res.json()["available"] is False
        assert res.json()["queue_count"] == 0
