"""Single source of truth for language support.

Every language-related decision in the kiosk reads from here, because the four
capabilities involved do not cover the same set and previously each module kept
its own two-entry map:

  ==============  =====  ==================================================
  Capability      Count  Provider
  ==============  =====  ==================================================
  Speech-to-text     23  Sarvam Saaras — 22 scheduled languages + English
  Translation        23  Sarvam ``sarvam-translate:v1`` — same coverage
  Text-to-speech     11  Sarvam Bulbul v3 — a strict subset
  UI + questions      2  our own strings — English and Hindi only
  ==============  =====  ==================================================

The asymmetry is the whole reason this module exists. A patient can *speak*
Santali and be transcribed accurately, but Bulbul cannot speak Santali back, and
we have no Santali interview prompts to speak even if it could. Offering such a
language as if it were fully supported would strand exactly the low-literacy
patient the audio path exists for — they would hear nothing, or worse, hear a
language they do not follow.

So support is graded rather than boolean:

``FULL``
    Speech in, audio out, translated UI. Safe to offer as a headline language.
``VOICE_INPUT``
    Speech in and translation out, but prompts are delivered in
    :attr:`Language.tts_fallback`. Honest to offer, with the caveat shown.
``TEXT_ONLY``
    Neither audio nor prompts. Reachable only by an attendant translating.

Adding a language is a data change here, not a code change anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupportLevel(str, Enum):
    """How completely the kiosk serves a language. See module docstring."""

    FULL = "full"
    VOICE_INPUT = "voice_input"
    TEXT_ONLY = "text_only"


@dataclass(frozen=True)
class Language:
    """One language and exactly what the kiosk can do in it."""

    code: str
    """Short code used throughout the app and stored on the patient record."""

    bcp47: str
    """Tag every Sarvam endpoint expects, e.g. ``hi-IN``."""

    english_name: str
    native_name: str
    """Shown in the picker in its own script, so a patient who cannot read
    English can still find their language."""

    stt: bool
    """Saaras can transcribe it."""

    tts: bool
    """Bulbul v3 can speak it."""

    translate: bool
    """``sarvam-translate:v1`` can translate it to and from English."""

    ui: bool
    """We have interface strings and interview prompts for it."""

    tts_fallback: str = "en"
    """Language to speak prompts in when :attr:`tts` is False.

    A judgement call, not a fact, and deliberately conservative: Devanagari
    languages fall back to Hindi because a speaker of Maithili or Dogri is far
    more likely to follow spoken Hindi than spoken English, while for the
    others English is the safer default than guessing at regional lingua
    francas. A deployment that knows its catchment should override this.
    """

    @property
    def support(self) -> SupportLevel:
        if self.tts and self.ui:
            return SupportLevel.FULL
        if self.stt:
            return SupportLevel.VOICE_INPUT
        return SupportLevel.TEXT_ONLY


# Bulbul v3 speaks these 11. Everything else is speech-in only.
_TTS_CAPABLE = {"en", "hi", "bn", "ta", "te", "gu", "kn", "ml", "mr", "pa", "od"}

# We only have interface strings and clinical prompts in these two. This is the
# real ceiling on headline language support, and it is not a Sarvam limitation:
# machine-translating clinical questions is a patient-safety risk, so these grow
# only with reviewed human translation.
_UI_TRANSLATED = {"en", "hi", "bn", "mr", "te", "ta", "gu", "kn", "ml", "pa"}


def _lang(
    code: str,
    bcp47: str,
    english_name: str,
    native_name: str,
    *,
    tts_fallback: str = "en",
) -> Language:
    """Build an entry. Saaras and sarvam-translate cover every language here."""
    return Language(
        code=code,
        bcp47=bcp47,
        english_name=english_name,
        native_name=native_name,
        stt=True,
        tts=code in _TTS_CAPABLE,
        translate=True,
        ui=code in _UI_TRANSLATED,
        tts_fallback=tts_fallback,
    )


#: Every language the kiosk accepts speech in, ordered so the fully supported
#: ones come first — that is what the picker should surface most prominently.
LANGUAGES: tuple[Language, ...] = (
    # ── Full support: speech in, audio out, translated interface ──────────
    _lang("en", "en-IN", "English", "English"),
    _lang("hi", "hi-IN", "Hindi", "हिन्दी"),
    # ── Audio out, but interface still English/Hindi ──────────────────────
    _lang("bn", "bn-IN", "Bengali", "বাংলা"),
    _lang("ta", "ta-IN", "Tamil", "தமிழ்"),
    _lang("te", "te-IN", "Telugu", "తెలుగు"),
    _lang("mr", "mr-IN", "Marathi", "मराठी"),
    _lang("gu", "gu-IN", "Gujarati", "ગુજરાતી"),
    _lang("kn", "kn-IN", "Kannada", "ಕನ್ನಡ"),
    _lang("ml", "ml-IN", "Malayalam", "മലയാളം"),
    _lang("pa", "pa-IN", "Punjabi", "ਪੰਜਾਬੀ"),
    _lang("od", "od-IN", "Odia", "ଓଡ଼ିଆ"),
    # ── Speech in only: Bulbul cannot voice these yet ─────────────────────
    _lang("ur", "ur-IN", "Urdu", "اردو", tts_fallback="hi"),
    _lang("as", "as-IN", "Assamese", "অসমীয়া"),
    _lang("mai", "mai-IN", "Maithili", "मैथिली", tts_fallback="hi"),
    _lang("ne", "ne-IN", "Nepali", "नेपाली", tts_fallback="hi"),
    _lang("kok", "kok-IN", "Konkani", "कोंकणी", tts_fallback="hi"),
    _lang("doi", "doi-IN", "Dogri", "डोगरी", tts_fallback="hi"),
    _lang("sa", "sa-IN", "Sanskrit", "संस्कृतम्", tts_fallback="hi"),
    _lang("brx", "brx-IN", "Bodo", "बड़ो", tts_fallback="hi"),
    _lang("ks", "ks-IN", "Kashmiri", "کٲشُر"),
    _lang("sd", "sd-IN", "Sindhi", "سنڌي"),
    _lang("mni", "mni-IN", "Manipuri", "ꯃꯤꯇꯩꯂꯣꯟ"),
    _lang("sat", "sat-IN", "Santali", "ᱥᱟᱱᱛᱟᱲᱤ"),
)

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}

#: Fallback when a code is unrecognised. English rather than a guess: the
#: summariser and the physician both read English, so an unknown code degrades
#: to something usable instead of failing.
DEFAULT_LANGUAGE = _BY_CODE["en"]

#: Sarvam's sentinel asking Saaras to detect the language itself.
AUTO_DETECT = "unknown"


def get(code: str | None) -> Language:
    """Resolve a short code, tolerating BCP-47 and unknown values."""
    if not code:
        return DEFAULT_LANGUAGE
    normalised = code.strip().lower().replace("_", "-")
    if normalised in _BY_CODE:
        return _BY_CODE[normalised]
    # Accept a full tag ("hi-IN") wherever a short code is expected.
    return _BY_CODE.get(normalised.split("-")[0], DEFAULT_LANGUAGE)


def is_supported(code: str | None) -> bool:
    """Whether the code names a language we actually know about."""
    if not code:
        return False
    normalised = code.strip().lower().replace("_", "-")
    return normalised in _BY_CODE or normalised.split("-")[0] in _BY_CODE


def to_bcp47(code: str | None, *, auto_detect: bool = False) -> str:
    """Map a short code to the tag Sarvam expects.

    ``auto_detect`` returns Saaras's ``unknown`` sentinel for an unrecognised
    language, which is better than guessing: the patient may well be speaking
    something we did not expect, and the model can identify it.
    """
    if auto_detect and not is_supported(code):
        return AUTO_DETECT
    return get(code).bcp47


def from_bcp47(tag: str | None, fallback: str = "en") -> str:
    """Map a tag Sarvam returned back to our short code."""
    if not tag:
        return fallback
    base = tag.strip().lower().split("-")[0]
    return base if base in _BY_CODE else fallback


def tts_language(code: str | None) -> str:
    """Short code to actually synthesise audio in.

    Returns the requested language when Bulbul supports it, otherwise the
    configured fallback. Never returns a language Bulbul cannot speak, because
    Sarvam would reject the request and the patient would get silence — the one
    outcome the audio path exists to prevent.
    """
    language = get(code)
    if language.tts:
        return language.code
    return get(language.tts_fallback).code if language.tts_fallback else "en"


def needs_translation_for_summary(code: str | None) -> bool:
    """Whether a transcript in this language should be translated before the LLM.

    English needs nothing. Hindi is left alone too: the summariser handles it
    well, and translating would discard the patient's own words for no gain.
    Everything else is translated to English first, because a summary that
    quietly degrades on a low-resource language is worse than one extra API
    call — the physician cannot tell a bad translation from a bad history.
    """
    return get(code).code not in {"en", "hi"}


def stt_languages() -> tuple[Language, ...]:
    return tuple(lang for lang in LANGUAGES if lang.stt)


def tts_languages() -> tuple[Language, ...]:
    return tuple(lang for lang in LANGUAGES if lang.tts)


def as_api_payload() -> list[dict]:
    """Serialise for the frontend language picker.

    The picker is driven by this rather than a hardcoded list so it cannot offer
    a language the backend has no voice or prompts for.
    """
    return [
        {
            "code": lang.code,
            "bcp47": lang.bcp47,
            "englishName": lang.english_name,
            "nativeName": lang.native_name,
            "support": lang.support.value,
            "speechInput": lang.stt,
            "audioOutput": lang.tts,
            "audioLanguage": tts_language(lang.code),
            "interfaceTranslated": lang.ui,
        }
        for lang in LANGUAGES
    ]
