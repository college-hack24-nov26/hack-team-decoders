"""Tests for the no-shell data bootstrap.

The functions take a session so they can run against the in-memory test DB; the
`run*` wrappers (which use the global SessionLocal) are not exercised here.
"""

from __future__ import annotations

import uuid

from app.bootstrap import reset_patient_data, seed_admin, seed_doctors
from app.models.models import Doctor, Physician, Visit
from app.services.password import verify_password


class TestSeedAdmin:
    def test_creates_a_single_admin(self, sql_db):
        seed_admin(sql_db, "admin@medickiosk.in", "winexe")

        admins = sql_db.query(Physician).filter(Physician.role == "admin").all()
        assert len(admins) == 1
        assert admins[0].email == "admin@medickiosk.in"
        assert verify_password("winexe", admins[0].hashed_password)

    def test_is_idempotent_and_resets_the_password(self, sql_db):
        seed_admin(sql_db, "admin@medickiosk.in", "winexe")
        seed_admin(sql_db, "admin@medickiosk.in", "newpass")

        admins = sql_db.query(Physician).filter(Physician.email == "admin@medickiosk.in").all()
        assert len(admins) == 1  # not duplicated
        assert verify_password("newpass", admins[0].hashed_password)

    def test_email_is_lowercased(self, sql_db):
        seed_admin(sql_db, "Admin@MediCkiosk.IN", "winexe")
        assert sql_db.query(Physician).filter(Physician.email == "admin@medickiosk.in").count() == 1


class TestSeedDoctors:
    def test_creates_all(self, sql_db):
        assert seed_doctors(sql_db) == 7
        assert sql_db.query(Doctor).count() == 7

    def test_is_idempotent(self, sql_db):
        seed_doctors(sql_db)
        assert seed_doctors(sql_db) == 0  # nothing new the second time
        assert sql_db.query(Doctor).count() == 7

    def test_covers_every_demo_department(self, sql_db):
        seed_doctors(sql_db)
        departments = {d.department for d in sql_db.query(Doctor).all()}
        assert departments == {
            "General Medicine",
            "Ayurveda",
            "Cardiology",
            "Pediatrics",
            "Orthopedics",
            "ENT",
        }

    def test_includes_two_ayurveda_doctors(self, sql_db):
        seed_doctors(sql_db)
        assert sql_db.query(Doctor).filter(Doctor.department == "Ayurveda").count() == 2


class TestResetPatientData:
    def test_wipes_patients_but_keeps_doctors_and_logins(self, sql_db, seeded_patient):
        # Something in every category first.
        seed_doctors(sql_db)
        seed_admin(sql_db, "admin@medickiosk.in", "winexe")
        sql_db.add(
            Visit(
                id=uuid.uuid4(),
                patient_id=seeded_patient["patient_id"],
                status="registered",
                token_number=1,
            )
        )
        sql_db.commit()

        from app.models.models import InterviewSession, Patient, RedFlag, Summary

        assert sql_db.query(Patient).count() >= 1

        reset_patient_data(sql_db)

        # Patient/clinical data gone…
        assert sql_db.query(Patient).count() == 0
        assert sql_db.query(Visit).count() == 0
        assert sql_db.query(InterviewSession).count() == 0
        assert sql_db.query(RedFlag).count() == 0
        assert sql_db.query(Summary).count() == 0
        # …but configuration kept.
        assert sql_db.query(Doctor).count() == 7
        assert sql_db.query(Physician).filter(Physician.role == "admin").count() == 1

    def test_safe_on_an_empty_database(self, sql_db):
        reset_patient_data(sql_db)  # must not raise
        from app.models.models import Patient

        assert sql_db.query(Patient).count() == 0
