"""Tests for Module A — Interview Engine.

Tests the full flow: start session → answer questions → red-flag detection → complete.
Uses the FakeSession from Phase 1 tests.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.models import ConsentRecord, Patient
from app.services.jwt import create_patient_token
from tests.fake_db import FakeSession


def _sample_answer(question: dict) -> object:
    """A type-appropriate answer for any question, for walking the interview."""
    kind = question["input_type"]
    if kind == "numeric":
        return 5
    if kind == "yes_no":
        return True
    if kind == "multi_choice":
        return [question["options"][0]["key"]] if question["options"] else []
    if kind == "single_choice":
        return question["options"][0]["key"] if question["options"] else "unknown"
    return "sample narrative answer"


@pytest.fixture()
def db() -> FakeSession:
    return FakeSession()


@pytest.fixture()
def client(db: FakeSession):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(db: FakeSession) -> dict[str, str]:
    """Create a patient with active consent (interview scope) and return auth headers."""
    patient = Patient(
        id=uuid.uuid4(),
        name="Test Patient",
        age=30,
        gender="female",
        phone="9999999999",
        preferred_language="en",
    )
    db.add(patient)

    consent = ConsentRecord(
        id=uuid.uuid4(),
        patient_id=patient.id,
        scope={"interview": True, "documents": True},
        language="en",
        audio_confirmed=True,
    )
    db.add(consent)

    token = create_patient_token(patient.id)
    return {"Authorization": f"Bearer {token}"}


class TestStartSession:
    def test_start_session_general_mode(self, client, auth_headers):
        response = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["mode"] == "general"
        assert data["next_question"] is not None
        # First question should be chief complaint
        assert data["next_question"]["field_id"] == "chief_complaint"

    def test_start_session_ayush_mode(self, client, auth_headers):
        response = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "ayush"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["mode"] == "ayush"

    def test_start_session_requires_consent(self, client):
        """Without a token, should be 401."""
        response = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
        )
        assert response.status_code == 401


class TestAnswerFlow:
    def _start_session(self, client, headers) -> str:
        response = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=headers,
        )
        return response.json()["session_id"]

    def test_answer_chief_complaint_advances_to_hpi(self, client, auth_headers):
        session_id = self._start_session(client, auth_headers)

        # Answer chief complaint = chest pain
        response = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is True
        # Next question should be from chest_pain HPI template
        assert data["next_question"]["field_id"] == "hpi.site"
        # The chief complaint is excluded from the progress count, so answering
        # only it leaves zero *clinical* questions answered. The bar also stops
        # being suppressed from here on.
        assert data["progress"]["answered"] == 0
        assert data["progress"]["awaiting_chief_complaint"] is False

    def test_answer_with_voice_mode(self, client, auth_headers):
        session_id = self._start_session(client, auth_headers)

        response = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={
                "field_id": "chief_complaint",
                "value": "fever",
                "input_mode": "voice",
                "raw_transcript": "I have fever since 3 days",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is True
        # Should now be in fever HPI
        assert "hpi." in data["next_question"]["field_id"]

    def test_progress_increases_with_answers(self, client, auth_headers):
        session_id = self._start_session(client, auth_headers)

        r1 = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "fever", "input_mode": "touch"},
            headers=auth_headers,
        )
        progress_1 = r1.json()["progress"]["answered"]

        # Answer next question
        next_field = r1.json()["next_question"]["field_id"]
        r2 = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": next_field, "value": "today", "input_mode": "touch"},
            headers=auth_headers,
        )
        progress_2 = r2.json()["progress"]["answered"]
        assert progress_2 > progress_1


class TestRedFlags:
    def _start_chest_pain_session(self, client, headers) -> str:
        session_id = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=headers,
        ).json()["session_id"]

        # Set chief complaint to chest pain
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
            headers=headers,
        )
        return session_id

    def test_chest_pain_with_breathlessness_fires_red_flag(self, client, auth_headers):
        session_id = self._start_chest_pain_session(client, auth_headers)

        # Answer site = central
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "hpi.site", "value": "central", "input_mode": "touch"},
            headers=auth_headers,
        )

        # Answer associations includes breathlessness — this should trigger the red flag
        response = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={
                "field_id": "hpi.associations",
                "value": ["breathlessness", "sweating"],
                "input_mode": "touch",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert len(data["red_flags_fired"]) > 0
        assert any(f["severity"] == "critical" for f in data["red_flags_fired"])

    def test_red_flag_queryable_via_endpoint(self, client, auth_headers):
        session_id = self._start_chest_pain_session(client, auth_headers)

        # Trigger the flag
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "hpi.site", "value": "central", "input_mode": "touch"},
            headers=auth_headers,
        )
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={
                "field_id": "hpi.associations",
                "value": ["breathlessness"],
                "input_mode": "touch",
            },
            headers=auth_headers,
        )

        # Query red flags endpoint
        response = client.get(
            f"/api/v1/interview/sessions/{session_id}/red-flags",
            headers=auth_headers,
        )
        assert response.status_code == 200
        flags = response.json()
        assert len(flags) >= 1
        assert flags[0]["severity"] == "critical"

    def test_no_false_red_flag_without_matching_conditions(self, client, auth_headers):
        session_id = self._start_chest_pain_session(client, auth_headers)

        # Answer site = right (not central/left)
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "hpi.site", "value": "right", "input_mode": "touch"},
            headers=auth_headers,
        )
        # Answer associations = none (no breathlessness)
        response = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "hpi.associations", "value": ["none"], "input_mode": "touch"},
            headers=auth_headers,
        )
        data = response.json()
        assert len(data["red_flags_fired"]) == 0


class TestCompleteSession:
    def test_complete_marks_session_done(self, client, auth_headers):
        session_id = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=auth_headers,
        ).json()["session_id"]

        response = client.post(
            f"/api/v1/interview/sessions/{session_id}/complete",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("completed", "red_flagged")
        assert data["completed_at"] is not None


class TestASR:
    def test_asr_endpoint_returns_transcript(self, client, auth_headers):
        # Without WHISPER_API_URL set, should return mock
        import io

        audio_bytes = io.BytesIO(b"fake audio data")
        response = client.post(
            "/api/v1/interview/asr",
            files={"file": ("test.webm", audio_bytes, "audio/webm")},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "text" in data
        assert data["is_mock"] is True  # No API configured in tests

    def test_asr_rejects_unauthenticated_upload(self, client):
        """The regression this exists for.

        /interview/asr was reachable with no credentials at all, so anyone could
        POST audio and bill the ASR provider. The route now carries the same
        consent dependency as the rest of the module.
        """
        import io

        response = client.post(
            "/api/v1/interview/asr",
            files={"file": ("test.webm", io.BytesIO(b"x"), "audio/webm")},
        )
        assert response.status_code == 401


class TestConsentEnforcement:
    """Wave 2 requires consent on every interview endpoint. Prove it, per route."""

    @pytest.fixture()
    def token_without_consent(self, db: FakeSession) -> dict[str, str]:
        patient = Patient(
            id=uuid.uuid4(),
            name="No Consent Patient",
            age=40,
            gender="male",
            phone="8888888888",
            preferred_language="en",
        )
        db.add(patient)
        return {"Authorization": f"Bearer {create_patient_token(patient.id)}"}

    def test_start_session_refused_without_consent(self, client, token_without_consent):
        response = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=token_without_consent,
        )
        assert response.status_code == 403

    def test_asr_refused_without_consent(self, client, token_without_consent):
        import io

        response = client.post(
            "/api/v1/interview/asr",
            files={"file": ("t.webm", io.BytesIO(b"x"), "audio/webm")},
            headers=token_without_consent,
        )
        assert response.status_code == 403

    def test_audio_route_refused_without_consent(self, client, token_without_consent):
        response = client.get(
            "/api/v1/interview/audio/en_abc123.mp3",
            headers=token_without_consent,
        )
        assert response.status_code == 403


class TestProgressStability:
    """The denominator the patient sees must not change mid-interview."""

    def test_total_is_stable_once_chief_complaint_is_known(self, client, auth_headers):
        session_id = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=auth_headers,
        ).json()["session_id"]

        first = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
            headers=auth_headers,
        ).json()
        baseline_total = first["progress"]["total"]

        # Walk several more answers; the total must not move.
        field = first["next_question"]["field_id"]
        for value in ("central", "hours", "sudden"):
            result = client.post(
                f"/api/v1/interview/sessions/{session_id}/answer",
                json={"field_id": field, "value": value, "input_mode": "touch"},
                headers=auth_headers,
            ).json()
            assert result["progress"]["total"] == baseline_total
            if result["next_question"] is None:
                break
            field = result["next_question"]["field_id"]

    def test_bar_is_suppressed_until_chief_complaint_answered(self, client, auth_headers):
        session = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=auth_headers,
        ).json()
        assert session["progress"]["awaiting_chief_complaint"] is True

    def test_ayush_mode_has_a_longer_interview(self, client, auth_headers):
        """The AYUSH branch must actually add the Dashavidha Pariksha fields."""
        totals = {}
        for mode in ("general", "ayush"):
            session_id = client.post(
                "/api/v1/interview/sessions", json={"mode": mode}, headers=auth_headers
            ).json()["session_id"]
            result = client.post(
                f"/api/v1/interview/sessions/{session_id}/answer",
                json={"field_id": "chief_complaint", "value": "fever", "input_mode": "touch"},
                headers=auth_headers,
            ).json()
            totals[mode] = result["progress"]["total"]

        assert totals["ayush"] > totals["general"]


class TestAnswerValidation:
    def _fever_session(self, client, headers) -> str:
        session_id = client.post(
            "/api/v1/interview/sessions", json={"mode": "general"}, headers=headers
        ).json()["session_id"]
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
            headers=headers,
        )
        return session_id

    def test_numeric_answer_out_of_range_is_refused(self, client, auth_headers):
        """A pain score of 400 is a typo or a bad client, not a clinical finding."""
        session_id = self._fever_session(client, auth_headers)

        question = client.get(
            f"/api/v1/interview/sessions/{session_id}/next-question", headers=auth_headers
        ).json()

        for _ in range(40):
            assert question is not None, "never reached a numeric question"

            if question["input_type"] == "numeric":
                for bad_value in (400, 0, -3, "not a number"):
                    rejected = client.post(
                        f"/api/v1/interview/sessions/{session_id}/answer",
                        json={
                            "field_id": question["field_id"],
                            "value": bad_value,
                            "input_mode": "touch",
                        },
                        headers=auth_headers,
                    )
                    assert rejected.status_code == 400, f"{bad_value!r} should be refused"

                # And the in-range value is still accepted.
                accepted = client.post(
                    f"/api/v1/interview/sessions/{session_id}/answer",
                    json={
                        "field_id": question["field_id"],
                        "value": 7,
                        "input_mode": "touch",
                    },
                    headers=auth_headers,
                )
                assert accepted.status_code == 200
                return

            res = client.post(
                f"/api/v1/interview/sessions/{session_id}/answer",
                json={
                    "field_id": question["field_id"],
                    "value": _sample_answer(question),
                    "input_mode": "touch",
                },
                headers=auth_headers,
            )
            assert res.status_code == 200, res.text
            question = res.json()["next_question"]

        pytest.fail("never reached a numeric question")

    def test_required_question_cannot_be_skipped(self, client, auth_headers):
        session_id = client.post(
            "/api/v1/interview/sessions", json={"mode": "general"}, headers=auth_headers
        ).json()["session_id"]

        response = client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "skipped": True, "input_mode": "touch"},
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_skip_is_recorded_as_a_skip_not_as_a_value(self, client, auth_headers, db):
        """Storing the string "skipped" would make it look like the answer."""
        from app.models.models import InterviewAnswer

        session_id = self._fever_session(client, auth_headers)

        # Walk forward, answering each question according to its declared type,
        # until an optional one turns up.
        question = client.get(
            f"/api/v1/interview/sessions/{session_id}/next-question", headers=auth_headers
        ).json()

        for _ in range(40):
            assert question is not None, "never reached an optional question"

            if not question["required"]:
                field = question["field_id"]
                client.post(
                    f"/api/v1/interview/sessions/{session_id}/answer",
                    json={"field_id": field, "skipped": True, "input_mode": "touch"},
                    headers=auth_headers,
                )
                stored = [a for a in db.rows_of(InterviewAnswer) if a.field == field]
                assert stored, f"no answer row written for {field}"
                assert stored[-1].value == {"skipped": True}
                return

            res = client.post(
                f"/api/v1/interview/sessions/{session_id}/answer",
                json={
                    "field_id": question["field_id"],
                    "value": _sample_answer(question),
                    "input_mode": "touch",
                },
                headers=auth_headers,
            )
            assert res.status_code == 200, res.text
            question = res.json()["next_question"]

        pytest.fail("never reached an optional question")


class TestRedFlagRehydration:
    def test_red_flag_query_returns_clinical_wording_not_the_rule_id(self, client, auth_headers):
        """GET /red-flags used to return the bare rule id as the display name."""
        session_id = client.post(
            "/api/v1/interview/sessions", json={"mode": "general"}, headers=auth_headers
        ).json()["session_id"]
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
            headers=auth_headers,
        )
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={"field_id": "hpi.site", "value": "central", "input_mode": "touch"},
            headers=auth_headers,
        )
        client.post(
            f"/api/v1/interview/sessions/{session_id}/answer",
            json={
                "field_id": "hpi.associations",
                "value": ["breathlessness"],
                "input_mode": "touch",
            },
            headers=auth_headers,
        )

        flags = client.get(
            f"/api/v1/interview/sessions/{session_id}/red-flags", headers=auth_headers
        ).json()
        assert flags, "expected at least one red flag"

        flag = flags[0]
        assert flag["id"] == "cardiac_chest_pain_dyspnoea"
        # The name must be the clinical sentence, not the identifier.
        assert flag["name"] != flag["id"]
        assert "chest pain" in flag["name"].lower()
        assert flag["description"], "description must survive the round trip"


class TestTtsWiring:
    def test_audio_url_is_absent_when_tts_is_not_configured(self, client, auth_headers):
        """No provider configured in tests, so prompts are text-only.

        The point of the assertion is that the field is wired at all: it used to
        be hardcoded to None regardless of configuration.
        """
        from app.interview import tts

        assert tts.is_enabled() is False

        session = client.post(
            "/api/v1/interview/sessions", json={"mode": "general"}, headers=auth_headers
        ).json()
        assert session["next_question"]["audio_url"] is None

    def test_cached_path_rejects_traversal(self):
        """The filename arrives from a URL, so it is untrusted."""
        from app.interview import tts

        for hostile in (
            "../../../../etc/passwd",
            "..\\..\\windows\\win.ini",
            "/etc/passwd",
            ".hidden",
            "",
        ):
            assert tts.cached_path(hostile) is None
