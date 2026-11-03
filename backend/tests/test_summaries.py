"""Tests for Module C — summary generator and physician dashboard.

Wave 4 shipped with no tests. Each class below corresponds to a defect the audit
found, so the suite is mostly regression cover rather than happy-path decoration.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.models import ConsentRecord
from app.services.summary.llm import (
    SummaryValidationError,
    _parse_and_validate,
    summarize_deterministic,
)
from app.services.summary.retrieval import retrieve_session_context

# ---------------------------------------------------------------------------
# Authentication — the dashboard shipped fully open
# ---------------------------------------------------------------------------


class TestDashboardRequiresPhysician:
    """The queue is a list of patients, names and diagnoses. It was public."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/dashboard/queue",
            "/api/v1/dashboard/patients/{pid}/summary",
            "/api/v1/dashboard/patients/{pid}/report",
        ],
    )
    def test_anonymous_is_refused(self, sql_client, seeded_patient, path):
        url = path.format(pid=seeded_patient["patient_id"])
        assert sql_client.get(url).status_code == 401

    def test_patient_token_is_not_enough(self, sql_client, patient_headers):
        """A patient must not be able to read the clinician's queue."""
        res = sql_client.get("/api/v1/dashboard/queue", headers=patient_headers)
        assert res.status_code == 401

    def test_physician_can_read_the_queue(self, sql_client, seeded_patient, physician_headers):
        res = sql_client.get("/api/v1/dashboard/queue", headers=physician_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["patients"][0]["has_red_flags"] is True

    def test_deactivated_physician_is_refused(
        self, sql_client, sql_db, physician, physician_headers
    ):
        physician.is_active = False
        sql_db.commit()
        res = sql_client.get("/api/v1/dashboard/queue", headers=physician_headers)
        assert res.status_code == 403


class TestSummaryMutationsRequirePhysician:
    """Confirming a summary promotes an AI draft into a record. It was open."""

    @pytest.fixture()
    def summary_id(self, sql_client, seeded_patient, physician_headers) -> str:
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def test_anonymous_cannot_edit(self, sql_client, summary_id):
        res = sql_client.patch(f"/api/v1/summaries/{summary_id}", json={"structured_content": {}})
        assert res.status_code == 401

    def test_anonymous_cannot_confirm(self, sql_client, summary_id):
        res = sql_client.post(
            f"/api/v1/summaries/{summary_id}/confirm", json={"decision": "accept"}
        )
        assert res.status_code == 401

    def test_anonymous_cannot_push(self, sql_client, summary_id):
        assert sql_client.post(f"/api/v1/summaries/{summary_id}/push-abdm").status_code == 401


class TestPhysicianLogin:
    def test_correct_credentials_issue_a_token(self, sql_client, physician):
        from tests.conftest import PHYSICIAN_PASSWORD

        res = sql_client.post(
            "/api/v1/auth/physician/login",
            json={"email": physician.email, "password": PHYSICIAN_PASSWORD},
        )
        assert res.status_code == 200
        assert res.json()["role"] == "physician"
        assert res.json()["token"]

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, sql_client, physician):
        """Differing responses would let anyone enumerate clinician accounts."""
        wrong = sql_client.post(
            "/api/v1/auth/physician/login",
            json={"email": physician.email, "password": "nope"},
        )
        unknown = sql_client.post(
            "/api/v1/auth/physician/login",
            json={"email": "ghost@test.in", "password": "nope"},
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"]

    def test_email_is_matched_case_insensitively(self, sql_client, physician):
        from tests.conftest import PHYSICIAN_PASSWORD

        res = sql_client.post(
            "/api/v1/auth/physician/login",
            json={"email": physician.email.upper(), "password": PHYSICIAN_PASSWORD},
        )
        assert res.status_code == 200


class TestTokenTypeSeparation:
    """One signing key, two subject types. The type claim must be enforced."""

    def test_a_patient_token_is_not_a_physician_token(self, seeded_patient):
        from app.services.jwt import create_patient_token, decode_physician_token

        token = create_patient_token(seeded_patient["patient_id"])
        assert decode_physician_token(token) is None

    def test_a_physician_token_is_not_a_patient_token(self, physician):
        from app.services.jwt import create_physician_token, decode_patient_token

        token = create_physician_token(physician.id)
        assert decode_patient_token(token) is None


# ---------------------------------------------------------------------------
# The generate flow the UI actually performs
# ---------------------------------------------------------------------------


class TestGenerateFlow:
    def test_dashboard_exposes_session_id_before_a_summary_exists(
        self, sql_client, seeded_patient, physician_headers
    ):
        """The regression behind the dead Generate button.

        The id was only nested inside `summary`, which is null in exactly the
        state where the client needs it, so the UI posted an empty string.
        """
        res = sql_client.get(
            f"/api/v1/dashboard/patients/{seeded_patient['patient_id']}/summary",
            headers=physician_headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["summary"] is None
        assert body["session_id"] == str(seeded_patient["session_id"])
        assert body["session_status"] == "red_flagged"

    def test_generate_produces_a_draft_from_interview_and_documents(
        self, sql_client, seeded_patient, physician_headers
    ):
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 201
        body = res.json()

        assert body["status"] == "draft"
        assert body["physician_edited"] is False

        content = body["structured_content"]
        assert content["chief_complaint"] == "chest_pain"
        assert content["hpi"]["site"] == "central"
        # Pulled from the patient's documents, not the interview.
        assert any(m["drug"] == "Metformin" for m in content["drug_history"])
        assert any(i["test"] == "HbA1c" for i in content["prior_investigations"])

    def test_generate_is_idempotent_per_session(
        self, sql_client, seeded_patient, physician_headers
    ):
        """A second click must not create a competing summary for one session."""
        body = {"session_id": str(seeded_patient["session_id"])}
        first = sql_client.post("/api/v1/summaries/generate", json=body, headers=physician_headers)
        second = sql_client.post("/api/v1/summaries/generate", json=body, headers=physician_headers)
        assert first.json()["id"] == second.json()["id"]

    def test_malformed_session_id_is_a_422_not_a_500(self, sql_client, physician_headers):
        """The dead button sent an empty string, which reached uuid.UUID()."""
        res = sql_client.post(
            "/api/v1/summaries/generate", json={"session_id": ""}, headers=physician_headers
        )
        assert res.status_code == 422

    def test_an_incomplete_interview_cannot_be_summarised(
        self, sql_client, sql_db, seeded_patient, physician_headers
    ):
        from app.models.models import InterviewSession

        session = (
            sql_db.query(InterviewSession)
            .filter(InterviewSession.id == seeded_patient["session_id"])
            .first()
        )
        session.status = "in_progress"
        sql_db.commit()

        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 400


class TestEditAndConfirm:
    @pytest.fixture()
    def summary(self, sql_client, seeded_patient, physician_headers) -> dict:
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        return res.json()

    def test_editing_sets_the_physician_edited_flag(self, sql_client, summary, physician_headers):
        """The acceptance criterion: the flag must reflect whether it was touched."""
        assert summary["physician_edited"] is False

        content = {**summary["structured_content"], "allergies": "Penicillin"}
        res = sql_client.patch(
            f"/api/v1/summaries/{summary['id']}",
            json={"structured_content": content},
            headers=physician_headers,
        )
        assert res.status_code == 200
        assert res.json()["physician_edited"] is True
        assert res.json()["structured_content"]["allergies"] == "Penicillin"

    def test_accepting_records_who_and_when(self, sql_client, summary, physician_headers):
        res = sql_client.post(
            f"/api/v1/summaries/{summary['id']}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "confirmed"
        assert res.json()["confirmed_at"] is not None

    def test_rejecting_without_a_reason_is_refused(self, sql_client, summary, physician_headers):
        """The reason is the primary model-improvement signal (PRD E1.5)."""
        res = sql_client.post(
            f"/api/v1/summaries/{summary['id']}/confirm",
            json={"decision": "reject"},
            headers=physician_headers,
        )
        assert res.status_code == 400

    def test_rejecting_with_a_reason_is_accepted(self, sql_client, summary, physician_headers):
        res = sql_client.post(
            f"/api/v1/summaries/{summary['id']}/confirm",
            json={"decision": "reject", "rejection_reason": "HPI does not match what I was told"},
            headers=physician_headers,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"

    def test_a_confirmed_summary_cannot_be_edited(self, sql_client, summary, physician_headers):
        sql_client.post(
            f"/api/v1/summaries/{summary['id']}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )
        res = sql_client.patch(
            f"/api/v1/summaries/{summary['id']}",
            json={"structured_content": {}},
            headers=physician_headers,
        )
        assert res.status_code == 400

    def test_only_a_confirmed_summary_can_be_pushed(
        self, sql_client, sql_db, summary, physician_headers, seeded_patient
    ):
        draft_push = sql_client.post(
            f"/api/v1/summaries/{summary['id']}/push-abdm", headers=physician_headers
        )
        assert draft_push.status_code == 400

        sql_client.post(
            f"/api/v1/summaries/{summary['id']}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )

        # The seeded patient declined ABDM push, and Module D now enforces that
        # scope, so grant it before asserting the confirmed-summary path.
        consent = (
            sql_db.query(ConsentRecord)
            .filter(ConsentRecord.patient_id == seeded_patient["patient_id"])
            .first()
        )
        consent.scope = {**consent.scope, "abdm_push": True}
        sql_db.commit()

        confirmed_push = sql_client.post(
            f"/api/v1/summaries/{summary['id']}/push-abdm", headers=physician_headers
        )
        assert confirmed_push.status_code == 200

        body = confirmed_push.json()
        # A real FHIR R4 document Bundle is produced...
        assert body["bundle"]["resourceType"] == "Bundle"
        assert body["bundle"]["type"] == "document"
        # ...but with no endpoint configured it is honestly reported as not sent,
        # so nobody mistakes Bundle generation for a real ABDM push.
        assert body["pushed"] is False
        assert body["transport"] == "none"


# ---------------------------------------------------------------------------
# Retrieval and the deterministic summariser
# ---------------------------------------------------------------------------


class TestAbnormalFlagSurvivesRetrieval:
    def test_is_abnormal_is_read_from_the_column_not_the_value_json(self, sql_db, seeded_patient):
        """A clinical-safety regression.

        Module B records the abnormal verdict as a column while `value` holds the
        extracted fields. Reading `value["is_abnormal"]` therefore reported every
        result as normal, and an HbA1c of 8.9% reached the physician unflagged.
        """
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        grouped = context.entities_grouped()

        hba1c = next(item for item in grouped["investigation_value"] if item["test"] == "HbA1c")
        assert hba1c["is_abnormal"] is True

    def test_the_summary_carries_the_abnormal_flag_through(self, sql_db, seeded_patient):
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        summary = summarize_deterministic(context)

        hba1c = next(i for i in summary.prior_investigations if i.test == "HbA1c")
        assert hba1c.is_abnormal is True


class TestRetrieval:
    def test_skipped_answers_are_omitted(self, sql_db, seeded_patient):
        """A skipped question is an absence, not the answer "skipped"."""
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        assert "allergy.known" not in context.answers_by_field()

    def test_documents_for_the_patient_are_included(self, sql_db, seeded_patient):
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        assert len(context.documents) == 1
        assert len(context.entities) == 2

    def test_unknown_session_raises(self, sql_db):
        with pytest.raises(ValueError):
            retrieve_session_context(str(uuid.uuid4()), sql_db)

    def test_prompt_context_mentions_the_red_flag(self, sql_db, seeded_patient):
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        rendered = context.format_for_prompt()
        assert "RED FLAGS" in rendered
        assert "cardiac_chest_pain_dyspnoea" in rendered
        assert "ABNORMAL" in rendered


class TestDeterministicSummary:
    def test_it_never_invents_a_clinical_impression(self, sql_db, seeded_patient):
        """No model ran, so there is nothing to base an impression on.

        Emitting one anyway would attribute a judgement to a string-formatting
        routine.
        """
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        summary = summarize_deterministic(context)
        assert summary.clinical_impression == ""

    def test_it_reports_red_flags(self, sql_db, seeded_patient):
        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        summary = summarize_deterministic(context)
        assert "cardiac_chest_pain_dyspnoea" in summary.red_flags_summary


# ---------------------------------------------------------------------------
# Failover
# ---------------------------------------------------------------------------


class TestSchemaValidationEnablesFailover:
    """Swallowing bad output silently defeated the whole routing design."""

    def test_non_json_raises(self):
        with pytest.raises(SummaryValidationError):
            _parse_and_validate("I'm afraid I can't help with that.")

    def test_json_of_the_wrong_shape_raises(self):
        with pytest.raises(SummaryValidationError):
            _parse_and_validate('{"hpi": 123}')

    def test_valid_output_is_returned(self):
        summary = _parse_and_validate('{"chief_complaint": "fever"}')
        assert summary.chief_complaint == "fever"


class TestRoutingFailover:
    @pytest.mark.asyncio
    async def test_falls_back_to_deterministic_with_nothing_configured(
        self, sql_db, seeded_patient, monkeypatch
    ):
        from app.core.config import Settings, get_settings
        from app.services.summary import router as summary_router

        get_settings.cache_clear()
        monkeypatch.setattr(
            summary_router,
            "get_settings",
            lambda: Settings(main_llm_api_key="", local_llm_endpoint=""),
        )

        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        summary, generated_by = await summary_router.generate_summary(context)

        assert generated_by == "deterministic"
        assert summary.chief_complaint == "chest_pain"

    @pytest.mark.asyncio
    async def test_a_failing_main_api_falls_through_to_deterministic(
        self, sql_db, seeded_patient, monkeypatch
    ):
        """The behaviour the swallowed-exception bug prevented."""
        from app.core.config import Settings
        from app.services.summary import router as summary_router

        async def _boom(_context):
            raise SummaryValidationError("model returned prose")

        monkeypatch.setattr(
            summary_router,
            "get_settings",
            lambda: Settings(main_llm_api_key="sk-test", local_llm_endpoint=""),
        )
        monkeypatch.setattr(summary_router, "summarize_main_api", _boom)

        context = retrieve_session_context(str(seeded_patient["session_id"]), sql_db)
        summary, generated_by = await summary_router.generate_summary(context)

        assert generated_by == "deterministic"
        assert summary.chief_complaint == "chest_pain"


class TestLlmEndpointConfiguration:
    def test_main_and_local_are_separate_settings(self):
        """summarize_main_api used to read local_llm_endpoint as its own URL."""
        from app.core.config import Settings

        settings = Settings(
            main_llm_endpoint="https://api.openai.com/v1/chat/completions",
            local_llm_endpoint="http://localhost:11434",
        )
        assert settings.main_llm_endpoint != settings.local_llm_endpoint
        assert settings.main_llm_model
        assert settings.local_llm_model


class TestPasswordHashing:
    def test_round_trip(self):
        from app.services.password import hash_password, verify_password

        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed)
        assert not verify_password("wrong", hashed)

    def test_long_passphrases_are_distinguishable(self):
        """bcrypt truncates at 72 bytes; the SHA-256 pre-hash is why this holds."""
        from app.services.password import hash_password, verify_password

        base = "x" * 80
        hashed = hash_password(base + "aaa")
        assert not verify_password(base + "bbb", hashed)
        assert verify_password(base + "aaa", hashed)

    def test_a_corrupt_hash_fails_closed(self):
        from app.services.password import verify_password

        assert verify_password("anything", "not-a-bcrypt-hash") is False
        assert verify_password("anything", "") is False
