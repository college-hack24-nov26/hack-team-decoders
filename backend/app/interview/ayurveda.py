"""Ayurvedic clinical interview protocol — traditional AYUSH examination framework.

Covers the key patient-reportable assessments from classical Ayurvedic texts:
- Dashavidha Pariksha (10-fold) — trimmed to the 8 most clinically relevant
- Ashtavidha Pariksha (8-fold) — patient-reportable subset (3 questions)
- Nidana (causation) + Upashaya (relief)
- Ahara-Vihara (diet & lifestyle) — condensed

All Ayurvedic terms include their plain-language meaning in brackets so the
patient understands what is being asked.
"""

from __future__ import annotations

from app.interview.ontology import InputType, Question, QuestionOption, Section

# ---------------------------------------------------------------------------
# Ashtavidha Pariksha — 8-fold examination (patient-reportable subset)
# Nadi/Sparsha/Drik require physician. Kept: Mutra, Mala, Jihva.
# ---------------------------------------------------------------------------

ASHTAVIDHA_FIELDS: list[Question] = [
    Question(
        field_id="ayush.ashtavidha.mutra",
        section=Section.AYUSH,
        prompt_en="How is your urine? (Mutra Pariksha — urine examination)",
        prompt_hi="आपका पेशाब कैसा है? (मूत्र परीक्षा — पेशाब की जाँच)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("normal", "Normal colour, no burning", "सामान्य रंग, जलन नहीं"),
            QuestionOption("dark", "Dark / concentrated", "गाढ़ा / गहरा रंग"),
            QuestionOption("burning", "Burning sensation", "जलन होती है"),
            QuestionOption("frequent", "Frequent urination", "बार-बार पेशाब"),
        ],
    ),
    Question(
        field_id="ayush.ashtavidha.mala",
        section=Section.AYUSH,
        prompt_en="How are your bowel movements? (Mala Pariksha — stool examination)",
        prompt_hi="आपका मल त्याग कैसा है? (मल परीक्षा — पाखाने की जाँच)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("normal", "Regular, well-formed", "नियमित, ठीक बना हुआ"),
            QuestionOption("constipated", "Hard / constipated", "कठिन / कब्ज़"),
            QuestionOption("loose", "Loose / watery", "पतला / दस्त"),
            QuestionOption("irregular", "Irregular timing", "अनियमित समय पर"),
        ],
    ),
    Question(
        field_id="ayush.ashtavidha.jihva",
        section=Section.AYUSH,
        prompt_en="How does your tongue look? (Jihva Pariksha — tongue examination)",
        prompt_hi="आपकी जीभ कैसी दिखती है? (जिह्वा परीक्षा — जीभ की जाँच)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("clean", "Clean, pink", "साफ़, गुलाबी"),
            QuestionOption("coated_white", "White-coated", "सफ़ेद परत"),
            QuestionOption("coated_yellow", "Yellow-coated", "पीली परत"),
            QuestionOption("dry", "Dry / cracked", "सूखी / फटी हुई"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Nidana + Upashaya — causation and relief (condensed to 2 questions)
# ---------------------------------------------------------------------------

NIDANA_FIELDS: list[Question] = [
    Question(
        field_id="ayush.nidana.hetu",
        section=Section.AYUSH,
        prompt_en="What do you think caused your current problem? (Nidana — cause of disease)",
        prompt_hi="आपको क्या लगता है आपकी समस्या का कारण क्या है? (निदान — रोग का कारण)",
        input_type=InputType.FREE_TEXT,
    ),
    Question(
        field_id="ayush.nidana.upashaya",
        section=Section.AYUSH,
        prompt_en="What gives you relief? (Upashaya — things that help)",
        prompt_hi="किस चीज़ से आराम मिलता है? (उपशय — आराम देने वाली चीज़ें)",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("hot", "Hot / warm things", "गर्म चीज़ें"),
            QuestionOption("cold", "Cold things", "ठंडी चीज़ें"),
            QuestionOption("food", "Eating food", "खाना खाने से"),
            QuestionOption("rest", "Rest / sleep", "आराम / नींद"),
            QuestionOption("nothing", "Nothing specific", "कुछ खास नहीं"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Complete AYUSH extended fields — appended AFTER base AYUSH_FIELDS
# ---------------------------------------------------------------------------

AYUSH_EXTENDED_FIELDS: list[Question] = ASHTAVIDHA_FIELDS + NIDANA_FIELDS


# ---------------------------------------------------------------------------
# AYUSH-specific conversational prompt supplement
# ---------------------------------------------------------------------------

AYUSH_SYSTEM_SUPPLEMENT = """
AYUSH MODE — ADDITIONAL INSTRUCTIONS
You are also assessing the patient using Ayurvedic clinical principles.
In addition to the standard clinical history:

1. DASHAVIDHA PARIKSHA (10-fold assessment): Ask about Prakriti (body constitution),
   Vikriti (current imbalance), Agni (digestive fire), Sara (tissue quality),
   Sattva (mental strength), Ahara Shakti (eating capacity), Vyayama Shakti
   (exercise capacity), and diet-lifestyle (Ahara-Vihara).

2. ASHTAVIDHA PARIKSHA (8-fold examination): Ask about Mutra (urine), Mala (stool),
   Jihva (tongue). Note that Nadi (pulse), Sparsha (skin), and Drik (eyes) need
   the physician.

3. NIDANA: Ask about Hetu (cause) and Upashaya (what gives relief).

IMPORTANT:
- Always explain Ayurvedic terms in simple language with their meaning.
- Do NOT suggest treatment, medicines, or Panchakarma procedures.
- This is information gathering only — treatment is for the physician.
"""
