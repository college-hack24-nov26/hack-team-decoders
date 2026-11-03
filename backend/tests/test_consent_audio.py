"""Spoken consent script and the endpoint that serves it.

The consent audio is the consent record for a patient who cannot read the
screen, so two things matter beyond "it returns bytes": the wording must match
what the screen shows, and hearing it must not itself require consent.
"""

import json
from pathlib import Path

import pytest

from app.interview.consent_script import (
    CONSENT_SCRIPT,
    CONSENT_SECTIONS,
    get_consent_text,
)

_LOCALES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"


def _frontend_audio(language: str) -> dict[str, str]:
    data = json.loads((_LOCALES / language / "translation.json").read_text(encoding="utf-8"))
    return data["consent"]["audio"]


class TestScriptMatchesTheScreen:
    """The backend script is canonical; the frontend copy is the TTS fallback.

    Two copies exist, so they can drift. For ordinary UI text that is cosmetic.
    For consent wording it means the patient could be read one set of terms and
    shown another, which is exactly the kind of discrepancy a DPDP audit would
    care about.
    """

    @pytest.mark.parametrize("language", ["en", "hi"])
    def test_every_section_matches_the_frontend_verbatim(self, language):
        frontend = _frontend_audio(language)

        for section in CONSENT_SECTIONS:
            assert section in frontend, f"{section} missing from {language} translations"
            assert CONSENT_SCRIPT[section][language] == frontend[section], (
                f"Spoken and on-screen consent wording differ for "
                f"{section}/{language}. Update both."
            )

    @pytest.mark.parametrize("language", ["en", "hi"])
    def test_frontend_has_no_extra_sections(self, language):
        """A section the server cannot speak would fall back silently forever."""
        assert set(_frontend_audio(language)) == set(CONSENT_SECTIONS)


class TestScriptContent:
    def test_all_four_scopes_are_covered(self):
        assert set(CONSENT_SECTIONS) == {
            "interview",
            "sharePhysician",
            "documents",
            "abdmPush",
        }

    @pytest.mark.parametrize("section", CONSENT_SECTIONS)
    def test_both_languages_present_and_non_trivial(self, section):
        for language in ("en", "hi"):
            text = CONSENT_SCRIPT[section][language]
            assert len(text) > 80, f"{section}/{language} looks truncated"

    @pytest.mark.parametrize("section", CONSENT_SECTIONS)
    def test_hindi_is_devanagari_not_romanised(self, section):
        """Sarvam documents that romanised Indic input degrades audio quality."""
        hindi = CONSENT_SCRIPT[section]["hi"]
        devanagari = sum(1 for ch in hindi if "\u0900" <= ch <= "\u097f")
        assert devanagari > len(hindi) * 0.5

    def test_abha_is_spaced_for_speech(self):
        """TTS reads "ABHA" as a word; patients are told to look for the letters."""
        assert "A B H A" in CONSENT_SCRIPT["abdmPush"]["en"]

    def test_optional_scopes_say_they_are_optional(self):
        """A patient must know declining these does not cost them the visit."""
        assert "optional" in CONSENT_SCRIPT["documents"]["en"].lower()
        assert "optional" in CONSENT_SCRIPT["abdmPush"]["en"].lower()


class TestLookup:
    def test_known_section_returns_the_requested_language(self):
        assert get_consent_text("interview", "hi") == CONSENT_SCRIPT["interview"]["hi"]

    def test_unknown_section_returns_none(self):
        assert get_consent_text("not-a-section", "en") is None

    def test_unsupported_language_falls_back_to_english(self):
        """Better that the patient hears the terms than hears nothing."""
        assert get_consent_text("interview", "ta") == CONSENT_SCRIPT["interview"]["en"]

    def test_default_language_is_english(self):
        assert get_consent_text("documents") == CONSENT_SCRIPT["documents"]["en"]
