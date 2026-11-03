"""Chief-complaint templates — SOCRATES-style branching per complaint.

Adding a new template is a config change: define the questions list and register
it in TEMPLATES dict at the bottom. The dialogue manager indexes into this.

Each template defines the HPI (History of Present Illness) questions specific to
that chief complaint. The base history fields (PMH, drugs, allergies, family,
personal, ROS) are appended automatically by the dialogue manager after
the template-specific HPI questions.
"""

from __future__ import annotations

from app.interview.ontology import (
    InputType,
    Question,
    QuestionOption,
    Section,
)

# ---------------------------------------------------------------------------
# SOCRATES framework reminder (what each letter covers):
# S - Site: Where is the pain/symptom?
# O - Onset: When did it start? Sudden or gradual?
# C - Character: What does it feel like?
# R - Radiation: Does it spread anywhere?
# A - Associations: Any other symptoms at the same time?
# T - Time course: Constant? Comes and goes? Getting worse?
# E - Exacerbating/relieving: What makes it better or worse?
# S - Severity: How bad is it (1-10)?
# ---------------------------------------------------------------------------


# ===========================================================================
# CHEST PAIN
# ===========================================================================

CHEST_PAIN_HPI: list[Question] = [
    Question(
        field_id="hpi.site",
        section=Section.HPI,
        prompt_en="Where exactly in your chest do you feel the pain?",
        prompt_hi="सीने में दर्द ठीक कहाँ हो रहा है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("central", "Centre of chest", "सीने के बीच में"),
            QuestionOption("left", "Left side", "बाईं तरफ़"),
            QuestionOption("right", "Right side", "दाईं तरफ़"),
            QuestionOption("diffuse", "All over / hard to point", "पूरे सीने में"),
        ],
    ),
    Question(
        field_id="hpi.onset",
        section=Section.HPI,
        prompt_en="When did the chest pain start?",
        prompt_hi="सीने का दर्द कब शुरू हुआ?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("minutes", "Minutes ago", "कुछ मिनट पहले"),
            QuestionOption("hours", "Hours ago", "कुछ घंटे पहले"),
            QuestionOption("days", "Days ago", "कुछ दिन पहले"),
            QuestionOption("weeks", "Weeks / longer", "हफ़्तों / ज़्यादा पहले"),
        ],
    ),
    Question(
        field_id="hpi.onset_type",
        section=Section.HPI,
        prompt_en="Did it start suddenly or gradually?",
        prompt_hi="अचानक शुरू हुआ या धीरे-धीरे?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("sudden", "Sudden", "अचानक"),
            QuestionOption("gradual", "Gradual", "धीरे-धीरे"),
        ],
    ),
    Question(
        field_id="hpi.character",
        section=Section.HPI,
        prompt_en="What does the pain feel like?",
        prompt_hi="दर्द कैसा लगता है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("crushing", "Crushing / heavy / pressure", "दबाव / भारीपन"),
            QuestionOption("sharp", "Sharp / stabbing", "तेज़ / चुभने वाला"),
            QuestionOption("burning", "Burning", "जलन"),
            QuestionOption("aching", "Dull ache", "हल्का दर्द"),
            QuestionOption("tearing", "Tearing", "फटने जैसा"),
        ],
    ),
    Question(
        field_id="hpi.radiation",
        section=Section.HPI,
        prompt_en="Does the pain spread to any other area?",
        prompt_hi="क्या दर्द कहीं और भी जाता है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("left_arm", "Left arm", "बाएँ हाथ में"),
            QuestionOption("jaw", "Jaw / neck", "जबड़े / गले में"),
            QuestionOption("back", "Back", "पीठ में"),
            QuestionOption("right_arm", "Right arm", "दाएँ हाथ में"),
            QuestionOption("nowhere", "Doesn't spread", "कहीं नहीं जाता"),
        ],
    ),
    Question(
        field_id="hpi.associations",
        section=Section.HPI,
        prompt_en="Do you have any of these along with the chest pain?",
        prompt_hi="सीने के दर्द के साथ इनमें से कुछ हो रहा है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("breathlessness", "Breathlessness", "साँस फूलना"),
            QuestionOption("sweating", "Sweating", "पसीना आना"),
            QuestionOption("nausea", "Nausea / vomiting", "जी मिचलाना / उल्टी"),
            QuestionOption("dizziness", "Dizziness", "चक्कर आना"),
            QuestionOption("palpitations", "Palpitations", "धड़कन तेज़"),
            QuestionOption("none", "None of these", "इनमें से कोई नहीं"),
        ],
    ),
    Question(
        field_id="hpi.time_course",
        section=Section.HPI,
        prompt_en="Is the pain constant or does it come and go?",
        prompt_hi="दर्द लगातार है या आता-जाता है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("constant", "Constant", "लगातार"),
            QuestionOption("intermittent", "Comes and goes", "आता-जाता है"),
            QuestionOption("worsening", "Getting worse over time", "बढ़ता जा रहा है"),
        ],
    ),
    Question(
        field_id="hpi.exacerbating",
        section=Section.HPI,
        prompt_en="Does anything make the pain worse?",
        prompt_hi="किसी चीज़ से दर्द बढ़ता है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("exertion", "Physical activity / walking", "शारीरिक गतिविधि"),
            QuestionOption("breathing", "Deep breathing", "गहरी साँस लेने से"),
            QuestionOption("eating", "Eating", "खाने से"),
            QuestionOption("lying_flat", "Lying flat", "लेटने से"),
            QuestionOption("nothing", "Nothing specific", "कुछ खास नहीं"),
        ],
    ),
    Question(
        field_id="hpi.relieving",
        section=Section.HPI,
        prompt_en="Does anything make the pain better?",
        prompt_hi="किसी चीज़ से दर्द कम होता है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("rest", "Rest", "आराम करने से"),
            QuestionOption("antacid", "Antacid / food", "एंटासिड / खाने से"),
            QuestionOption("position", "Sitting up / leaning forward", "बैठने से"),
            QuestionOption("nothing", "Nothing helps", "कुछ काम नहीं करता"),
        ],
    ),
    Question(
        field_id="hpi.severity",
        section=Section.HPI,
        prompt_en="On a scale of 1-10, how bad is the pain right now?",
        prompt_hi="1 से 10 में, अभी दर्द कितना तेज़ है?",
        input_type=InputType.NUMERIC,
    ),
]


# ===========================================================================
# FEVER
# ===========================================================================

FEVER_HPI: list[Question] = [
    Question(
        field_id="hpi.onset",
        section=Section.HPI,
        prompt_en="When did the fever start?",
        prompt_hi="बुखार कब से है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("today", "Today", "आज"),
            QuestionOption("days", "A few days ago", "कुछ दिन पहले"),
            QuestionOption("week", "About a week", "लगभग एक हफ़्ता"),
            QuestionOption("longer", "More than a week", "एक हफ़्ते से ज़्यादा"),
        ],
    ),
    Question(
        field_id="hpi.pattern",
        section=Section.HPI,
        prompt_en="How does the fever behave?",
        prompt_hi="बुखार कैसे आता है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("continuous", "Continuous (always there)", "लगातार"),
            QuestionOption("intermittent", "Comes and goes with chills", "आता-जाता है, ठंड लगती है"),
            QuestionOption("evening_rise", "Rises in the evening", "शाम को बढ़ता है"),
            QuestionOption("alternate_days", "Every other day", "एक दिन छोड़कर"),
        ],
    ),
    Question(
        field_id="hpi.degree",
        section=Section.HPI,
        prompt_en="How high is the fever? (If measured)",
        prompt_hi="बुखार कितना है? (अगर नापा हो)",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("low", "Mild / low-grade (99-100°F)", "हल्का (99-100°F)"),
            QuestionOption("moderate", "Moderate (100-102°F)", "मध्यम (100-102°F)"),
            QuestionOption("high", "High (102-104°F)", "तेज़ (102-104°F)"),
            QuestionOption("very_high", "Very high (>104°F)", "बहुत तेज़ (>104°F)"),
            QuestionOption("not_measured", "Haven't measured", "नापा नहीं"),
        ],
    ),
    Question(
        field_id="hpi.associations",
        section=Section.HPI,
        prompt_en="Do you have any of these along with the fever?",
        prompt_hi="बुखार के साथ इनमें से कुछ है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("chills", "Chills / shivering", "ठंड / कंपकंपी"),
            QuestionOption("headache", "Headache", "सिरदर्द"),
            QuestionOption("body_ache", "Body aches", "बदन दर्द"),
            QuestionOption("cough", "Cough", "खाँसी"),
            QuestionOption("rash", "Skin rash", "चकत्ते"),
            QuestionOption("burning_urine", "Burning urination", "पेशाब में जलन"),
            QuestionOption("vomiting", "Vomiting", "उल्टी"),
            QuestionOption("none", "None of these", "इनमें से कोई नहीं"),
        ],
    ),
    Question(
        field_id="hpi.travel",
        section=Section.HPI,
        prompt_en="Have you traveled anywhere in the last 2 weeks?",
        prompt_hi="क्या आप पिछले 2 हफ़्तों में कहीं गए थे?",
        input_type=InputType.YES_NO,
    ),
    Question(
        field_id="hpi.contact",
        section=Section.HPI,
        prompt_en="Has anyone around you been sick recently?",
        prompt_hi="क्या आपके आस-पास कोई बीमार था हाल ही में?",
        input_type=InputType.YES_NO,
    ),
    Question(
        field_id="hpi.severity",
        section=Section.HPI,
        prompt_en="How much is the fever affecting your daily activities?",
        prompt_hi="बुखार से आपके रोज़मर्रा के काम पर कितना असर पड़ रहा है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("mild", "Mild — can do most things", "हल्का — ज़्यादातर काम कर सकता हूँ"),
            QuestionOption("moderate", "Moderate — need to rest", "मध्यम — आराम चाहिए"),
            QuestionOption("severe", "Severe — bedridden", "गंभीर — बिस्तर से उठ नहीं पाता"),
        ],
    ),
]


# ===========================================================================
# ABDOMINAL PAIN
# ===========================================================================

ABDOMINAL_PAIN_HPI: list[Question] = [
    Question(
        field_id="hpi.site",
        section=Section.HPI,
        prompt_en="Where in your abdomen is the pain?",
        prompt_hi="पेट में दर्द कहाँ हो रहा है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("epigastric", "Upper middle (stomach area)", "ऊपर बीच में"),
            QuestionOption("right_upper", "Right upper", "दाईं तरफ़ ऊपर"),
            QuestionOption("left_upper", "Left upper", "बाईं तरफ़ ऊपर"),
            QuestionOption("periumbilical", "Around the navel", "नाभि के आसपास"),
            QuestionOption("right_lower", "Right lower", "दाईं तरफ़ नीचे"),
            QuestionOption("left_lower", "Left lower", "बाईं तरफ़ नीचे"),
            QuestionOption("diffuse", "All over", "पूरे पेट में"),
        ],
    ),
    Question(
        field_id="hpi.onset",
        section=Section.HPI,
        prompt_en="When did the pain start?",
        prompt_hi="दर्द कब शुरू हुआ?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("hours", "A few hours ago", "कुछ घंटे पहले"),
            QuestionOption("days", "A few days ago", "कुछ दिन पहले"),
            QuestionOption("weeks", "Weeks / chronic", "हफ़्तों से / पुराना"),
        ],
    ),
    Question(
        field_id="hpi.character",
        section=Section.HPI,
        prompt_en="What does the pain feel like?",
        prompt_hi="दर्द कैसा लगता है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("cramping", "Cramping / colicky", "ऐंठन / मरोड़"),
            QuestionOption("burning", "Burning", "जलन"),
            QuestionOption("sharp", "Sharp / stabbing", "तेज़ / चुभने वाला"),
            QuestionOption("dull", "Dull / heavy", "भारी / हल्का दर्द"),
        ],
    ),
    Question(
        field_id="hpi.associations",
        section=Section.HPI,
        prompt_en="Any of these along with the pain?",
        prompt_hi="दर्द के साथ इनमें से कुछ है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("nausea", "Nausea / vomiting", "जी मिचलाना / उल्टी"),
            QuestionOption("diarrhea", "Loose stools / diarrhea", "दस्त"),
            QuestionOption("constipation", "Constipation", "कब्ज़"),
            QuestionOption("blood_stool", "Blood in stool", "मल में खून"),
            QuestionOption("fever", "Fever", "बुखार"),
            QuestionOption("bloating", "Bloating / gas", "पेट फूलना / गैस"),
            QuestionOption("none", "None", "कोई नहीं"),
        ],
    ),
    Question(
        field_id="hpi.food_relation",
        section=Section.HPI,
        prompt_en="Is the pain related to eating?",
        prompt_hi="क्या दर्द का खाने से संबंध है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("worse_after", "Worse after eating", "खाने के बाद बढ़ता है"),
            QuestionOption("better_after", "Better after eating", "खाने से कम होता है"),
            QuestionOption("worse_empty", "Worse on empty stomach", "खाली पेट बढ़ता है"),
            QuestionOption("no_relation", "No relation", "कोई संबंध नहीं"),
        ],
    ),
    Question(
        field_id="hpi.severity",
        section=Section.HPI,
        prompt_en="On a scale of 1-10, how bad is the pain?",
        prompt_hi="1 से 10 में दर्द कितना तेज़ है?",
        input_type=InputType.NUMERIC,
    ),
]


# ===========================================================================
# HEADACHE
# ===========================================================================

HEADACHE_HPI: list[Question] = [
    Question(
        field_id="hpi.site",
        section=Section.HPI,
        prompt_en="Where is the headache?",
        prompt_hi="सिरदर्द कहाँ हो रहा है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("frontal", "Front / forehead", "आगे / माथे पर"),
            QuestionOption("temporal", "Sides / temples", "दोनों तरफ़ / कनपटी"),
            QuestionOption("occipital", "Back of head", "सिर के पीछे"),
            QuestionOption("one_side", "One side only", "एक तरफ़"),
            QuestionOption("all_over", "All over", "पूरे सिर में"),
        ],
    ),
    Question(
        field_id="hpi.onset",
        section=Section.HPI,
        prompt_en="When did this headache start?",
        prompt_hi="यह सिरदर्द कब शुरू हुआ?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("sudden", "Sudden (thunderclap)", "अचानक (बहुत तेज़)"),
            QuestionOption("hours", "A few hours ago", "कुछ घंटे पहले"),
            QuestionOption("days", "A few days", "कुछ दिनों से"),
            QuestionOption("recurrent", "Keeps coming back (weeks/months)", "बार-बार आता है"),
        ],
    ),
    Question(
        field_id="hpi.character",
        section=Section.HPI,
        prompt_en="What does the headache feel like?",
        prompt_hi="सिरदर्द कैसा लगता है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("throbbing", "Throbbing / pulsating", "धड़कता हुआ"),
            QuestionOption("pressure", "Pressure / band-like", "दबाव / पट्टी बँधी हो जैसे"),
            QuestionOption("sharp", "Sharp / stabbing", "तेज़ / चुभने वाला"),
            QuestionOption("dull", "Dull / constant", "हल्का / लगातार"),
        ],
    ),
    Question(
        field_id="hpi.associations",
        section=Section.HPI,
        prompt_en="Do you have any of these with the headache?",
        prompt_hi="सिरदर्द के साथ इनमें से कुछ है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("nausea", "Nausea / vomiting", "जी मिचलाना / उल्टी"),
            QuestionOption("light_sensitivity", "Sensitivity to light", "रोशनी से तकलीफ़"),
            QuestionOption("visual_changes", "Visual changes / aura", "दिखने में बदलाव"),
            QuestionOption("neck_stiffness", "Neck stiffness", "गर्दन अकड़ना"),
            QuestionOption("fever", "Fever", "बुखार"),
            QuestionOption("weakness", "Weakness in arms/legs", "हाथ/पैर में कमज़ोरी"),
            QuestionOption("none", "None", "कोई नहीं"),
        ],
    ),
    Question(
        field_id="hpi.severity",
        section=Section.HPI,
        prompt_en="On a scale of 1-10, how bad is the headache?",
        prompt_hi="1 से 10 में सिरदर्द कितना तेज़ है?",
        input_type=InputType.NUMERIC,
    ),
    Question(
        field_id="hpi.worst_headache",
        section=Section.HPI,
        prompt_en="Is this the worst headache of your life?",
        prompt_hi="क्या यह आपकी ज़िंदगी का सबसे तेज़ सिरदर्द है?",
        input_type=InputType.YES_NO,
    ),
]


# ===========================================================================
# BREATHLESSNESS
# ===========================================================================

BREATHLESSNESS_HPI: list[Question] = [
    Question(
        field_id="hpi.onset",
        section=Section.HPI,
        prompt_en="When did the breathlessness start?",
        prompt_hi="साँस फूलना कब शुरू हुआ?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("sudden", "Sudden (minutes)", "अचानक (कुछ मिनट)"),
            QuestionOption("hours", "Over hours", "कुछ घंटों में"),
            QuestionOption("days", "Over days", "कुछ दिनों में"),
            QuestionOption("chronic", "Weeks / months (worsening)", "हफ़्तों / महीनों से (बढ़ रहा)"),
        ],
    ),
    Question(
        field_id="hpi.trigger",
        section=Section.HPI,
        prompt_en="When do you feel breathless?",
        prompt_hi="साँस कब फूलती है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("rest", "Even at rest", "आराम करते हुए भी"),
            QuestionOption("minimal", "Walking a short distance", "थोड़ा चलने पर"),
            QuestionOption("moderate", "Climbing stairs", "सीढ़ियाँ चढ़ने पर"),
            QuestionOption("heavy", "Only with heavy exertion", "सिर्फ़ भारी काम करने पर"),
        ],
    ),
    Question(
        field_id="hpi.orthopnea",
        section=Section.HPI,
        prompt_en="Do you need extra pillows to sleep? Can you lie flat?",
        prompt_hi="क्या सोने के लिए ज़्यादा तकिए चाहिए? क्या सीधे लेट सकते हैं?",
        input_type=InputType.YES_NO,
    ),
    Question(
        field_id="hpi.associations",
        section=Section.HPI,
        prompt_en="Any of these along with the breathlessness?",
        prompt_hi="साँस फूलने के साथ इनमें से कुछ है?",
        input_type=InputType.MULTI_CHOICE,
        options=[
            QuestionOption("chest_pain", "Chest pain", "सीने में दर्द"),
            QuestionOption("cough", "Cough", "खाँसी"),
            QuestionOption("wheezing", "Wheezing", "घरघराहट"),
            QuestionOption("leg_swelling", "Leg swelling", "पैरों में सूजन"),
            QuestionOption("hemoptysis", "Coughing blood", "खाँसी में खून"),
            QuestionOption("fever", "Fever", "बुखार"),
            QuestionOption("none", "None", "कोई नहीं"),
        ],
    ),
    Question(
        field_id="hpi.previous_episodes",
        section=Section.HPI,
        prompt_en="Have you had similar episodes before?",
        prompt_hi="क्या पहले भी ऐसा हुआ है?",
        input_type=InputType.YES_NO,
    ),
    Question(
        field_id="hpi.severity",
        section=Section.HPI,
        prompt_en="How breathless are you right now (1-10)?",
        prompt_hi="अभी साँस कितनी फूल रही है (1-10)?",
        input_type=InputType.NUMERIC,
    ),
]


# ===========================================================================
# GENERIC FALLBACK — for any complaint not covered above
# ===========================================================================

GENERIC_HPI: list[Question] = [
    Question(
        field_id="hpi.description",
        section=Section.HPI,
        prompt_en="Please describe your main problem in your own words.",
        prompt_hi="कृपया अपनी मुख्य समस्या अपने शब्दों में बताइए।",
        input_type=InputType.FREE_TEXT,
    ),
    Question(
        field_id="hpi.onset",
        section=Section.HPI,
        prompt_en="When did this problem start?",
        prompt_hi="यह समस्या कब शुरू हुई?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("today", "Today", "आज"),
            QuestionOption("days", "A few days ago", "कुछ दिन पहले"),
            QuestionOption("weeks", "Weeks ago", "हफ़्तों पहले"),
            QuestionOption("months", "Months / longer", "महीनों / ज़्यादा पहले"),
        ],
    ),
    Question(
        field_id="hpi.time_course",
        section=Section.HPI,
        prompt_en="Is it getting better, worse, or staying the same?",
        prompt_hi="बढ़ रहा है, कम हो रहा है, या वही है?",
        input_type=InputType.SINGLE_CHOICE,
        options=[
            QuestionOption("better", "Getting better", "कम हो रहा है"),
            QuestionOption("worse", "Getting worse", "बढ़ रहा है"),
            QuestionOption("same", "About the same", "वही है"),
        ],
    ),
    Question(
        field_id="hpi.severity",
        section=Section.HPI,
        prompt_en="On a scale of 1-10, how much does this bother you?",
        prompt_hi="1 से 10 में यह कितना परेशान करता है?",
        input_type=InputType.NUMERIC,
    ),
    Question(
        field_id="hpi.associations",
        section=Section.HPI,
        prompt_en="Any other symptoms along with this?",
        prompt_hi="इसके साथ और कोई लक्षण है?",
        input_type=InputType.FREE_TEXT,
        required=False,
    ),
]


# ===========================================================================
# TEMPLATE REGISTRY — the dialogue manager uses this dict
# ===========================================================================

TEMPLATES: dict[str, list[Question]] = {
    "chest_pain": CHEST_PAIN_HPI,
    "fever": FEVER_HPI,
    "abdominal_pain": ABDOMINAL_PAIN_HPI,
    "headache": HEADACHE_HPI,
    "breathlessness": BREATHLESSNESS_HPI,
    "generic": GENERIC_HPI,
}

# Chief complaint selection question — asked first in every interview
CHIEF_COMPLAINT_QUESTION = Question(
    field_id="chief_complaint",
    section=Section.CHIEF_COMPLAINT,
    prompt_en="What is your main problem today?",
    prompt_hi="आज आपकी मुख्य समस्या क्या है?",
    input_type=InputType.SINGLE_CHOICE,
    options=[
        QuestionOption("chest_pain", "Chest pain", "सीने में दर्द"),
        QuestionOption("fever", "Fever", "बुखार"),
        QuestionOption("abdominal_pain", "Stomach / abdominal pain", "पेट दर्द"),
        QuestionOption("headache", "Headache", "सिरदर्द"),
        QuestionOption("breathlessness", "Difficulty breathing", "साँस फूलना"),
        QuestionOption("other", "Something else", "कुछ और"),
    ],
)
