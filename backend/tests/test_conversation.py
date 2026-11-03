"""Tests for the LLM-driven conversational interview engine.

The engine's whole value depends on one property: the model chooses the wording,
the ontology chooses what exists. Most of what follows tests that boundary rather
than the conversation, because the conversation failing is visible and the
boundary failing is not — an off-ontology field looks like a successful turn at
every layer and simply never reaches the physician.

Zero live calls. ``conftest`` pins every provider off, and the model itself is
replaced at ``conversation.post_chat_completion``.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.interview import conversation
from app.interview.dialogue import InterviewState
from app.interview.red_flags import evaluate_red_flags
from app.models.models import InterviewAnswer, InterviewMessage, InterviewSession


def _state(
    complaint: str | None = "chest_pain",
    answered: set[str] | None = None,
    mode: str = "general",
) -> InterviewState:
    return InterviewState(
        chief_complaint=complaint,
        mode=mode,
        answered_field_ids=answered or set(),
    )


def _reply(**payload) -> str:
    """A model turn as JSON."""
    payload.setdefault("reply", "When did the pain start?")
    return json.dumps(payload)


@pytest.fixture()
def model(monkeypatch):
    """Replace the model with a scripted reply. Returns a setter."""
    box: dict[str, str] = {"content": _reply()}

    async def fake_post(messages, **kwargs):
        box["messages"] = messages
        return box["content"]

    monkeypatch.setattr(conversation, "post_chat_completion", fake_post)
    return box


# ---------------------------------------------------------------------------
# The catalogue — what the model is allowed to touch
# ---------------------------------------------------------------------------


class TestOutstandingQuestions:
    def test_only_the_complaint_is_reachable_before_it_is_known(self):
        """Nothing else can be legally described until the template is chosen.

        The complaint selects the HPI template, and the templates disagree about
        what a given field id means, so an answer captured before then cannot be
        validated against anything.
        """
        outstanding = conversation.outstanding_questions(_state(complaint=None))

        assert [q.field_id for q in outstanding] == ["chief_complaint"]

    def test_template_fields_appear_once_the_complaint_is_known(self):
        ids = {q.field_id for q in conversation.outstanding_questions(_state("chest_pain"))}

        assert "hpi.character" in ids
        assert "past_medical.conditions" in ids
        assert "ros.cardiovascular" in ids

    def test_answered_fields_drop_out(self):
        outstanding = conversation.outstanding_questions(
            _state("chest_pain", answered={"chief_complaint", "hpi.site"})
        )

        assert "hpi.site" not in {q.field_id for q in outstanding}

    def test_ayush_fields_only_in_ayush_mode(self):
        general = {q.field_id for q in conversation.outstanding_questions(_state("fever"))}
        ayush = {
            q.field_id for q in conversation.outstanding_questions(_state("fever", mode="ayush"))
        }

        assert not any(f.startswith("ayush.") for f in general)
        assert "ayush.prakriti" in ayush


class TestCatalogueDescription:
    def test_lists_legal_option_keys(self):
        text = conversation.describe_catalogue(
            conversation.outstanding_questions(_state("chest_pain"))
        )

        assert '"crushing"' in text
        assert '"breathlessness"' in text

    def test_explains_what_each_key_means(self):
        """The key alone is not enough to map "a heavy weight" onto "crushing"."""
        text = conversation.describe_catalogue(
            conversation.outstanding_questions(_state("chest_pain"))
        )

        assert "crushing = Crushing / heavy / pressure" in text

    def test_marks_optional_fields(self):
        text = conversation.describe_catalogue(
            conversation.outstanding_questions(_state("chest_pain"))
        )

        assert "optional" in text


# ---------------------------------------------------------------------------
# Validation — the gate between the model and the clinical record
# ---------------------------------------------------------------------------


class TestValidateExtraction:
    def test_accepts_a_legal_field(self):
        accepted, rejected = conversation.validate_extraction(
            {"hpi.character": "crushing"}, _state("chest_pain")
        )

        assert accepted == {"hpi.character": "crushing"}
        assert rejected == []

    def test_rejects_an_invented_field_id(self):
        """The summariser reads fixed ids and ignores everything else.

        Without this gate a model emitting `hpi.location` would look successful
        at every layer and quietly lose the answer.
        """
        accepted, rejected = conversation.validate_extraction(
            {"hpi.location": "central"}, _state("chest_pain")
        )

        assert accepted == {}
        assert rejected == ["hpi.location"]

    def test_rejects_a_plausible_synonym(self):
        """Red-flag rules match exact keys, so a synonym is worse than nothing."""
        accepted, rejected = conversation.validate_extraction(
            {"hpi.character": "heavy pressure"}, _state("chest_pain")
        )

        assert accepted == {}
        assert rejected == ["hpi.character"]

    def test_rejects_a_field_belonging_to_another_template(self):
        """`hpi.degree` is a fever field; it is not legal on a chest-pain session."""
        accepted, rejected = conversation.validate_extraction(
            {"hpi.degree": "high"}, _state("chest_pain")
        )

        assert accepted == {}
        assert rejected == ["hpi.degree"]

    def test_refuses_to_overwrite_an_answered_field(self):
        """A later, vaguer turn must not overwrite an explicit earlier answer.

        ``interview_answers`` has no uniqueness constraint, so the duplicate row
        would win by insertion order rather than by being more correct.
        """
        accepted, rejected = conversation.validate_extraction(
            {"hpi.site": "left"},
            _state("chest_pain", answered={"chief_complaint", "hpi.site"}),
        )

        assert accepted == {}
        assert rejected == ["hpi.site"]

    def test_tolerates_a_non_dict(self):
        assert conversation.validate_extraction("not a dict", _state()) == ({}, [])


class TestValueCoercion:
    @pytest.mark.parametrize("raw", [True, "true", "yes", "haan", "1"])
    def test_yes_no_accepts_affirmatives(self, raw):
        accepted, _ = conversation.validate_extraction(
            {"ros.cardiovascular": raw}, _state("chest_pain")
        )

        assert accepted == {"ros.cardiovascular": True}

    @pytest.mark.parametrize("raw", [False, "false", "no", "nahi"])
    def test_yes_no_accepts_negatives(self, raw):
        accepted, _ = conversation.validate_extraction(
            {"ros.cardiovascular": raw}, _state("chest_pain")
        )

        assert accepted == {"ros.cardiovascular": False}

    def test_yes_no_rejects_a_non_answer(self):
        _, rejected = conversation.validate_extraction(
            {"ros.cardiovascular": "maybe sometimes"}, _state("chest_pain")
        )

        assert rejected == ["ros.cardiovascular"]

    def test_numeric_accepts_in_range(self):
        accepted, _ = conversation.validate_extraction({"hpi.severity": "7"}, _state("chest_pain"))

        assert accepted == {"hpi.severity": 7}

    @pytest.mark.parametrize("raw", [0, 11, 50, -3, "unbearable"])
    def test_numeric_rejects_out_of_range(self, raw):
        """A model returning 50 for "unbearable" would clear the >=9 red-flag
        threshold with a value no clinician would trust."""
        _, rejected = conversation.validate_extraction({"hpi.severity": raw}, _state("chest_pain"))

        assert rejected == ["hpi.severity"]

    def test_multi_choice_filters_illegal_entries(self):
        accepted, _ = conversation.validate_extraction(
            {"hpi.associations": ["breathlessness", "shortness of breath", "sweating"]},
            _state("chest_pain"),
        )

        assert accepted == {"hpi.associations": ["breathlessness", "sweating"]}

    def test_multi_choice_wraps_a_bare_value(self):
        accepted, _ = conversation.validate_extraction(
            {"hpi.associations": "sweating"}, _state("chest_pain")
        )

        assert accepted == {"hpi.associations": ["sweating"]}

    def test_multi_choice_rejects_all_illegal(self):
        """An empty list is indistinguishable from "not asked" downstream, so it
        must not be stored as a positive finding of nothing."""
        _, rejected = conversation.validate_extraction(
            {"hpi.associations": ["shortness of breath"]}, _state("chest_pain")
        )

        assert rejected == ["hpi.associations"]

    def test_free_text_is_stripped(self):
        accepted, _ = conversation.validate_extraction(
            {"allergy.known": "  penicillin  "}, _state("chest_pain")
        )

        assert accepted == {"allergy.known": "penicillin"}

    def test_free_text_rejects_empty(self):
        _, rejected = conversation.validate_extraction(
            {"allergy.known": "   "}, _state("chest_pain")
        )

        assert rejected == ["allergy.known"]


# ---------------------------------------------------------------------------
# The safety property: triage stays deterministic
# ---------------------------------------------------------------------------


class TestRedFlagsRemainDeterministic:
    """Validated conversational fields must fire the same rules as touch input.

    This is the reason extraction is constrained at all. The rules match exact
    option keys, so the question is not whether the model *noticed* something
    worrying but whether what it extracted is still machine-checkable.
    """

    def test_validated_fields_fire_the_cardiac_rule(self):
        accepted, rejected = conversation.validate_extraction(
            {
                "hpi.site": "central",
                "hpi.associations": ["breathlessness"],
            },
            _state("chest_pain"),
        )
        assert rejected == []

        fired = evaluate_red_flags(accepted, chief_complaint="chest_pain")

        assert "cardiac_chest_pain_dyspnoea" in {r.id for r in fired}

    def test_synonyms_would_have_fired_nothing(self):
        """Why validation is load-bearing rather than tidy.

        Had the engine trusted the model's phrasing, this transcript would read
        perfectly and triage would never have run.
        """
        unvalidated = {
            "hpi.site": "centre of the chest",
            "hpi.associations": ["shortness of breath"],
        }

        assert evaluate_red_flags(unvalidated, chief_complaint="chest_pain") == []

    def test_severity_threshold_survives_the_round_trip(self):
        accepted, _ = conversation.validate_extraction({"hpi.severity": 9}, _state("chest_pain"))

        fired = evaluate_red_flags(accepted, chief_complaint="chest_pain")

        assert "severe_pain_9_10" in {r.id for r in fired}

    def test_a_model_concern_does_not_fire_a_flag(self, model):
        """The model's opinion is advisory. Only the rules fire flags."""
        model["content"] = _reply(
            extracted_data={"hpi.character": "aching"},
            concern="patient sounds frightened, possible cardiac event",
        )

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "it aches a bit"))

        assert turn.advisory_red_flag is not None
        assert evaluate_red_flags(turn.accepted, chief_complaint="chest_pain") == []


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


def _run(coro):
    import asyncio

    return asyncio.run(coro)


class TestNextTurn:
    def test_parses_a_normal_reply(self, model):
        model["content"] = _reply(
            reply="Kahan dard ho raha hai?",
            extracted_data={"hpi.character": "crushing"},
        )

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "bhaari lag raha hai"))

        assert turn.reply == "Kahan dard ho raha hai?"
        assert turn.accepted == {"hpi.character": "crushing"}

    def test_tolerates_markdown_fences(self, model):
        model["content"] = f"```json\n{_reply(reply='Hello')}\n```"

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "hi"))

        assert turn.reply == "Hello"

    def test_recovers_json_after_a_prose_preamble(self, model):
        """A formatting slip should not stall the interview."""
        model["content"] = f"Sure, here you go: {_reply(reply='Where is the pain?')}"

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "hi"))

        assert turn.reply == "Where is the pain?"

    def test_completion_is_decided_by_the_ontology_not_the_model(self, model):
        """A model declaring itself finished must not end an incomplete record."""
        model["content"] = _reply(interview_complete=True)

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "that's all"))

        assert turn.interview_complete is False

    def test_completion_is_reported_when_everything_is_captured(self, model):
        every_field = {
            q.field_id for q in conversation.outstanding_questions(_state("chest_pain"))
        } | {"chief_complaint"}
        model["content"] = _reply()

        turn = _run(
            conversation.next_turn(_state("chest_pain", answered=every_field), [], "nothing else")
        )

        assert turn.interview_complete is True

    def test_quick_replies_use_ontology_keys(self, model):
        """A tapped chip must produce a value the validator will accept."""
        model["content"] = _reply(asking_field_id="hpi.character")

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "hi"))

        keys = {chip.key for chip in turn.quick_replies}
        assert keys == {"crushing", "sharp", "burning", "aching", "tearing"}

    def test_free_text_questions_offer_no_chips(self, model):
        model["content"] = _reply(asking_field_id="allergy.known")

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "hi"))

        assert turn.quick_replies == []

    def test_section_follows_the_field_being_asked(self, model):
        model["content"] = _reply(asking_field_id="past_medical.conditions")

        turn = _run(conversation.next_turn(_state("chest_pain"), [], "hi"))

        assert turn.section == "past_medical"

    def test_the_catalogue_reaches_the_model(self, model):
        _run(conversation.next_turn(_state("chest_pain"), [], "hi"))

        final_user_turn = model["messages"][-1]["content"]
        assert "hpi.character" in final_user_turn
        assert '"crushing"' in final_user_turn

    def test_the_patients_language_reaches_the_model(self, model):
        _run(conversation.next_turn(_state("chest_pain"), [], "hi", language="ta"))

        assert "Tamil" in model["messages"][0]["content"]

    def test_opening_turn_sends_no_patient_message(self, model):
        _run(conversation.next_turn(_state(complaint=None), [], None))

        assert "has not said anything yet" in model["messages"][-1]["content"]

    def test_an_overlong_utterance_is_truncated(self, model):
        _run(conversation.next_turn(_state("chest_pain"), [], "a" * 9000))

        assert len(model["messages"][-1]["content"]) < 9000

    def test_history_is_bounded(self, model):
        history = [{"role": "user", "content": f"turn {i}"} for i in range(100)]

        _run(conversation.next_turn(_state("chest_pain"), history, "hi"))

        # system + capped history + the current user turn
        assert len(model["messages"]) == conversation.MAX_HISTORY_TURNS + 2

    def test_a_malformed_reply_raises(self, model):
        """The caller falls back to the deterministic engine, so failure must be
        visible rather than an empty reply."""
        model["content"] = "the model felt chatty today"

        with pytest.raises(Exception):  # noqa: B017 - json or ValueError, both fine
            _run(conversation.next_turn(_state("chest_pain"), [], "hi"))


class TestAvailability:
    def test_follows_the_summariser_gate(self, monkeypatch):
        """One definition of "configured", so the two cannot drift."""
        monkeypatch.setattr(conversation, "main_api_is_configured", lambda: True)
        assert conversation.is_available() is True

        monkeypatch.setattr(conversation, "main_api_is_configured", lambda: False)
        assert conversation.is_available() is False


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _conversation_session(sql_db, patient_id) -> uuid.UUID:
    sid = uuid.uuid4()
    sql_db.add(
        InterviewSession(
            id=sid,
            patient_id=patient_id,
            mode="general",
            engine="conversation",
            status="in_progress",
        )
    )
    sql_db.commit()
    return sid


class TestSessionCreation:
    def test_conversation_downgrades_when_no_model_is_configured(self, sql_client, patient_headers):
        """A missing API key should not look like a broken kiosk."""
        res = sql_client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general", "engine": "conversation"},
            headers=patient_headers,
        )

        assert res.status_code == 201, res.text
        body = res.json()
        assert body["engine"] == "legacy"
        assert body["next_question"] is not None

    def test_legacy_remains_the_default(self, sql_client, patient_headers):
        res = sql_client.post("/api/v1/interview/sessions", json={}, headers=patient_headers)

        assert res.json()["engine"] == "legacy"

    def test_an_unknown_engine_is_refused(self, sql_client, patient_headers):
        res = sql_client.post(
            "/api/v1/interview/sessions",
            json={"engine": "voice-live"},
            headers=patient_headers,
        )

        assert res.status_code == 422


class TestMessageEndpoint:
    def test_rejects_a_legacy_session(self, sql_client, patient_headers, seeded_patient):
        """The engines disagree about whose turn it is, so mixing them would
        re-ask what the patient already answered."""
        res = sql_client.post(
            f"/api/v1/interview/sessions/{seeded_patient['session_id']}/message",
            json={"message": "it hurts"},
            headers=patient_headers,
        )

        assert res.status_code == 409

    def test_unknown_session_is_404(self, sql_client, patient_headers):
        res = sql_client.post(
            f"/api/v1/interview/sessions/{uuid.uuid4()}/message",
            json={"message": "hello"},
            headers=patient_headers,
        )

        assert res.status_code == 404

    def test_a_malformed_session_id_is_404_not_500(self, sql_client, patient_headers):
        res = sql_client.post(
            "/api/v1/interview/sessions/not-a-uuid/message",
            json={"message": "hello"},
            headers=patient_headers,
        )

        assert res.status_code == 404

    def test_an_empty_message_is_refused(self, sql_client, patient_headers, seeded_patient, sql_db):
        sid = _conversation_session(sql_db, seeded_patient["patient_id"])

        res = sql_client.post(
            f"/api/v1/interview/sessions/{sid}/message",
            json={"message": ""},
            headers=patient_headers,
        )

        assert res.status_code == 422

    def test_a_turn_persists_transcript_answers_and_progress(
        self, sql_client, patient_headers, seeded_patient, sql_db, model
    ):
        sid = _conversation_session(sql_db, seeded_patient["patient_id"])
        model["content"] = _reply(
            reply="Kitna tez dard hai, 1 se 10 mein?",
            extracted_data={"chief_complaint": "chest_pain"},
        )

        res = sql_client.post(
            f"/api/v1/interview/sessions/{sid}/message",
            json={"message": "seene mein dard ho raha hai", "input_mode": "voice"},
            headers=patient_headers,
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["reply"] == "Kitna tez dard hai, 1 se 10 mein?"
        assert body["captured"] == {"chief_complaint": "chest_pain"}

        # The conversation is logged: what the patient said, and the reply.
        turns = (
            sql_db.query(InterviewMessage)
            .filter(InterviewMessage.session_id == sid)
            .order_by(InterviewMessage.created_at)
            .all()
        )
        assert [t.role for t in turns] == ["patient", "assistant"]
        assert turns[0].input_mode == "voice"

        # And the clinical record is written in the shape the summariser reads.
        answers = sql_db.query(InterviewAnswer).filter(InterviewAnswer.session_id == sid).all()
        assert {a.field: a.value for a in answers} == {"chief_complaint": {"answer": "chest_pain"}}

        # Setting the complaint selects the template, so progress becomes knowable.
        session = sql_db.query(InterviewSession).filter(InterviewSession.id == sid).one()
        assert session.chief_complaint == "chest_pain"
        assert body["progress"]["awaiting_chief_complaint"] is False

    def test_red_flags_fire_from_a_conversation(
        self, sql_client, patient_headers, seeded_patient, sql_db, model
    ):
        """End to end: spoken symptoms reach the deterministic triage rules."""
        sid = _conversation_session(sql_db, seeded_patient["patient_id"])
        sql_db.query(InterviewSession).filter(
            InterviewSession.id == sid
        ).one().chief_complaint = "chest_pain"
        sql_db.commit()

        model["content"] = _reply(
            reply="I understand. Let me get help.",
            extracted_data={
                "hpi.site": "central",
                "hpi.associations": ["breathlessness", "sweating"],
            },
        )

        res = sql_client.post(
            f"/api/v1/interview/sessions/{sid}/message",
            json={"message": "chest is crushing and I cannot breathe"},
            headers=patient_headers,
        )

        assert res.status_code == 200, res.text
        fired = {f["id"] for f in res.json()["red_flags_fired"]}
        assert "cardiac_chest_pain_dyspnoea" in fired

        session = sql_db.query(InterviewSession).filter(InterviewSession.id == sid).one()
        assert session.status == "red_flagged"

    def test_off_ontology_extraction_is_dropped_not_stored(
        self, sql_client, patient_headers, seeded_patient, sql_db, model
    ):
        sid = _conversation_session(sql_db, seeded_patient["patient_id"])
        model["content"] = _reply(extracted_data={"hpi.vibes": "bad", "made.up": 1})

        res = sql_client.post(
            f"/api/v1/interview/sessions/{sid}/message",
            json={"message": "hello"},
            headers=patient_headers,
        )

        assert res.status_code == 200, res.text
        assert res.json()["captured"] == {}
        assert sql_db.query(InterviewAnswer).filter(InterviewAnswer.session_id == sid).count() == 0

    def test_model_failure_is_503_not_500(
        self, sql_client, patient_headers, seeded_patient, sql_db, monkeypatch
    ):
        """The request was fine; the upstream model was not. The client should
        retry or switch engines, not change what it sent."""
        sid = _conversation_session(sql_db, seeded_patient["patient_id"])

        async def boom(*args, **kwargs):
            raise RuntimeError("upstream exploded")

        monkeypatch.setattr(conversation, "post_chat_completion", boom)

        res = sql_client.post(
            f"/api/v1/interview/sessions/{sid}/message",
            json={"message": "hello"},
            headers=patient_headers,
        )

        assert res.status_code == 503

    def test_a_completed_session_is_closed(
        self, sql_client, patient_headers, seeded_patient, sql_db
    ):
        sid = _conversation_session(sql_db, seeded_patient["patient_id"])
        sql_db.query(InterviewSession).filter(InterviewSession.id == sid).one().status = "completed"
        sql_db.commit()

        res = sql_client.post(
            f"/api/v1/interview/sessions/{sid}/message",
            json={"message": "one more thing"},
            headers=patient_headers,
        )

        assert res.status_code == 400


# ---------------------------------------------------------------------------
# The language a request is answered in
# ---------------------------------------------------------------------------


class TestSpokenLanguageOverride:
    """An explicit ?language= must beat the patient record.

    The record is a snapshot from registration, and the header dropdown can change
    the choice at any point afterwards. Interface strings are bundled client-side,
    so before this the screen followed the dropdown while the questions and audio
    stayed in the registration language — a Marathi screen narrated in English.
    """

    def _patient(self, preferred: str = "en"):
        from app.models.models import Patient

        return Patient(id=uuid.uuid4(), name="T", preferred_language=preferred)

    def test_explicit_language_wins(self):
        from app.api.routes.interview import _spoken_language

        assert _spoken_language("mr", self._patient("en")) == "mr"

    def test_falls_back_to_the_record_when_absent(self):
        from app.api.routes.interview import _spoken_language

        assert _spoken_language(None, self._patient("ta")) == "ta"

    def test_an_unsupported_override_is_ignored(self):
        """A junk query param must not silently drop the patient to English."""
        from app.api.routes.interview import _spoken_language

        assert _spoken_language("klingon", self._patient("kn")) == "kn"

    def test_defaults_to_english_with_nothing_set(self):
        from app.api.routes.interview import _spoken_language

        assert _spoken_language(None, self._patient("")) == "en"

    def test_next_question_honours_the_override(self, sql_client, patient_headers, seeded_patient):
        """seeded_patient registered in Hindi; ask for Tamil and get Tamil."""
        res = sql_client.get(
            f"/api/v1/interview/sessions/{seeded_patient['session_id']}"
            f"/next-question?language=ta",
            headers=patient_headers,
        )

        assert res.status_code == 200, res.text
        body = res.json()
        if body is not None:
            assert body["language"] == "ta"

    def test_session_start_honours_the_override(self, sql_client, patient_headers):
        res = sql_client.post(
            "/api/v1/interview/sessions?language=ta",
            json={"mode": "general"},
            headers=patient_headers,
        )

        assert res.status_code == 201, res.text
        question = res.json()["next_question"]
        if question is not None:
            assert question["language"] == "ta"
