"""Languages endpoint — GET /languages.

Returns every language the kiosk accepts, with what it can actually do in each.
Public endpoint (no auth required): the patient picks a language before they
identify themselves.

The list is derived from ``app.interview.languages`` rather than written out here,
because it used to be a hardcoded pair that silently disagreed with what Sarvam
could handle. One registry means the picker cannot offer a language the backend
has no voice or prompts for.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.interview import languages as registry

router = APIRouter(tags=["languages"])


class LanguageItem(BaseModel):
    """One language, and honestly what the patient gets in it."""

    code: str
    name: str
    native_name: str

    support: str = Field(
        description=(
            "full — speech in, audio out, translated interface. "
            "voice_input — speech in and audio out in a fallback language, "
            "interface still English/Hindi. "
            "text_only — neither."
        )
    )
    speech_input: bool = Field(description="Sarvam Saaras can transcribe this language")
    audio_output: bool = Field(description="Sarvam Bulbul can speak this language")
    audio_language: str = Field(
        description=(
            "Language prompts are actually spoken in. Differs from `code` when "
            "Bulbul cannot voice the chosen language, so the patient hears "
            "something they are likely to follow rather than silence."
        )
    )
    interface_translated: bool = Field(
        description="On-screen text and interview questions exist in this language"
    )


class LanguagesResponse(BaseModel):
    languages: list[LanguageItem]
    default: str = Field(description="Code to preselect when nothing is chosen")


def _to_item(language: registry.Language) -> LanguageItem:
    return LanguageItem(
        code=language.code,
        name=language.english_name,
        native_name=language.native_name,
        support=language.support.value,
        speech_input=language.stt,
        audio_output=language.tts,
        audio_language=registry.tts_language(language.code),
        interface_translated=language.ui,
    )


@router.get("/languages", response_model=LanguagesResponse)
def list_languages():
    """Return every language the kiosk supports, most complete first.

    Public endpoint — no authentication required. The frontend uses this to build
    the language selection screen, and should surface `support` so a patient
    choosing a speech-only language knows the screen text will not be in it.
    """
    return LanguagesResponse(
        languages=[_to_item(language) for language in registry.LANGUAGES],
        default=registry.DEFAULT_LANGUAGE.code,
    )
