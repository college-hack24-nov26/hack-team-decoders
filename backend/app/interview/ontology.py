"""Clinical history ontology — the fixed set of fields the interview tries to fill.

Structured as data (not scattered hardcoded strings) so:
- Adding a new chief-complaint template is a config change, not a code rewrite.
- The dialogue manager, summary generator, and frontend can all reference the same
  canonical field IDs.
- AYUSH Dashavidha Pariksha fields are toggled by session mode, not a separate code path.

Field IDs follow a dotted namespace: `section.field` or `section.subsection.field`.
These IDs are what get stored in `interview_answers.field` in the DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InputType(str, Enum):
    """How the patient can answer this question."""

    SINGLE_CHOICE = "single_choice"  # tap one option
    MULTI_CHOICE = "multi_choice"  # tap multiple
    FREE_TEXT = "free_text"  # voice narration or typed
    YES_NO = "yes_no"  # binary
    NUMERIC = "numeric"  # e.g. pain scale 1-10
    DATE = "date"  # onset date


class Section(str, Enum):
    """Top-level sections of a clinical history."""

    CHIEF_COMPLAINT = "chief_complaint"
    HPI = "hpi"  # History of Present Illness (SOCRATES)
    PAST_MEDICAL = "past_medical"
    PAST_SURGICAL = "past_surgical"
    DRUG_HISTORY = "drug_history"
    ALLERGY = "allergy"
    FAMILY_HISTORY = "family_history"
    PERSONAL_HISTORY = "personal_history"
    REVIEW_OF_SYSTEMS = "review_of_systems"
    AYUSH = "ayush"  # Dashavidha Pariksha — only for mode=ayush


# ---------------------------------------------------------------------------
# Question definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionOption:
    """One selectable option for single/multi choice questions."""

    key: str
    label_en: str
    label_hi: str


@dataclass(frozen=True)
class Question:
    """A single question in the clinical history ontology.

    `field_id` is the canonical identifier stored in interview_answers.field.
    """

    field_id: str
    section: Section
    prompt_en: str
    prompt_hi: str
    input_type: InputType
    options: list[QuestionOption] = field(default_factory=list)
    required: bool = True
    # If set, this question is only asked when a prior answer matches a condition
    condition: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Base fields — asked in EVERY interview regardless of chief complaint
# ---------------------------------------------------------------------------

BASE_HISTORY_FIELDS: list[Question] = [
    # -- Past Medical History --
    Question(
        field_id="past_medical.conditions",
        section=Section.PAST_MEDICAL,
        prompt_en="Do you have any of these conditions?",
        prompt_hi="क्या आपको इनमें से कोई बीमारी है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("diabetes", "Diabetes", "मधुमेह (शुगर)"),
            QuestionOption("hypertension", "High blood pressure", "उच्च रक्तचाप (BP)"),
            QuestionOption("heart_disease", "Heart disease", "हृदय रोग"),
            QuestionOption("asthma", "Asthma / COPD", "दमा / COPD"),
            QuestionOption("thyroid", "Thyroid disorder", "थायराइड"),
            QuestionOption("none", "None of these", "इनमें से कोई नहीं"),
        ],
    ),
    # -- Drug History --
    Question(
        field_id="drug_history.current_meds",
        section=Section.DRUG_HISTORY,
        prompt_en="Are you currently taking any medicines? If yes, which ones?",
        prompt_hi="क्या आप अभी कोई दवाई ले रहे हैं? हाँ तो कौन सी?",
        input_type=InputType.FREE_TEXT,
        required=False,
    ),
    # -- Allergy --
    Question(
        field_id="allergy.known",
        section=Section.ALLERGY,
        prompt_en="Do you have any known drug or food allergies?",
        prompt_hi="क्या आपको किसी दवाई या खाने से एलर्जी है?",
        input_type=InputType.FREE_TEXT,
        required=False,
    ),
    # -- Family History --
    Question(
        field_id="family_history.conditions",
        section=Section.FAMILY_HISTORY,
        prompt_en="Does anyone in your family have diabetes, heart disease, or cancer?",
        prompt_hi="क्या आपके परिवार में किसी को शुगर, हृदय रोग, या कैंसर है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("diabetes", "Diabetes", "मधुमेह"),
            QuestionOption("heart_disease", "Heart disease", "हृदय रोग"),
            QuestionOption("cancer", "Cancer", "कैंसर"),
            QuestionOption("none", "None / Don't know", "कोई नहीं / पता नहीं"),
        ],
        required=False,
    ),
    # -- Personal History (combined smoking + alcohol) --
    Question(
        field_id="personal_history.habits",
        section=Section.PERSONAL_HISTORY,
        prompt_en="Do you smoke, chew tobacco, or drink alcohol?",
        prompt_hi="क्या आप धूम्रपान, तंबाकू, या शराब का सेवन करते हैं?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("smoking", "Smoke / tobacco", "धूम्रपान / तंबाकू"),
            QuestionOption("alcohol", "Alcohol", "शराब"),
            QuestionOption("none", "None of these", "इनमें से कोई नहीं"),
        ],
    ),
]


# ---------------------------------------------------------------------------
# AYUSH Dashavidha Pariksha — only asked when mode=ayush
# ---------------------------------------------------------------------------

AYUSH_FIELDS: list[Question] = [
    Question(
        field_id="ayush.prakriti",
        section=Section.AYUSH,
        prompt_en="What is your body type? (Prakriti — natural constitution)",
        prompt_hi="आपके शरीर का प्रकार क्या है? (प्रकृति — शरीर की प्राकृतिक बनावट)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("vata", "Vata — thin, dry skin, anxious", "वात — दुबला, सूखी त्वचा, चिंतित"),
            QuestionOption("pitta", "Pitta — warm body, sharp mind", "पित्त — गर्म शरीर, तेज़ दिमाग"),
            QuestionOption("kapha", "Kapha — heavy, calm, oily skin", "कफ — भारी, शांत, तैलीय त्वचा"),
            QuestionOption("vata_pitta", "Vata-Pitta mix", "वात-पित्त मिश्रित"),
            QuestionOption("pitta_kapha", "Pitta-Kapha mix", "पित्त-कफ मिश्रित"),
            QuestionOption("vata_kapha", "Vata-Kapha mix", "वात-कफ मिश्रित"),
            QuestionOption("tridosha", "Balanced (Tridosha)", "संतुलित (त्रिदोष)"),
        ],
    ),
    Question(
        field_id="ayush.vikriti",
        section=Section.AYUSH,
        prompt_en="Which energy feels most disturbed right now? (Vikriti — current imbalance)",
        prompt_hi="इस समय कौन सी ऊर्जा सबसे बिगड़ी हुई है? (विकृति — वर्तमान असंतुलन)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("vata", "Vata — gas, pain, anxiety", "वात — गैस, दर्द, चिंता"),
            QuestionOption("pitta", "Pitta — heat, acidity, anger", "पित्त — गर्मी, एसिडिटी, गुस्सा"),
            QuestionOption("kapha", "Kapha — heaviness, mucus, laziness", "कफ — भारीपन, बलगम, आलस"),
            QuestionOption("unsure", "Not sure", "पता नहीं"),
        ],
    ),
    Question(
        field_id="ayush.agni",
        section=Section.AYUSH,
        prompt_en="How is your appetite and digestion? (Agni — digestive fire)",
        prompt_hi="आपकी भूख और पाचन कैसी है? (अग्नि — पाचन शक्ति)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("sama", "Normal appetite, digests well", "सामान्य भूख, अच्छा पचता है"),
            QuestionOption(
                "vishama",
                "Irregular — sometimes hungry, sometimes not",
                "अनियमित — कभी भूख, कभी नहीं",
            ),
            QuestionOption("tikshna", "Always hungry, eats a lot", "हमेशा भूख, बहुत खाता हूँ"),
            QuestionOption(
                "manda", "Low appetite, feels heavy after eating", "कम भूख, खाने के बाद भारी लगता है"
            ),
        ],
    ),
    Question(
        field_id="ayush.sattva",
        section=Section.AYUSH,
        prompt_en="How do you handle stress and worry? (Sattva — mental strength)",
        prompt_hi="आप तनाव और चिंता को कैसे सहते हैं? (सत्त्व — मानसिक शक्ति)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("pravara", "Strong — handle stress well", "अच्छी — तनाव सह लेता हूँ"),
            QuestionOption("madhya", "Moderate — sometimes stressed", "मध्यम — कभी-कभी तनाव होता है"),
            QuestionOption("avara", "Weak — get anxious easily", "कम — जल्दी घबरा जाता हूँ"),
        ],
    ),
    Question(
        field_id="ayush.ahara_shakti",
        section=Section.AYUSH,
        prompt_en="How much food can you eat and digest comfortably? (Ahara Shakti — eating capacity)",
        prompt_hi="आप आराम से कितना खाना खा और पचा सकते हैं? (आहार शक्ति — खाने की क्षमता)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("pravara", "Large meals, digest easily", "ज़्यादा खाता हूँ, पच जाता है"),
            QuestionOption("madhya", "Moderate amount", "मध्यम मात्रा"),
            QuestionOption("avara", "Small meals, feel heavy", "कम खाता हूँ, भारी लगता है"),
        ],
    ),
    Question(
        field_id="ayush.ahara_vihara",
        section=Section.AYUSH,
        prompt_en="Describe your daily diet, sleep, and routine briefly. (Ahara-Vihara — diet, sleep & lifestyle)",
        prompt_hi="अपना रोज़ का खानपान, नींद और दिनचर्या बताइए। (आहार-विहार — खानपान, नींद और जीवनशैली)",
        input_type=InputType.FREE_TEXT,
    ),
]


# ---------------------------------------------------------------------------
# Review of Systems — brief screening at the end
# ---------------------------------------------------------------------------

REVIEW_OF_SYSTEMS_FIELDS: list[Question] = [
    Question(
        field_id="ros.constitutional",
        section=Section.REVIEW_OF_SYSTEMS,
        prompt_en="Have you had fever, weight loss, or night sweats recently?",
        prompt_hi="क्या आपको हाल ही में बुखार, वजन कम होना, या रात को पसीना आता है?",
        input_type=InputType.YES_NO,
    ),
    Question(
        field_id="ros.cardiovascular",
        section=Section.REVIEW_OF_SYSTEMS,
        prompt_en="Any chest pain, palpitations, or swelling in legs?",
        prompt_hi="क्या सीने में दर्द, धड़कन तेज़ होना, या पैरों में सूजन है?",
        input_type=InputType.YES_NO,
    ),
    Question(
        field_id="ros.gastrointestinal",
        section=Section.REVIEW_OF_SYSTEMS,
        prompt_en="Any nausea, vomiting, abdominal pain, or change in bowel habits?",
        prompt_hi="क्या जी मिचलाना, उल्टी, पेट दर्द, या पेट ख़राब है?",
        input_type=InputType.YES_NO,
    ),
]
