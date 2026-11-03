"""Red-flag rules engine — deterministic pattern matching, not LLM-dependent.

Each rule is an explicit combination of field values that constitutes a clinical
emergency or high-priority finding. Rules fire IMMEDIATELY when their conditions
are met — they don't wait for the interview to complete.

This is a checklist/rules approach on purpose:
- Deterministic: same answers always fire (or don't fire) the same flags.
- Auditable: you can explain exactly WHY a flag fired to a physician.
- Fast: no API call needed.
- Testable: unit tests can exhaustively cover every rule.

Adding a new red-flag rule: add a RedFlagRule to RULES list at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedFlagRule:
    """One red-flag pattern to watch for.

    `conditions` is a dict of field_id → expected values. The rule fires when
    ALL conditions are satisfied simultaneously.

    `value_match` can be:
    - A string: exact match
    - A list: answer must be one of these (OR)
    - A dict with "contains": answer (if list) must include this value
    - A dict with "gte" or "lte": numeric comparison
    - True: field just needs to exist with a truthy value
    """

    id: str
    name: str
    description: str
    severity: str  # "critical" | "high" | "moderate"
    conditions: dict[str, Any]


def _matches(answer_value: Any, expected: Any) -> bool:
    """Check if an answer value matches an expected condition."""
    if expected is True:
        # Field just needs to exist with a truthy value
        return bool(answer_value)

    if isinstance(expected, str):
        # Exact string match, or check if it's in a list answer
        if isinstance(answer_value, list):
            return expected in answer_value
        return str(answer_value) == expected

    if isinstance(expected, list):
        # Answer must be one of these values
        if isinstance(answer_value, list):
            return bool(set(expected) & set(answer_value))
        return answer_value in expected

    if isinstance(expected, dict):
        if "contains" in expected:
            # Answer list must contain this value
            if isinstance(answer_value, list):
                return expected["contains"] in answer_value
            return str(answer_value) == expected["contains"]
        if "gte" in expected:
            try:
                return float(answer_value) >= expected["gte"]
            except (ValueError, TypeError):
                return False
        if "lte" in expected:
            try:
                return float(answer_value) <= expected["lte"]
            except (ValueError, TypeError):
                return False

    return False


def evaluate_red_flags(
    answers: dict[str, Any],
    chief_complaint: str | None = None,
) -> list[RedFlagRule]:
    """Evaluate all rules against the current answer set. Returns fired rules.

    Called after EVERY answer submission — not just at the end. A red flag
    found after the patient has already walked back to the waiting area is a
    red flag found too late.

    Args:
        answers: dict mapping field_id → answer value (from interview_answers).
        chief_complaint: the selected chief complaint (for context-aware rules).
    """
    fired: list[RedFlagRule] = []

    for rule in RULES:
        all_match = True
        for field_id, expected in rule.conditions.items():
            # Special handling for chief_complaint which lives on the session
            if field_id == "chief_complaint":
                if not _matches(chief_complaint, expected):
                    all_match = False
                    break
                continue

            if field_id not in answers:
                all_match = False
                break

            if not _matches(answers[field_id], expected):
                all_match = False
                break

        if all_match:
            fired.append(rule)

    return fired


# ---------------------------------------------------------------------------
# RULE DEFINITIONS
# ---------------------------------------------------------------------------

RULES: list[RedFlagRule] = [
    # -- Cardiac emergency: chest pain + breathlessness --
    RedFlagRule(
        id="cardiac_chest_pain_dyspnoea",
        name="Acute chest pain with breathlessness",
        description=(
            "Central/left chest pain with associated breathlessness — "
            "possible acute coronary syndrome or pulmonary embolism. "
            "Needs immediate ECG and physician assessment."
        ),
        severity="critical",
        conditions={
            "chief_complaint": "chest_pain",
            "hpi.site": ["central", "left"],
            "hpi.associations": {"contains": "breathlessness"},
        },
    ),
    RedFlagRule(
        id="cardiac_crushing_sweating",
        name="Crushing chest pain with sweating",
        description=(
            "Crushing/pressure chest pain with diaphoresis — "
            "classic MI presentation. Immediate priority."
        ),
        severity="critical",
        conditions={
            "chief_complaint": "chest_pain",
            "hpi.character": "crushing",
            "hpi.associations": {"contains": "sweating"},
        },
    ),
    RedFlagRule(
        id="cardiac_radiation_arm_jaw",
        name="Chest pain radiating to arm/jaw",
        description=(
            "Chest pain radiating to left arm or jaw — "
            "high suspicion for acute coronary syndrome."
        ),
        severity="critical",
        conditions={
            "chief_complaint": "chest_pain",
            "hpi.radiation": {"contains": "left_arm"},
        },
    ),
    # -- Stroke symptoms --
    RedFlagRule(
        id="stroke_sudden_headache_weakness",
        name="Sudden severe headache with weakness",
        description=(
            "Thunderclap headache with limb weakness — "
            "possible stroke or subarachnoid hemorrhage. "
            "Needs immediate CT and neurological assessment."
        ),
        severity="critical",
        conditions={
            "chief_complaint": "headache",
            "hpi.onset": "sudden",
            "hpi.associations": {"contains": "weakness"},
        },
    ),
    RedFlagRule(
        id="stroke_worst_headache_neck_stiff",
        name="Worst headache ever with neck stiffness",
        description=(
            "Worst headache of life with meningismus — "
            "possible SAH or meningitis. Immediate imaging."
        ),
        severity="critical",
        conditions={
            "chief_complaint": "headache",
            "hpi.worst_headache": True,
            "hpi.associations": {"contains": "neck_stiffness"},
        },
    ),
    # -- Respiratory emergency --
    RedFlagRule(
        id="resp_acute_rest_dyspnoea",
        name="Acute breathlessness at rest",
        description=(
            "Sudden onset breathlessness even at rest — "
            "possible PE, pneumothorax, or severe asthma. "
            "Immediate assessment needed."
        ),
        severity="critical",
        conditions={
            "chief_complaint": "breathlessness",
            "hpi.onset": "sudden",
            "hpi.trigger": "rest",
        },
    ),
    RedFlagRule(
        id="resp_hemoptysis",
        name="Breathlessness with hemoptysis",
        description=(
            "Breathlessness with coughing blood — "
            "possible PE, TB, or malignancy. Priority assessment."
        ),
        severity="high",
        conditions={
            "chief_complaint": "breathlessness",
            "hpi.associations": {"contains": "hemoptysis"},
        },
    ),
    # -- Abdominal emergency --
    RedFlagRule(
        id="abd_right_lower_fever",
        name="Right lower abdominal pain with fever",
        description=(
            "Right iliac fossa pain with fever — "
            "possible appendicitis. Surgical assessment needed."
        ),
        severity="high",
        conditions={
            "chief_complaint": "abdominal_pain",
            "hpi.site": "right_lower",
            "hpi.associations": {"contains": "fever"},
        },
    ),
    RedFlagRule(
        id="abd_blood_stool",
        name="Abdominal pain with blood in stool",
        description=("Abdominal pain with GI bleeding — needs urgent evaluation."),
        severity="high",
        conditions={
            "chief_complaint": "abdominal_pain",
            "hpi.associations": {"contains": "blood_stool"},
        },
    ),
    # -- Fever emergency --
    RedFlagRule(
        id="fever_high_rash",
        name="High fever with rash",
        description=(
            "High fever with skin rash — possible meningococcemia, "
            "dengue, or other serious infection. Priority assessment."
        ),
        severity="high",
        conditions={
            "chief_complaint": "fever",
            "hpi.degree": ["high", "very_high"],
            "hpi.associations": {"contains": "rash"},
        },
    ),
    # -- Severe pain (any complaint) --
    RedFlagRule(
        id="severe_pain_9_10",
        name="Severe pain (9-10/10)",
        description=(
            "Patient reporting extreme pain (9 or 10 out of 10). "
            "Priority for pain management and assessment."
        ),
        severity="moderate",
        conditions={
            "hpi.severity": {"gte": 9},
        },
    ),
]


#: Rule lookup by id.
#:
#: ``red_flags.symptom`` in the database stores only the rule id, so a flag read
#: back from the DB has to be rehydrated through this to recover its clinical
#: name and description. Without it, `GET /red-flags` returned the raw id
#: ("cardiac_chest_pain_dyspnoea") where the UI expected a sentence, so a
#: patient who reloaded the page saw an identifier instead of the alert.
RULES_BY_ID: dict[str, RedFlagRule] = {rule.id: rule for rule in RULES}
