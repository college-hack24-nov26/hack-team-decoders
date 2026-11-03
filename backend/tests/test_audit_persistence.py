"""Audit entries must survive the end of the request — Module D deliverable 3.

`log_action()` flushes but does not commit, by design: the audit row belongs in
the same transaction as the action it describes. The consequence is that an entry
flushed *after* the final `db.commit()` is silently discarded, because production's
`get_db()` ends the request with `db.close()`, which rolls back the open
transaction.

That is not a hypothetical. Before this wave, nine call sites logged after their
commit — session start, session complete, answer submitted, summary
generated/edited/confirmed/pushed, dashboard patient view, and the document
timeline read. Every one of those audit trails was being thrown away, while the
code read as though it were recording them.

These tests reproduce the production lifecycle by calling `rollback()` after the
request: anything the request left uncommitted disappears, exactly as it would on
`close()`. An audit row that survives was genuinely committed.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.models import AuditLog, ConsentRecord, InterviewSession


def _audit_actions(sql_db) -> list[str]:
    """Audit actions that survived a rollback, i.e. were actually committed."""
    sql_db.rollback()
    return [row.action for row in sql_db.query(AuditLog).all()]


def _grant_scope(sql_db, patient_id: uuid.UUID, **scopes: bool) -> None:
    consent = sql_db.query(ConsentRecord).filter(ConsentRecord.patient_id == patient_id).first()
    consent.scope = {**consent.scope, **scopes}
    sql_db.commit()


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------


class TestInterviewAuditPersists:
    def test_session_start_is_committed(self, sql_client, sql_db, patient_headers):
        res = sql_client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=patient_headers,
        )
        assert res.status_code == 201, res.text
        assert "interview.session_started" in _audit_actions(sql_db)

    def test_answer_submission_is_committed(self, sql_client, sql_db, patient_headers):
        session_id = sql_client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=patient_headers,
        ).json()["session_id"]

        res = sql_client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "fever", "input_mode": "touch"},
            headers=patient_headers,
        )
        assert res.status_code == 200, res.text
        assert "interview.answer_submitted" in _audit_actions(sql_db)

    def test_session_completion_is_committed(self, sql_client, sql_db, patient_headers):
        session_id = sql_client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=patient_headers,
        ).json()["session_id"]

        res = sql_client.post(
            f"/api/v1/interview/sessions/{session_id}/complete", headers=patient_headers
        )
        assert res.status_code == 200, res.text
        assert "interview.session_completed" in _audit_actions(sql_db)


# ---------------------------------------------------------------------------
# Documents — reads of patient data are audited too
# ---------------------------------------------------------------------------


class TestDocumentReadAuditPersists:
    def test_timeline_read_is_committed(self, sql_client, sql_db, seeded_patient, patient_headers):
        pid = seeded_patient["patient_id"]
        res = sql_client.get(f"/api/v1/patients/{pid}/documents/timeline", headers=patient_headers)
        assert res.status_code == 200, res.text
        assert "document.timeline_read" in _audit_actions(sql_db)

    def test_document_read_is_committed(self, sql_client, sql_db, seeded_patient, patient_headers):
        did = seeded_patient["document_id"]
        res = sql_client.get(f"/api/v1/documents/{did}", headers=patient_headers)
        assert res.status_code == 200, res.text
        assert "document.read" in _audit_actions(sql_db)


# ---------------------------------------------------------------------------
# Dashboard — a physician reading a record is the audit trail's core case
# ---------------------------------------------------------------------------


class TestDashboardAuditPersists:
    def test_queue_view_is_committed(self, sql_client, sql_db, seeded_patient, physician_headers):
        res = sql_client.get("/api/v1/dashboard/queue", headers=physician_headers)
        assert res.status_code == 200, res.text
        assert "dashboard.queue_viewed" in _audit_actions(sql_db)

    def test_patient_view_is_committed(self, sql_client, sql_db, seeded_patient, physician_headers):
        pid = seeded_patient["patient_id"]
        res = sql_client.get(f"/api/v1/dashboard/patients/{pid}/summary", headers=physician_headers)
        assert res.status_code == 200, res.text
        assert "dashboard.patient_viewed" in _audit_actions(sql_db)

    def test_patient_view_records_the_physician_not_just_the_patient(
        self, sql_client, sql_db, seeded_patient, physician, physician_headers
    ):
        """DPDP wants to know *who* read the record, not only whose it was."""
        pid = seeded_patient["patient_id"]
        sql_client.get(f"/api/v1/dashboard/patients/{pid}/summary", headers=physician_headers)

        sql_db.rollback()
        entry = sql_db.query(AuditLog).filter(AuditLog.action == "dashboard.patient_viewed").first()
        assert entry is not None
        assert entry.actor_id == physician.id
        assert entry.detail["patient_id"] == str(pid)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


class TestSummaryAuditPersists:
    @pytest.fixture()
    def summary_id(self, sql_client, sql_db, seeded_patient, physician_headers) -> str:
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def test_generation_is_committed(self, sql_client, sql_db, summary_id):
        assert "summary.generated" in _audit_actions(sql_db)

    def test_edit_is_committed(self, sql_client, sql_db, summary_id, physician_headers):
        res = sql_client.patch(
            f"/api/v1/summaries/{summary_id}",
            json={"structured_content": {"chief_complaint": "edited"}},
            headers=physician_headers,
        )
        assert res.status_code == 200, res.text
        assert "summary.edited" in _audit_actions(sql_db)

    def test_confirmation_is_committed(self, sql_client, sql_db, summary_id, physician_headers):
        res = sql_client.post(
            f"/api/v1/summaries/{summary_id}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )
        assert res.status_code == 200, res.text
        assert "summary.accepted" in _audit_actions(sql_db)

    def test_abdm_push_is_committed(
        self, sql_client, sql_db, seeded_patient, summary_id, physician_headers
    ):
        sql_client.post(
            f"/api/v1/summaries/{summary_id}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )
        _grant_scope(sql_db, seeded_patient["patient_id"], abdm_push=True)

        res = sql_client.post(
            f"/api/v1/summaries/{summary_id}/push-abdm", headers=physician_headers
        )
        assert res.status_code == 200, res.text
        # No endpoint configured, so the honest outcome is a recorded failure to
        # transmit rather than a silent success.
        assert "summary.push_abdm_failed" in _audit_actions(sql_db)


# ---------------------------------------------------------------------------
# End-to-end trail — the Module D acceptance criterion
# ---------------------------------------------------------------------------


def test_full_journey_leaves_a_complete_committed_trail(
    sql_client, sql_db, seeded_patient, patient_headers, physician_headers
):
    """Identify → Converse → Scan → Summarize → Consult all appear in audit_logs.

    The seeded patient already has consent and documents, so this drives the
    remaining stages and asserts every one of them survived commit.
    """
    pid = seeded_patient["patient_id"]

    session_id = sql_client.post(
        "/api/v1/interview/sessions", json={"mode": "general"}, headers=patient_headers
    ).json()["session_id"]
    sql_client.post(
        f"/api/v1/interview/sessions/{session_id}/answer",
        json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
        headers=patient_headers,
    )
    sql_client.post(f"/api/v1/interview/sessions/{session_id}/complete", headers=patient_headers)
    sql_client.get(f"/api/v1/patients/{pid}/documents/timeline", headers=patient_headers)

    # Summarise the seeded, already-completed session.
    summary = sql_client.post(
        "/api/v1/summaries/generate",
        json={"session_id": str(seeded_patient["session_id"])},
        headers=physician_headers,
    )
    assert summary.status_code == 201, summary.text

    sql_client.get("/api/v1/dashboard/queue", headers=physician_headers)
    sql_client.get(f"/api/v1/dashboard/patients/{pid}/summary", headers=physician_headers)

    actions = _audit_actions(sql_db)
    for expected in (
        "interview.session_started",
        "interview.answer_submitted",
        "interview.session_completed",
        "document.timeline_read",
        "summary.generated",
        "dashboard.queue_viewed",
        "dashboard.patient_viewed",
    ):
        assert expected in actions, f"missing from audit trail: {expected}"


def test_a_started_session_is_actually_persisted(sql_client, sql_db, patient_headers):
    """Guard against the reordering fix breaking the write it wraps.

    Moving the audit call before the commit is only safe if the row it describes
    is still committed, so assert the session itself survives too.
    """
    session_id = sql_client.post(
        "/api/v1/interview/sessions", json={"mode": "general"}, headers=patient_headers
    ).json()["session_id"]

    sql_db.rollback()
    assert (
        sql_db.query(InterviewSession).filter(InterviewSession.id == uuid.UUID(session_id)).first()
        is not None
    )
