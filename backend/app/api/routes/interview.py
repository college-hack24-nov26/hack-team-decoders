"""Interview API routes — Module A endpoints.

All endpoints require valid consent (ConsentedPatient dependency from Phase 1).
The interview scope is checked specifically via require_consent_scope("interview").
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import DbSession, require_consent_scope
from app.interview import conversation, languages, tts
from app.interview.asr import TranscriptResult, transcribe_audio
from app.interview.dialogue import (
    InterviewState,
    get_next_question,
    get_progress,
    get_question_sequence,
)
from app.interview.ontology import InputType, Question
from app.interview.red_flags import RULES_BY_ID, evaluate_red_flags
from app.models.models import (
    InterviewAnswer,
    InterviewMessage,
    InterviewSession,
    Patient,
    RedFlag,
    Visit,
)
from app.services.audit import log_action
from app.services.translation import translate_many_from_english

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interview", tags=["Interview"])

# Consent scope dependency — all interview endpoints require "interview" scope.
# Applied per-route rather than at router level so the requirement is visible at
# every call site.
InterviewPatient = Annotated[Patient, Depends(require_consent_scope("interview"))]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    mode: str = Field(default="general", pattern="^(general|ayush)$")
    chief_complaint: str | None = None  # can be set later via first answer
    engine: str = Field(default="legacy", pattern="^(legacy|conversation)$")
    """Which interview engine drives the session.

    Defaults to ``legacy`` so existing clients keep the question-by-question
    flow they were written against. The chat UI opts in explicitly by sending
    ``conversation``; flipping this default is a one-line change once that UI
    ships. Requesting ``conversation`` without a hosted model configured is
    downgraded rather than refused — see `start_session`.
    """


class AnswerRequest(BaseModel):
    field_id: str
    value: Any = None  # string, list, number, bool depending on question type
    input_mode: str = Field(default="touch", pattern="^(voice|touch)$")
    raw_transcript: str | None = None
    skipped: bool = False
    """Set when the patient declines an optional question. Recorded as an
    explicit skip rather than as a value, because storing the string "skipped"
    in a clinical field makes "skipped" look like the patient's answer."""


class QuestionResponse(BaseModel):
    field_id: str
    section: str
    prompt_en: str
    prompt_hi: str
    #: The prompt already resolved into the patient's language. Prefer this over
    #: prompt_en/prompt_hi, which only cover two of the 23 languages supported.
    prompt: str = ""
    #: Language `prompt` and the option `label`s are actually in.
    language: str = "en"
    input_type: str
    options: list[dict[str, str]]
    required: bool
    audio_url: str | None = None


class ProgressResponse(BaseModel):
    answered: int
    total: int
    percent: int
    awaiting_chief_complaint: bool = False
    """True until the chief complaint is answered, while the real total is still
    unknown. Clients should hide the progress bar rather than show a number that
    is about to change. See `dialogue.get_progress`."""


class SessionResponse(BaseModel):
    session_id: str
    status: str
    mode: str
    chief_complaint: str | None
    progress: ProgressResponse
    next_question: QuestionResponse | None
    engine: str = "legacy"
    """The engine actually in force, which may differ from what was requested if
    no hosted model is configured. Clients should branch on this, not on what
    they asked for."""
    opening_message: str | None = None
    """The agent's greeting, present only for a conversational session. Saves the
    client an immediate follow-up call just to get the first thing said."""
    quick_replies: list[dict[str, str]] = []
    """Tappable chips for the opening turn, each ``{"key", "label"}``."""
    audio_url: str | None = None
    """Spoken form of ``opening_message``, when TTS is available."""


class RedFlagResponse(BaseModel):
    id: str
    name: str
    description: str
    severity: str
    triggered_at: str


class AnswerResultResponse(BaseModel):
    accepted: bool
    red_flags_fired: list[RedFlagResponse]
    next_question: QuestionResponse | None
    progress: ProgressResponse
    interview_complete: bool


class MessageRequest(BaseModel):
    """One patient turn in a conversational interview."""

    message: str = Field(min_length=1, max_length=conversation.MAX_MESSAGE_CHARS)
    input_mode: str = Field(default="touch", pattern="^(voice|touch)$")


class MessageResponse(BaseModel):
    reply: str
    """The agent's next question, already in the patient's language."""
    audio_url: str | None = None
    quick_replies: list[dict[str, str]] = []
    section: str = ""
    captured: dict[str, Any] = {}
    """Fields accepted from this turn. Surfaced so the UI can show the patient
    what was understood, and so a reviewer can tie a field to an utterance."""
    red_flags_fired: list[RedFlagResponse] = []
    progress: ProgressResponse
    interview_complete: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_state(session: InterviewSession, db: Session) -> InterviewState:
    """Build an InterviewState from the DB session + its answers."""
    answers = db.query(InterviewAnswer).filter(InterviewAnswer.session_id == session.id).all()
    answered_ids = {a.field for a in answers}
    return InterviewState(
        chief_complaint=session.chief_complaint,
        mode=session.mode,
        answered_field_ids=answered_ids,
    )


async def _question_to_response(q: Question, language: str = "en") -> QuestionResponse:
    """Convert ontology Question to API response, synthesising the audio prompt.

    The prompt is spoken in the patient's own language, so which of the two
    prompt strings gets synthesised depends on ``language``.
    """
    code = languages.get(language).code

    # Hindi and English are authored by hand. Every other language is translated
    # from the English source: without this the ontology fell back to English, so
    # a patient who chose Kannada was asked — and read aloud — English questions,
    # which defeats the point of accepting Kannada at all.
    if code == "hi":
        prompt = q.prompt_hi
        labels = [opt.label_hi for opt in q.options]
    elif code == "en":
        prompt = q.prompt_en
        labels = [opt.label_en for opt in q.options]
    else:
        # One concurrent batch: prompt first, then the option labels in order.
        source = [q.prompt_en, *(opt.label_en for opt in q.options)]
        rendered = await translate_many_from_english(source, code)
        # Fall back per string, so a partial failure degrades one label rather
        # than dropping the whole question back to English.
        prompt = rendered[0] or q.prompt_en
        labels = [
            translated or opt.label_en
            for translated, opt in zip(rendered[1:], q.options, strict=True)
        ]

    clip = await tts.synthesize(prompt, code)

    return QuestionResponse(
        field_id=q.field_id,
        section=q.section.value,
        prompt_en=q.prompt_en,
        prompt_hi=q.prompt_hi,
        # Already resolved for the patient's language, so the frontend does not
        # need to know which of the 23 it is or how to pick.
        prompt=prompt,
        language=code,
        input_type=q.input_type.value,
        options=[
            {
                "key": opt.key,
                "label_en": opt.label_en,
                "label_hi": opt.label_hi,
                "label": label,
            }
            for opt, label in zip(q.options, labels, strict=True)
        ],
        required=q.required,
        audio_url=f"/api/v1/interview/audio/{clip}" if clip else None,
    )


def _get_answers_dict(session_id: uuid.UUID, db: Session) -> dict[str, Any]:
    """Get all answers for a session as a flat dict of field_id → value.

    The DB stores values as {"answer": <actual_value>} for simple types.
    This unwraps them so the red-flag engine sees clean values.
    """
    answers = db.query(InterviewAnswer).filter(InterviewAnswer.session_id == session_id).all()
    result: dict[str, Any] = {}
    for a in answers:
        val = a.value
        # Unwrap the {"answer": ...} wrapper we add for simple values
        if isinstance(val, dict) and "answer" in val and len(val) == 1:
            val = val["answer"]
        result[a.field] = val
    return result


def _check_and_fire_red_flags(
    session: InterviewSession,
    db: Session,
) -> list[RedFlagResponse]:
    """Evaluate red-flag rules and persist any new ones. Returns newly fired."""
    answers = _get_answers_dict(session.id, db)
    fired_rules = evaluate_red_flags(answers, chief_complaint=session.chief_complaint)

    if not fired_rules:
        return []

    # Check which rules already fired for this session (don't double-fire)
    existing_flags = db.query(RedFlag).filter(RedFlag.session_id == session.id).all()
    existing_ids = {f.symptom for f in existing_flags}

    new_flags: list[RedFlagResponse] = []
    now = datetime.now(tz=UTC)

    for rule in fired_rules:
        if rule.id in existing_ids:
            continue  # Already fired

        flag = RedFlag(
            id=uuid.uuid4(),
            session_id=session.id,
            symptom=rule.id,
            severity=rule.severity,
            triggered_at=now,
            triage_notified=False,
        )
        db.add(flag)

        new_flags.append(
            RedFlagResponse(
                id=rule.id,
                name=rule.name,
                description=rule.description,
                severity=rule.severity,
                triggered_at=now.isoformat(),
            )
        )

    if new_flags:
        # Update session status
        session.status = "red_flagged"

        # Audit: critical clinical event (DPDP + patient safety)
        log_action(
            db,
            action="interview.red_flag_fired",
            resource=f"interview_sessions/{session.id}",
            patient_id=session.patient_id,
            detail={
                "flags": [{"id": f.id, "severity": f.severity} for f in new_flags],
            },
        )

        db.commit()

    return new_flags


# ---------------------------------------------------------------------------
# Conversational engine helpers
# ---------------------------------------------------------------------------


def _load_history(session_id: uuid.UUID, db: Session) -> list[dict[str, str]]:
    """Replay the conversation as OpenAI-format chat messages.

    ``patient`` maps to ``user`` and ``assistant`` stays ``assistant``, so the
    model sees the exchange in the shape it was trained on.
    """
    messages = (
        db.query(InterviewMessage)
        .filter(InterviewMessage.session_id == session_id)
        .order_by(InterviewMessage.created_at)
        .all()
    )
    return [
        {"role": "assistant" if m.role == "assistant" else "user", "content": m.content}
        for m in messages
    ]


def _persist_turn(
    session: InterviewSession,
    *,
    role: str,
    content: str,
    db: Session,
    extracted: dict[str, Any] | None = None,
    input_mode: str = "touch",
) -> None:
    """Append one turn to the conversation log. Does not commit."""
    db.add(
        InterviewMessage(
            id=uuid.uuid4(),
            session_id=session.id,
            role=role,
            content=content,
            extracted_data=extracted or None,
            input_mode=input_mode,
        )
    )


def _persist_extracted(
    session: InterviewSession,
    accepted: dict[str, Any],
    input_mode: str,
    db: Session,
) -> None:
    """Write validated conversational fields as ordinary interview answers.

    This is what keeps the conversational engine compatible with everything
    downstream. The summariser, the FHIR bundle and the physician dashboard all
    read ``interview_answers``; none of them know or care that a conversation
    produced these rows. Values use the same ``{"answer": ...}`` envelope the
    legacy endpoint writes, because that is precisely what
    ``RetrievedContext.answers_by_field`` knows how to unwrap.

    Does not commit — the caller batches this with the transcript and the audit
    entry so a turn lands atomically or not at all.
    """
    for field_id, value in accepted.items():
        if field_id == "chief_complaint":
            session.chief_complaint = str(value)

        db.add(
            InterviewAnswer(
                id=uuid.uuid4(),
                session_id=session.id,
                field=field_id,
                value={"answer": value},
                # The patient's exact words are in interview_messages; repeating
                # the whole utterance on every field it produced would store the
                # same paragraph five times.
                raw_transcript=None,
                input_mode=input_mode,
            )
        )


async def _speak(text: str, language: str) -> str | None:
    """Synthesise a reply, returning an audio URL or None.

    Never raises: a TTS outage should cost the patient the audio, not the turn.
    """
    if not text.strip():
        return None
    clip = await tts.synthesize(text, language)
    return f"/api/v1/interview/audio/{clip}" if clip else None


async def _option_labels_for(state: InterviewState, language: str) -> dict[str, list[str]]:
    """Translated chip labels for the question most likely to be asked next.

    Only the next question is translated, not the whole outstanding catalogue: a
    full translation pass per turn would add a request per remaining question for
    labels the patient will not see this turn.
    """
    code = languages.get(language).code
    question = get_next_question(state)
    if question is None or not question.options:
        return {}

    if code == "hi":
        return {question.field_id: [opt.label_hi for opt in question.options]}
    if code == "en":
        return {question.field_id: [opt.label_en for opt in question.options]}

    rendered = await translate_many_from_english([opt.label_en for opt in question.options], code)
    return {
        question.field_id: [
            translated or opt.label_en
            for translated, opt in zip(rendered, question.options, strict=True)
        ]
    }


def _spoken_language(requested: str | None, patient: Patient) -> str:
    """The language this request should be answered in.

    An explicit ``?language=`` wins over the patient record, because the record
    is a snapshot from registration and the header dropdown can change the choice
    at any point afterwards. Without the override, a patient who registered in
    English and then switched to Marathi got a Marathi screen — the interface
    strings are bundled client-side — narrated and questioned in English, because
    only the server-side half was still reading the stale value.

    Mirrors what ``consent.py`` and the ASR route already do; these endpoints were
    simply missed.
    """
    if requested and languages.is_supported(requested):
        return requested
    return patient.preferred_language or "en"


def _get_session_or_404(session_id: str, patient: Patient, db: Session) -> InterviewSession:
    """Fetch a session the patient owns, or 404.

    Ownership is a filter rather than a dependency so a mistyped or guessed id is
    indistinguishable from someone else's session — both are 404, neither
    confirms the row exists.
    """
    try:
        parsed = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found") from None

    session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == parsed,
            InterviewSession.patient_id == patient.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def start_session(
    body: StartSessionRequest,
    patient: InterviewPatient,
    db: DbSession,
    language: str | None = None,
):
    """Start a new interview session.

    ``engine="conversation"`` asks for the LLM-driven agent. If no hosted model
    is configured the session is silently created as ``legacy`` instead, and the
    response says so. Refusing outright would make a missing API key look like a
    broken kiosk, when the deterministic interview is a perfectly good fallback.
    """
    engine = body.engine
    if engine == "conversation" and not conversation.is_available():
        logger.info(
            "interview: conversation engine requested but no hosted model is "
            "configured; falling back to the deterministic engine"
        )
        engine = "legacy"

    session = InterviewSession(
        id=uuid.uuid4(),
        patient_id=patient.id,
        mode=body.mode,
        chief_complaint=body.chief_complaint,
        engine=engine,
        status="in_progress",
    )
    db.add(session)
    db.flush()

    # Audit BEFORE commit so the entry lands in the same transaction as the
    # action. log_action only flushes; anything flushed after the final commit
    # is discarded when get_db closes the session.
    log_action(
        db,
        action="interview.session_started",
        resource=f"interview_sessions/{session.id}",
        patient_id=patient.id,
        detail={"mode": body.mode, "engine": engine},
    )

    db.commit()
    db.refresh(session)

    state = _build_state(session, db)
    progress = get_progress(state)
    lang = _spoken_language(language, patient)

    if session.engine == "conversation":
        opening, audio_url, chips = await _open_conversation(session, state, lang, db)
        if opening is not None:
            return SessionResponse(
                session_id=str(session.id),
                status=session.status,
                mode=session.mode,
                chief_complaint=session.chief_complaint,
                progress=ProgressResponse(**progress),
                next_question=None,
                engine="conversation",
                opening_message=opening,
                quick_replies=chips,
                audio_url=audio_url,
            )
        # The greeting failed. Downgrade the session rather than hand back an
        # empty chat window: the patient can still be interviewed by the
        # deterministic engine, which needs no network at all to pick a question.
        session.engine = "legacy"
        db.commit()
        db.refresh(session)

    next_q = get_next_question(state)
    return SessionResponse(
        session_id=str(session.id),
        status=session.status,
        mode=session.mode,
        chief_complaint=session.chief_complaint,
        progress=ProgressResponse(**progress),
        next_question=await _question_to_response(next_q, lang) if next_q else None,
        engine=session.engine,
    )


async def _open_conversation(
    session: InterviewSession,
    state: InterviewState,
    language: str,
    db: Session,
) -> tuple[str | None, str | None, list[dict[str, str]]]:
    """Produce the agent's greeting. Returns (reply, audio_url, chips).

    ``reply`` is None when the model could not be reached, which the caller
    treats as "use the deterministic engine instead".
    """
    try:
        labels = await _option_labels_for(state, language)
        turn = await conversation.next_turn(
            state=state,
            history=[],
            patient_message=None,
            language=language,
            option_labels=labels,
        )
    except Exception:
        logger.warning("interview: conversational greeting failed", exc_info=True)
        return None, None, []

    _persist_turn(session, role="assistant", content=turn.reply, db=db)
    db.commit()

    return (
        turn.reply,
        await _speak(turn.reply, language),
        [{"key": c.key, "label": c.label} for c in turn.quick_replies],
    )


@router.post("/sessions/{session_id}/message", response_model=MessageResponse)
async def send_message(
    session_id: str,
    body: MessageRequest,
    patient: InterviewPatient,
    db: DbSession,
    language: str | None = None,
):
    """Send one patient turn to the conversational agent.

    The agent decides the wording and the order of what to ask next; the ontology
    decides what can be recorded. Anything the model returns outside the
    outstanding-field catalogue is discarded before it reaches the database — see
    :mod:`app.interview.conversation` for why that matters more than it sounds.

    Red flags are evaluated by the same deterministic rules the legacy engine
    uses, over the validated fields, after every turn. The model's own opinion is
    logged but cannot fire or suppress a flag.
    """
    session = _get_session_or_404(session_id, patient, db)

    if session.engine != "conversation":
        raise HTTPException(
            status_code=409,
            detail=(
                "This session is running the deterministic engine. Use "
                "/answer, or start a new session with engine='conversation'."
            ),
        )
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed")

    lang = _spoken_language(language, patient)
    state = _build_state(session, db)

    try:
        turn = await conversation.next_turn(
            state=state,
            history=_load_history(session.id, db),
            patient_message=body.message,
            language=lang,
            option_labels=await _option_labels_for(state, lang),
        )
    except Exception as exc:
        # 503 rather than 500: the request was fine, the upstream model was not,
        # and the client's correct response is to retry or switch to the
        # deterministic flow rather than to change what it sent.
        logger.warning("interview: conversational turn failed", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="The interview assistant is temporarily unavailable. Please try again.",
        ) from exc

    # One transaction for the whole turn: the patient's words, the fields they
    # produced, the agent's reply, and the audit entry. A partial commit here
    # would leave a clinical answer with no utterance explaining it.
    _persist_turn(
        session,
        role="patient",
        content=body.message,
        db=db,
        extracted=turn.accepted or None,
        input_mode=body.input_mode,
    )
    _persist_extracted(session, turn.accepted, body.input_mode, db)
    _persist_turn(session, role="assistant", content=turn.reply, db=db)

    log_action(
        db,
        action="interview.message_exchanged",
        resource=f"interview_sessions/{session.id}",
        patient_id=patient.id,
        detail={
            "input_mode": body.input_mode,
            "fields_captured": sorted(turn.accepted),
            "fields_rejected": turn.rejected,
            "model_concern": turn.advisory_red_flag,
        },
    )
    db.commit()

    new_flags = _check_and_fire_red_flags(session, db)

    fresh = _build_state(session, db)
    progress = get_progress(fresh)

    return MessageResponse(
        reply=turn.reply,
        audio_url=await _speak(turn.reply, lang),
        quick_replies=[{"key": c.key, "label": c.label} for c in turn.quick_replies],
        section=turn.section,
        captured=turn.accepted,
        red_flags_fired=new_flags,
        progress=ProgressResponse(**progress),
        interview_complete=get_next_question(fresh) is None,
    )


@router.get("/sessions/{session_id}/next-question", response_model=QuestionResponse | None)
async def get_next(
    session_id: str,
    patient: InterviewPatient,
    db: DbSession,
    language: str | None = None,
):
    """Get the next adaptive question for this session."""
    session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == uuid.UUID(session_id),
            InterviewSession.patient_id == patient.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    state = _build_state(session, db)
    next_q = get_next_question(state)

    if next_q is None:
        return None

    return await _question_to_response(next_q, _spoken_language(language, patient))


@router.post("/sessions/{session_id}/answer", response_model=AnswerResultResponse)
async def submit_answer(
    session_id: str,
    body: AnswerRequest,
    patient: InterviewPatient,
    db: DbSession,
    language: str | None = None,
):
    """Submit an answer (voice transcript or touch selection).

    Red-flag rules are evaluated AFTER EVERY ANSWER — not at the end.
    """
    session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == uuid.UUID(session_id),
            InterviewSession.patient_id == patient.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed")

    # Locate the question being answered so the payload can be validated against
    # its declared input type. Without this the API trusts whatever the client
    # sends, and the 1-10 range enforced by the on-screen buttons would be the
    # only thing standing between a typo and a severity of 400.
    pending = get_next_question(_build_state(session, db))
    question = pending if pending and pending.field_id == body.field_id else None

    if question and question.required and body.skipped:
        raise HTTPException(
            status_code=400,
            detail=f"Question '{body.field_id}' is required and cannot be skipped",
        )

    if question and not body.skipped and question.input_type is InputType.NUMERIC:
        try:
            numeric = float(body.value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"Question '{body.field_id}' expects a number",
            ) from None
        if not 1 <= numeric <= 10:
            raise HTTPException(
                status_code=400,
                detail=f"Question '{body.field_id}' expects a number from 1 to 10",
            )

    # If this is the chief complaint answer, update the session
    if body.field_id == "chief_complaint" and not body.skipped:
        cc_value = body.value if isinstance(body.value, str) else str(body.value)
        session.chief_complaint = cc_value
        db.flush()

    # Store the answer
    if body.skipped:
        stored: dict[str, Any] = {"skipped": True}
    elif isinstance(body.value, dict):
        stored = body.value
    else:
        stored = {"answer": body.value}

    answer = InterviewAnswer(
        id=uuid.uuid4(),
        session_id=session.id,
        field=body.field_id,
        value=stored,
        raw_transcript=body.raw_transcript,
        input_mode=body.input_mode,
    )
    db.add(answer)

    # Audit: answer submission (processes patient health data — DPDP compliance).
    # Logged before the commit so both rows persist atomically.
    log_action(
        db,
        action="interview.answer_submitted",
        resource=f"interview_sessions/{session.id}",
        patient_id=patient.id,
        detail={"field_id": body.field_id, "input_mode": body.input_mode, "skipped": body.skipped},
    )

    db.commit()

    # Evaluate red flags (after EVERY answer)
    new_flags = _check_and_fire_red_flags(session, db)

    # Get next question
    state = _build_state(session, db)
    next_q = get_next_question(state)
    progress = get_progress(state)
    interview_complete = next_q is None

    lang = _spoken_language(language, patient)

    return AnswerResultResponse(
        accepted=True,
        red_flags_fired=new_flags,
        next_question=await _question_to_response(next_q, lang) if next_q else None,
        progress=ProgressResponse(**progress),
        interview_complete=interview_complete,
    )


@router.post("/sessions/{session_id}/complete")
def complete_session(
    session_id: str,
    patient: InterviewPatient,
    db: DbSession,
):
    """Mark the interview session as complete."""
    session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == uuid.UUID(session_id),
            InterviewSession.patient_id == patient.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    now = datetime.now(tz=UTC)
    # Keep red_flagged status if it was already set
    if session.status != "red_flagged":
        session.status = "completed"
    session.completed_at = now

    # Tie the interview to the visit booked on the doctor-selection screen, so the
    # dashboard can show which doctor and department the patient is waiting for.
    # The most recent visit still without an interview is the one this session
    # belongs to; nothing is linked if the patient skipped doctor selection.
    visit = (
        db.query(Visit)
        .filter(Visit.patient_id == patient.id, Visit.interview_session_id.is_(None))
        .order_by(Visit.created_at.desc())
        .first()
    )
    if visit is not None:
        visit.interview_session_id = session.id
        visit.chief_complaint = visit.chief_complaint or session.chief_complaint
        visit.status = "summary_ready" if visit.summary_id else "waiting"

    log_action(
        db,
        action="interview.session_completed",
        resource=f"interview_sessions/{session.id}",
        patient_id=patient.id,
        detail={"status": session.status},
    )

    db.commit()

    return {
        "session_id": str(session.id),
        "status": session.status,
        "completed_at": now.isoformat(),
    }


@router.get("/sessions/{session_id}/red-flags", response_model=list[RedFlagResponse])
def get_red_flags(
    session_id: str,
    patient: InterviewPatient,
    db: DbSession,
):
    """List any red flags triggered during this session."""
    session = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.id == uuid.UUID(session_id),
            InterviewSession.patient_id == patient.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    flags = db.query(RedFlag).filter(RedFlag.session_id == session.id).all()

    responses: list[RedFlagResponse] = []
    for f in flags:
        # `symptom` holds the rule id; rehydrate the clinical wording from the
        # rule set so this endpoint returns the same thing the answer endpoint
        # did. Returning the bare id here meant a patient who reloaded the page
        # saw "cardiac_chest_pain_dyspnoea" where a sentence belonged.
        rule = RULES_BY_ID.get(f.symptom)
        responses.append(
            RedFlagResponse(
                id=f.symptom,
                name=rule.name if rule else f.symptom,
                description=rule.description if rule else "",
                severity=f.severity,
                triggered_at=f.triggered_at.isoformat() if f.triggered_at else "",
            )
        )
    return responses


class ReviewItem(BaseModel):
    field_id: str
    section: str
    question: str
    answer: str
    skipped: bool = False


class ReviewResponse(BaseModel):
    session_id: str
    status: str
    mode: str
    chief_complaint: str | None
    language: str
    items: list[ReviewItem]


def _answer_text(question: Question | None, value: Any, code: str) -> str:
    """Render a stored answer the way the patient chose it: option labels, not keys."""
    labels: dict[str, str] = {}
    if question is not None:
        for opt in question.options:
            labels[opt.key] = opt.label_hi if code == "hi" else opt.label_en
    if isinstance(value, bool):
        if code == "hi":
            return "हाँ" if value else "नहीं"
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(labels.get(str(v), str(v)) for v in value)
    if question is not None and question.input_type is InputType.NUMERIC:
        return f"{value} / 10"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return labels.get(str(value), str(value))


@router.get("/sessions/{session_id}/review", response_model=ReviewResponse)
async def review_session(
    session_id: str,
    patient: InterviewPatient,
    db: DbSession,
    language: str | None = None,
):
    """The patient's own answers, question by question, for the review screen.

    Patient-authenticated and owner-only. The physician summary routes are
    physician-only, so without this the patient's review screen had nothing real
    to show and fell back to placeholder text.
    """
    session = _get_session_or_404(session_id, patient, db)
    code = languages.get(_spoken_language(language, patient)).code

    sequence = get_question_sequence(_build_state(session, db))
    order = {q.field_id: i for i, q in enumerate(sequence)}
    by_id = {q.field_id: q for q in sequence}

    answers = db.query(InterviewAnswer).filter(InterviewAnswer.session_id == session.id).all()
    answers.sort(key=lambda a: order.get(a.field, len(order)))

    items: list[ReviewItem] = []
    for a in answers:
        q = by_id.get(a.field)
        stored = a.value if isinstance(a.value, dict) else {"answer": a.value}
        skipped = bool(stored.get("skipped"))
        value = stored.get("answer", stored)
        if q is not None:
            prompt = q.prompt_hi if code == "hi" else q.prompt_en
            section = q.section.value
        else:
            prompt = a.field.split(".")[-1].replace("_", " ").capitalize()
            section = a.field.split(".")[0] if "." in a.field else "other"
        items.append(
            ReviewItem(
                field_id=a.field,
                section=section,
                question=prompt,
                answer="" if skipped else _answer_text(q, value, code),
                skipped=skipped,
            )
        )

    # Hindi and English are hand-authored; other languages are machine-translated
    # when a translation provider is configured, and stay English otherwise.
    if code not in ("en", "hi") and items:
        source = [s for item in items for s in (item.question, item.answer)]
        rendered = await translate_many_from_english(source, code)
        for i, item in enumerate(items):
            item.question = rendered[2 * i] or item.question
            item.answer = rendered[2 * i + 1] or item.answer

    return ReviewResponse(
        session_id=str(session.id),
        status=session.status,
        mode=session.mode,
        chief_complaint=session.chief_complaint,
        language=code,
        items=items,
    )


@router.post("/asr")
async def transcribe(
    patient: InterviewPatient,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    language: str | None = None,
):
    """Upload audio, get back a transcript. Proxies the configured ASR provider.

    Consent-gated like every other route in this module. It was briefly left
    open on the reasoning that transcription is a stateless utility, which was
    wrong twice over: the audio is the patient's voice describing their
    symptoms, so processing it is exactly the kind of operation consent covers,
    and an unauthenticated endpoint that forwards to a paid ASR provider is
    someone else's bill waiting to happen.
    """
    result: TranscriptResult = await transcribe_audio(
        audio_file=file.file,
        filename=file.filename or "audio.webm",
        language=language or patient.preferred_language or "en",
    )

    # Audit: AI call processing patient voice (PII — DPDP compliance)
    log_action(
        db,
        action="interview.asr_transcribed",
        resource=f"patient:{patient.id}",
        patient_id=patient.id,
        detail={"language": result.language, "is_mock": result.is_mock},
    )
    db.commit()

    return {
        "text": result.text,
        "language": result.language,
        "confidence": result.confidence,
        "is_mock": result.is_mock,
    }


@router.get("/audio/{filename}")
def get_audio_prompt(filename: str, patient: InterviewPatient):
    """Serve a cached TTS clip for a question prompt.

    Consent-gated for consistency with the rest of the module. The clips
    themselves contain no patient data — they are synthesised from the fixed
    question ontology — but there is no reason to hand out an open file route
    when every caller is already authenticated.

    `tts.cached_path` rejects any name that resolves outside the cache
    directory, so a crafted `filename` cannot walk the filesystem.
    """
    path = tts.cached_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio prompt not found")

    return FileResponse(
        path,
        media_type=tts.media_type_for(filename),
        headers={"Cache-Control": "public, max-age=86400"},
    )
