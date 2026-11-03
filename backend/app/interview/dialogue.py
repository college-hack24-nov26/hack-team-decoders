"""Dialogue manager — deterministic state machine driving the interview.

The state is: "which questions have been answered so far for this session."
The next question is determined by walking the template's question list and
finding the first unanswered one, then moving to base history fields, then
AYUSH fields (if mode=ayush), then ROS.

This is deliberately NOT an LLM agent. A deterministic state machine is:
- Predictable (same inputs → same questions every time)
- Auditable (you can prove exactly which questions were asked)
- Fast (no API latency for deciding the next question)
- Demo-reliable (won't hallucinate questions or skip important ones)

LLM-driven adaptive follow-ups can be layered on TOP of this later, once the
deterministic core works.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.interview.ayurveda import AYUSH_EXTENDED_FIELDS
from app.interview.ontology import (
    AYUSH_FIELDS,
    BASE_HISTORY_FIELDS,
    REVIEW_OF_SYSTEMS_FIELDS,
    Question,
)
from app.interview.templates import CHIEF_COMPLAINT_QUESTION, TEMPLATES


@dataclass
class InterviewState:
    """Snapshot of an in-progress interview, built from DB answers."""

    chief_complaint: str | None  # None if not yet answered
    mode: str  # "general" or "ayush"
    answered_field_ids: set[str]  # field_ids already answered


def get_question_sequence(state: InterviewState) -> list[Question]:
    """Return the full ordered question list for this session's state.

    The sequence is:
    1. Chief complaint (if not yet answered)
    2. HPI template questions for the selected chief complaint
    3. Base history (PMH, drugs, allergies, family, personal)
    4. AYUSH Dashavidha Pariksha (only if mode=ayush)
    5. Review of Systems
    """
    questions: list[Question] = []

    # 1. Chief complaint selection
    questions.append(CHIEF_COMPLAINT_QUESTION)

    # 2. HPI template — pick based on chief complaint
    if state.chief_complaint:
        template_key = state.chief_complaint
        if template_key == "other" or template_key not in TEMPLATES:
            template_key = "generic"
        questions.extend(TEMPLATES[template_key])

    # 3. Base history fields (PMH, drugs, allergies, family, personal)
    questions.extend(BASE_HISTORY_FIELDS)

    # 4. AYUSH fields (only in ayush mode)
    if state.mode == "ayush":
        questions.extend(AYUSH_FIELDS)
        questions.extend(AYUSH_EXTENDED_FIELDS)

    # 5. Review of Systems
    questions.extend(REVIEW_OF_SYSTEMS_FIELDS)

    return questions


def get_next_question(state: InterviewState) -> Question | None:
    """Return the next unanswered question, or None if the interview is complete.

    Skips questions whose `condition` is not met (future use — currently all
    questions in the templates are unconditional).
    """
    sequence = get_question_sequence(state)

    for question in sequence:
        if question.field_id in state.answered_field_ids:
            continue

        # If CC not yet answered, only the CC question is reachable
        if state.chief_complaint is None and question.field_id != "chief_complaint":
            continue

        # Condition check (for future use)
        if question.condition is not None:
            # TODO: evaluate condition against answered values
            pass

        return question

    return None  # Interview complete


def get_progress(state: InterviewState) -> dict:
    """Return progress info for the frontend progress bar.

    The chief-complaint question is excluded from the count, and
    ``awaiting_chief_complaint`` tells the client to hide the bar until it is
    answered. Both exist for the same reason: the chief complaint is what
    *selects* the HPI template, so the real number of remaining questions is
    unknowable until it has been answered. Counting it produced a denominator
    that jumped the moment the patient answered the first question (13 → 23 for
    chest pain, 13 → 20 for fever), and a progress total that lurches reads as
    the machine having lost the answers already given.

    Because the chief complaint is always the first and only question asked
    before the template is known, hiding the bar for exactly that one question
    means the denominator the patient actually sees never changes.
    """
    sequence = get_question_sequence(state)
    clinical = [q for q in sequence if q.field_id != "chief_complaint"]

    total = len(clinical)
    answered = sum(1 for q in clinical if q.field_id in state.answered_field_ids)
    known = state.chief_complaint is not None

    return {
        "answered": answered,
        "total": total,
        "percent": int((answered / total) * 100) if total > 0 and known else 0,
        "awaiting_chief_complaint": not known,
    }
