"""LLM-driven conversational interview engine.

The deterministic state machine in :mod:`app.interview.dialogue` walks a fixed
question list. It is predictable and auditable, but it reads as a form being
recited: every patient gets the same wording in the same order, options that do
not fit their complaint, and no acknowledgement of what they just said. The
problem statement asks for the opposite — "adaptive questioning: dynamically
branches based on chief complaint and prior answers", driven by a "dialogue
manager constrained by a clinical history ontology".

Note the *constrained by*. This module is the conversation; the ontology is still
the authority. Concretely:

**The model chooses the wording and the order. The ontology chooses what exists.**
Every turn is given the catalogue of field ids still outstanding, together with
the exact option keys each one accepts, and told to work only within it. Anything
it returns outside that catalogue is dropped before it reaches the database.

That constraint is doing real work, not box-ticking:

*Fields the model invents go nowhere.* The summariser reads specific ids —
``hpi.site``, ``allergy.known`` — and silently ignores everything else. An
unvalidated engine that emitted ``hpi.location`` would look successful at every
layer and simply lose the answer, with no error anywhere to notice.

*Values have to be the ontology's keys, not the model's paraphrase.* The
red-flag rules match exact strings: ``hpi.associations`` must contain
``"breathlessness"``, not "shortness of breath". A plausible-sounding synonym
matches no rule, so a patient describing an evolving MI would pass through
unflagged — a failure that is invisible precisely because the transcript reads
perfectly.

*The same id means different things per complaint.* ``hpi.onset`` takes
time-ago keys under the chest-pain template, with suddenness held separately in
``hpi.onset_type``; under headache and breathlessness, ``sudden`` belongs in
``hpi.onset`` itself. Only the active template knows which is legal, which is why
the catalogue is rebuilt per turn rather than described once in a static prompt.

*It bounds the scope of the interview.* The model can only ask about fields that
are actually outstanding, so it cannot wander into what the patient ate yesterday
or start suggesting treatment. Both belong to the physician.

Red flags are **not** taken from the model. :func:`app.interview.red_flags.evaluate_red_flags`
runs over the validated fields exactly as it does for the legacy engine. A model
that forgets to populate a ``red_flag`` key must not be able to turn triage off,
so the deterministic rules stay authoritative and anything the model volunteers
is advisory only.

The legacy engine remains fully supported and is still the default: sessions
record which engine owns them, and a session cannot switch mid-flight.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.interview import languages
from app.interview.dialogue import InterviewState, get_next_question, get_progress
from app.interview.ontology import InputType, Question
from app.interview.templates import CHIEF_COMPLAINT_QUESTION
from app.services.summary.llm import main_api_is_configured, post_chat_completion

logger = logging.getLogger(__name__)

#: How many prior turns to replay to the model.
#:
#: The full transcript would keep growing for the whole interview, and audio
#: token cost on a realtime-style exchange scales with what gets resent. Twenty
#: turns is comfortably more than the SOCRATES block needs for continuity while
#: keeping the request bounded; the structured answers already carry the durable
#: record, so older turns are recoverable context rather than lost information.
MAX_HISTORY_TURNS = 20

#: Cap on a single patient utterance handed to the model, in characters.
#: A transcript this long is a stuck microphone, not an answer.
MAX_MESSAGE_CHARS = 2000


@dataclass(frozen=True)
class QuickReply:
    """One tappable chip offered alongside the model's question.

    Drawn from the ontology's own options rather than invented by the model, so
    tapping a chip always produces a value the validator will accept.
    """

    key: str
    label: str


@dataclass(frozen=True)
class ConversationTurn:
    """The result of one exchange."""

    reply: str
    """What to show and speak to the patient."""

    accepted: dict[str, Any] = field(default_factory=dict)
    """Validated ``field_id -> value``, ready to persist as interview answers."""

    rejected: list[str] = field(default_factory=list)
    """Field ids the model returned that the ontology refused. Logged, not shown
    to the patient — a rejected field means the interview simply has not
    captured that answer yet, and it will be asked again."""

    section: str = ""
    """Ontology section the conversation is currently in."""

    quick_replies: list[QuickReply] = field(default_factory=list)
    """Tappable options for the current question, empty for free text."""

    interview_complete: bool = False
    """True when every required field has been captured."""

    advisory_red_flag: str | None = None
    """Anything the model flagged of its own accord. Never authoritative — the
    deterministic rules decide what actually fires — but worth logging, because a
    model noticing something the rules do not is a gap in the rules."""


def is_available() -> bool:
    """Whether the conversational engine can run.

    Gated on the same check the summariser uses so the two cannot disagree about
    what "configured" means. Without a hosted model there is no conversation, and
    the caller must fall back to the deterministic engine.
    """
    return main_api_is_configured()


# ---------------------------------------------------------------------------
# Ontology catalogue — what the model is allowed to fill in
# ---------------------------------------------------------------------------


def outstanding_questions(state: InterviewState) -> list[Question]:
    """Questions still unanswered, in ontology order.

    Mirrors the legacy sequence so both engines agree on what a complete
    interview contains. While the chief complaint is unknown the only thing
    outstanding is the chief complaint itself: the complaint selects the HPI
    template, so nothing else can be legally described yet.
    """
    from app.interview.dialogue import get_question_sequence

    if state.chief_complaint is None:
        return [CHIEF_COMPLAINT_QUESTION]

    return [q for q in get_question_sequence(state) if q.field_id not in state.answered_field_ids]


def _describe_question(question: Question) -> str:
    """One catalogue line: the field id, how to answer it, and the legal values."""
    kind = question.input_type
    parts = [f'- "{question.field_id}" ({kind.value})']

    if kind in (InputType.SINGLE_CHOICE, InputType.MULTI_CHOICE):
        keys = ", ".join(f'"{opt.key}"' for opt in question.options)
        shape = "exactly one of" if kind is InputType.SINGLE_CHOICE else "a list of"
        parts.append(f"  value: {shape} [{keys}]")
        # The English labels tell the model what each key *means*, which is what
        # lets it map a patient saying "it feels like a heavy weight" onto
        # "crushing" rather than guessing from the key spelling alone.
        glossary = "; ".join(f"{opt.key} = {opt.label_en}" for opt in question.options)
        parts.append(f"  meaning: {glossary}")
    elif kind is InputType.YES_NO:
        parts.append("  value: true or false")
    elif kind is InputType.NUMERIC:
        parts.append("  value: a number from 1 to 10")
    elif kind is InputType.DATE:
        parts.append("  value: a date as YYYY-MM-DD")
    else:
        parts.append("  value: a short string in the patient's own words")

    parts.append(f"  asks: {question.prompt_en}")
    if not question.required:
        parts.append("  optional: may be skipped if the patient has nothing to say")

    return "\n".join(parts)


def describe_catalogue(questions: list[Question]) -> str:
    """Render the outstanding questions as the model's allowed vocabulary."""
    if not questions:
        return "(nothing outstanding — the interview is complete)"
    return "\n".join(_describe_question(q) for q in questions)


# ---------------------------------------------------------------------------
# Validation — the gate between the model and the clinical record
# ---------------------------------------------------------------------------


_TRUEISH = {"true", "yes", "y", "haan", "haa", "1", "affirmative"}
_FALSEISH = {"false", "no", "n", "nahi", "nahin", "0", "negative"}


def _coerce(question: Question, raw: Any) -> Any | None:
    """Coerce a model-supplied value to the question's declared type.

    Returns None when the value cannot be salvaged, which is treated as "not
    answered" rather than as an error: the field stays outstanding and gets asked
    again. Guessing here would put a fabricated value into a clinical record.
    """
    kind = question.input_type

    if kind is InputType.YES_NO:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUEISH:
            return True
        if text in _FALSEISH:
            return False
        return None

    if kind is InputType.NUMERIC:
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        # The ontology's only numeric field is a 1-10 severity scale, and the
        # legacy endpoint enforces the same bound. A model that returns 50
        # because the patient said "the pain is unbearable" would otherwise sail
        # past the >= 9 red-flag threshold with a value no clinician would trust.
        if not 1 <= number <= 10:
            return None
        return int(number) if number.is_integer() else number

    if kind is InputType.SINGLE_CHOICE:
        legal = {opt.key for opt in question.options}
        text = str(raw).strip()
        return text if text in legal else None

    if kind is InputType.MULTI_CHOICE:
        legal = {opt.key for opt in question.options}
        items = raw if isinstance(raw, list) else [raw]
        kept = [str(i).strip() for i in items if str(i).strip() in legal]
        # An empty list is indistinguishable from "not asked yet" downstream, so
        # it is rejected rather than stored as a positive finding of nothing.
        return kept or None

    if kind is InputType.DATE:
        text = str(raw).strip()
        return text or None

    # FREE_TEXT
    text = str(raw).strip()
    return text or None


def validate_extraction(
    raw: dict[str, Any],
    state: InterviewState,
) -> tuple[dict[str, Any], list[str]]:
    """Split a model's ``extracted_data`` into what the ontology accepts and what it does not.

    Returns ``(accepted, rejected_field_ids)``. Only outstanding questions are
    accepted: re-answering a field the patient already settled would let a later,
    vaguer turn overwrite an explicit earlier one, and ``interview_answers`` has
    no uniqueness constraint to stop the duplicate row.
    """
    if not isinstance(raw, dict):
        return {}, []

    allowed = {q.field_id: q for q in outstanding_questions(state)}
    accepted: dict[str, Any] = {}
    rejected: list[str] = []

    for field_id, value in raw.items():
        question = allowed.get(field_id)
        if question is None:
            rejected.append(field_id)
            continue

        coerced = _coerce(question, value)
        if coerced is None:
            rejected.append(field_id)
            continue

        accepted[field_id] = coerced

    return accepted, rejected


def quick_replies_for(
    question: Question | None, labels: list[str] | None = None
) -> list[QuickReply]:
    """Chips for the question the model is expected to be asking.

    Labels come from the ontology, optionally replaced by translated ones the
    caller has already resolved. Keys always come from the ontology, so a tap
    cannot produce a value the validator would reject.
    """
    if question is None or not question.options:
        return []

    if labels is not None and len(labels) == len(question.options):
        return [
            QuickReply(key=opt.key, label=label)
            for opt, label in zip(question.options, labels, strict=True)
        ]
    return [QuickReply(key=opt.key, label=opt.label_en) for opt in question.options]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """\
You are a warm, patient medical interviewer at a public hospital kiosk in India.
You are collecting a clinical history that a doctor will read before seeing the
patient. You are NOT diagnosing and NOT advising treatment.

WHO YOU ARE TALKING TO
The patient may be elderly, may not read well, and may never have used a
computer. Many are anxious. Speak the way a kind nurse would: short sentences,
everyday words, no medical jargon. Acknowledge what they said before asking the
next thing.

LANGUAGE
Write every word of "reply" in {language_name} ({language_code}), in that
language's own script. This is the only language the patient understands. Never
mix in English words unless they are the ordinary local usage for a thing.

HOW TO CONDUCT THE INTERVIEW
1. Ask about ONE thing at a time. Never stack two questions in one reply.
2. Follow the SOCRATES structure for the presenting complaint: site, onset,
   character, radiation, associations, time course, exacerbating and relieving
   factors, severity.
3. Let their answers steer you. If they mention something that matters
   clinically, follow it up before moving on.
4. Work only through the OUTSTANDING FIELDS listed below. Do not ask about
   anything else — diet, lifestyle advice, opinions on their condition, or
   anything a doctor should be asking. That is not your job here.
5. If an answer is unclear, a greeting, silence, or "I don't know", extract
   NOTHING for that field and ask again in simpler words. Never fill a field
   with a guess.
6. When every field is captured, thank them warmly and set
   "interview_complete": true.

EXTRACTING DATA
"extracted_data" maps field ids to values. Rules that are not negotiable:
- Use ONLY field ids from OUTSTANDING FIELDS. Any other id is discarded.
- Use ONLY the listed option keys as values, spelled exactly. Not a synonym, not
  a translation, not the patient's phrasing — the key itself.
- Extract only what the patient actually told you in their last message.
- Omit fields you have no answer for. An absent field is fine; a wrong one is not.

OUTPUT
Reply with JSON only, no markdown fences:
{{
  "reply": "your next question, in {language_name}",
  "extracted_data": {{"field_id": value}},
  "asking_field_id": "the field id your reply is asking about, or null",
  "interview_complete": false,
  "concern": null
}}

"concern" is for anything that worries you clinically, in one short English
phrase, or null. It does not control triage — automatic rules handle that — but
a doctor will read it.
"""


USER_TEMPLATE = """\
INTERVIEW SO FAR
Mode: {mode}
Chief complaint: {chief_complaint}
Captured so far: {captured}

OUTSTANDING FIELDS (the only ones you may fill or ask about)
{catalogue}

PATIENT'S LATEST MESSAGE
{message}
"""


def _opening_user_message(language_name: str) -> str:
    """The instruction that starts an interview, before the patient has spoken."""
    return (
        "The patient has just sat down and has not said anything yet. Greet them "
        f"warmly in {language_name} and ask what has brought them to the hospital "
        "today. Extract nothing."
    )


def build_messages(
    state: InterviewState,
    history: list[dict[str, str]],
    patient_message: str | None,
    language: str,
) -> list[dict[str, str]]:
    """Assemble the chat messages for one turn."""
    lang = languages.get(language)
    catalogue = describe_catalogue(outstanding_questions(state))

    captured = ", ".join(sorted(state.answered_field_ids)) or "nothing yet"

    if patient_message is None:
        user_content = _opening_user_message(lang.english_name)
    else:
        user_content = USER_TEMPLATE.format(
            mode=state.mode,
            chief_complaint=state.chief_complaint or "not established yet",
            captured=captured,
            catalogue=catalogue,
            message=patient_message[:MAX_MESSAGE_CHARS],
        )

    system_content = SYSTEM_PROMPT.format(
        language_name=lang.english_name,
        language_code=lang.code,
    )

    # Append AYUSH-specific instructions for ayush-mode sessions
    if state.mode == "ayush":
        from app.interview.ayurveda import AYUSH_SYSTEM_SUPPLEMENT

        system_content += "\n" + AYUSH_SYSTEM_SUPPLEMENT

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    # Recent turns first so the model can acknowledge what was just said; the
    # catalogue rides on the final user message so the constraint is the most
    # recent thing it read.
    messages.extend(history[-MAX_HISTORY_TURNS:])
    messages.append({"role": "user", "content": user_content})
    return messages


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _parse_reply(content: str) -> dict[str, Any]:
    """Parse the model's JSON turn, tolerating fences and stray prose."""
    text = content.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: the outermost brace pair. A model that prefixed "Sure!"
        # still produced a usable turn, and discarding it would stall the
        # interview on a formatting slip.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("model returned JSON that was not an object")
    return parsed


async def next_turn(
    state: InterviewState,
    history: list[dict[str, str]],
    patient_message: str | None,
    language: str = "en",
    option_labels: dict[str, list[str]] | None = None,
) -> ConversationTurn:
    """Run one exchange and return the validated result.

    Args:
        state: Current interview state, built from persisted answers.
        history: Prior turns as OpenAI-format messages.
        patient_message: What the patient just said, or None to open the
            interview with a greeting.
        language: The patient's language code — governs the reply's language.
        option_labels: Optional pre-translated chip labels, keyed by field id.

    Raises:
        Exception: Propagates transport, parse and validation failures so the
            caller can fall back to the deterministic engine. Swallowing them
            here would leave the patient staring at an empty screen.
    """
    messages = build_messages(state, history, patient_message, language)

    content = await post_chat_completion(messages, json_mode=True, temperature=0.3)
    parsed = _parse_reply(content)

    reply = str(parsed.get("reply", "")).strip()
    accepted, rejected = validate_extraction(parsed.get("extracted_data") or {}, state)

    if rejected:
        # Loud, because a persistent pattern here means the catalogue and the
        # model disagree, and the symptom is silently missing answers rather
        # than a visible failure.
        logger.warning(
            "conversation: discarded %d off-ontology field(s): %s",
            len(rejected),
            ", ".join(rejected),
        )

    # Progress and completion come from the ontology, not the model's opinion.
    # A model that declares itself finished while required fields are outstanding
    # would end the interview with holes in the record.
    projected = InterviewState(
        chief_complaint=accepted.get("chief_complaint", state.chief_complaint),
        mode=state.mode,
        answered_field_ids=state.answered_field_ids | set(accepted),
    )
    next_question = get_next_question(projected)
    complete = next_question is None

    # Chips describe whatever the model says it is asking, falling back to the
    # ontology's own next question when it does not say.
    asking_id = parsed.get("asking_field_id")
    asking = next(
        (q for q in outstanding_questions(projected) if q.field_id == asking_id),
        next_question,
    )
    labels = (option_labels or {}).get(asking.field_id) if asking else None

    concern = parsed.get("concern")

    return ConversationTurn(
        reply=reply,
        accepted=accepted,
        rejected=rejected,
        section=asking.section.value if asking else "",
        quick_replies=quick_replies_for(asking, labels),
        interview_complete=complete,
        advisory_red_flag=str(concern).strip() if concern else None,
    )


def progress_for(state: InterviewState) -> dict:
    """Progress in the same shape the legacy engine reports.

    Shared so a client does not need to care which engine is driving.
    """
    return get_progress(state)
