"""Canonical spoken consent script.

The consent screen is built for a patient who cannot read it, so the audio is
the consent record — not a convenience. That makes this text legally meaningful:
what the patient *hears* is what they agreed to.

It lives here, server-side, for two reasons:

1. The browser SpeechSynthesis API the consent page previously used is
   device-dependent. On a kiosk it produced a flat robotic voice, and on a
   device with no Hindi voice installed it silently produced nothing at all —
   for the exact users who depend on it most.
2. Synthesising from a fixed, server-owned set of strings means the TTS
   endpoint can never be handed arbitrary text. An open text-to-speech proxy in
   front of a paid provider is someone else's bill waiting to happen.

The frontend keeps its own copy under ``consent.audio.*`` purely as a fallback
for when server TTS is unconfigured. ``tests/test_consent_audio.py`` asserts the
two stay identical, so the spoken and on-screen wording cannot drift apart.

Keys match the i18n keys the consent page already uses.
"""

from __future__ import annotations

#: Spoken consent script, keyed by section then language.
#:
#: Note "A B H A" is spaced deliberately in the English text: TTS engines read
#: "ABHA" as a word ("abba") rather than the four letters patients are told to
#: look for on their card.
CONSENT_SCRIPT: dict[str, dict[str, str]] = {
    "interview": {
        "en": (
            "This section asks your permission for us to ask you questions about "
            "your health. We will ask what problem brought you here, how long you "
            "have had it, what other illnesses you have had, and which medicines "
            "you take. Your answers will be saved and shown to your doctor. You "
            "may stop at any time."
        ),
        "hi": (
            "यह भाग आपसे अनुमति मांगता है कि हम आपके स्वास्थ्य के बारे में प्रश्न पूछ सकें। "
            "हम पूछेंगे कि आप किस तकलीफ़ के कारण आए हैं, वह कब से है, आपको पहले कौन सी "
            "बीमारियाँ हुई हैं, और आप कौन सी दवाएँ लेते हैं। आपके उत्तर सुरक्षित रखे जाएँगे और "
            "आपके डॉक्टर को दिखाए जाएँगे। आप किसी भी समय रोक सकते हैं।"
        ),
    },
    "sharePhysician": {
        "en": (
            "This section asks your permission to show everything you tell us to "
            "the doctor who will treat you at this hospital. This helps the doctor "
            "understand your problem before you go in, so your time with the "
            "doctor is used well."
        ),
        "hi": (
            "यह भाग आपसे अनुमति मांगता है कि आप जो कुछ बताते हैं वह इस अस्पताल में आपका "
            "इलाज करने वाले डॉक्टर को दिखाया जा सके। इससे डॉक्टर आपके अंदर जाने से पहले ही "
            "आपकी तकलीफ़ समझ लेते हैं, और डॉक्टर के साथ आपका समय अच्छे से काम आता है।"
        ),
    },
    "documents": {
        "en": (
            "This section asks your permission to look at any medical papers you "
            "have brought, such as old prescriptions, laboratory reports, or "
            "hospital discharge papers. We will read them, pick out the important "
            "details, and arrange them by date for your doctor. This is optional. "
            "You may say no and still see the doctor."
        ),
        "hi": (
            "यह भाग आपसे अनुमति मांगता है कि हम आपके लाए हुए काग़ज़ देख सकें, जैसे पुरानी "
            "पर्चियाँ, जाँच की रिपोर्ट, या अस्पताल से छुट्टी के काग़ज़। हम उन्हें पढ़ेंगे, ज़रूरी "
            "बातें निकालेंगे, और तारीख़ के क्रम में लगाकर आपके डॉक्टर को देंगे। यह वैकल्पिक है। "
            "आप मना करके भी डॉक्टर से मिल सकते हैं।"
        ),
    },
    "abdmPush": {
        "en": (
            "This section is optional. It asks whether we may save a summary of "
            "today's visit to your A B H A health record, which is your national "
            "health record. If you agree, any hospital in India can see this visit "
            "in future. If you say no, your information stays only with this "
            "hospital."
        ),
        "hi": (
            "यह भाग वैकल्पिक है। इसमें पूछा जाता है कि क्या हम आज की भेंट का सारांश आपके "
            "आभा स्वास्थ्य रिकॉर्ड में रख सकते हैं, जो आपका राष्ट्रीय स्वास्थ्य रिकॉर्ड है। यदि आप "
            "सहमत हैं, तो आगे भारत का कोई भी अस्पताल इस भेंट को देख सकेगा। यदि आप मना "
            "करते हैं, तो आपकी जानकारी केवल इस अस्पताल में रहेगी।"
        ),
    },
}

#: The sections a patient is read, in the order the screen presents them.
CONSENT_SECTIONS: tuple[str, ...] = tuple(CONSENT_SCRIPT)


def get_consent_text(section: str, language: str = "en") -> str | None:
    """Return the spoken script for ``section``, or ``None`` if unknown.

    Falls back to English for a language we have no translation for, which is
    better than silence: the patient still hears the terms, and the attendant
    can translate.
    """
    translations = CONSENT_SCRIPT.get(section)
    if translations is None:
        return None
    return translations.get(language) or translations["en"]
