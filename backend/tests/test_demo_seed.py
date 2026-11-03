"""Tests for the curated demo dataset (``MEDIKIOSK_BOOTSTRAP=demo``).

These run against the real per-test SQLite session with foreign-key enforcement
turned ON. That matters: production is Postgres, which enforces foreign keys at
statement time, and ``Visit`` has no ORM relationship to ``Summary`` /
``InterviewSession`` for the unit of work to order inserts by. The demo builder
flushes parents before each visit to bridge that gap, and enabling the pragma
here is what makes this suite fail if that flush is ever removed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.bootstrap import seed_admin, seed_doctors, seed_physician
from app.demo_seed import build_demo
from app.models.models import (
    Document,
    InterviewMessage,
    Patient,
    RedFlag,
    Summary,
    Visit,
)


@pytest.fixture()
def demo_db(sql_db):
    """A session with the doctors + logins seeded and the full demo built."""
    sql_db.execute(text("PRAGMA foreign_keys=ON"))
    seed_doctors(sql_db)
    seed_admin(sql_db, "admin@medickiosk.in", "winexe")
    seed_physician(sql_db, "doctor@medikiosk.in", "winexe")
    build_demo(sql_db)
    return sql_db


class TestBuildDemo:
    def test_builds_all_seven_patients(self, demo_db):
        assert demo_db.query(Patient).count() == 7

    def test_visit_and_summary_totals(self, demo_db):
        # Six patients carry summaries and one (Ramesh) carries two, so seven
        # summaries across eight visits.
        assert demo_db.query(Visit).count() == 8
        assert demo_db.query(Summary).count() == 7

    def test_every_patient_has_at_least_one_visit(self, demo_db):
        patients = demo_db.query(Patient).all()
        for p in patients:
            assert demo_db.query(Visit).filter(Visit.patient_id == p.id).count() >= 1

    def test_returning_patient_has_multiple_visits(self, demo_db):
        """Ramesh's two visits are what the history-sync demo hangs on."""
        ramesh = demo_db.query(Patient).filter(Patient.name == "Ramesh Kumar").one()
        assert demo_db.query(Visit).filter(Visit.patient_id == ramesh.id).count() == 2

    def test_one_case_is_left_without_a_summary(self, demo_db):
        """Mohan is the live-generation case: interview + docs, no summary yet."""
        mohan = demo_db.query(Patient).filter(Patient.name == "Mohan Rao").one()
        assert demo_db.query(Summary).filter(Summary.patient_id == mohan.id).count() == 0
        # …but he does have the material for a live generation.
        assert demo_db.query(Document).filter(Document.patient_id == mohan.id).count() >= 1

    def test_red_flags_are_seeded(self, demo_db):
        """Two critical cases so the physician triage queue is populated."""
        flags = demo_db.query(RedFlag).all()
        assert len(flags) == 2
        assert all(f.severity == "critical" for f in flags)

    def test_confirmed_and_draft_summaries_both_present(self, demo_db):
        confirmed = demo_db.query(Summary).filter(Summary.status == "confirmed").count()
        draft = demo_db.query(Summary).filter(Summary.status == "draft").count()
        assert confirmed == 5
        assert draft == 2

    def test_conversational_transcripts_exist(self, demo_db):
        assert demo_db.query(InterviewMessage).count() > 0

    def test_confirmed_summaries_are_attributed_to_a_physician(self, demo_db):
        for summary in demo_db.query(Summary).filter(Summary.status == "confirmed").all():
            assert summary.confirmed_by_id is not None
            assert summary.confirmed_at is not None
