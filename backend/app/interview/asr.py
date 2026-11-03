"""ASR (Automatic Speech Recognition) integration.

``ASR_PROVIDER`` names an ordered chain, not a single provider:

    ASR_PROVIDER=sarvam,azure

Each is tried in turn until one returns a transcript, so a Sarvam account that
runs out of credit mid-interview escalates to Azure instead of handing the
patient a mock transcript. Left unset, the first provider with usable credentials
is chosen instead, in the order below.

  1. ``sarvam``  — Sarvam AI Saaras (``SARVAM_API_KEY``). The recommended
                   primary: built for Indian languages, accents and code-mixed
                   speech, which is what patients actually produce.
                   REST caps a request at 30 seconds of audio.
  2. ``whisper`` — OpenAI Whisper API, or a local whisper behind an
                   OpenAI-compatible endpoint. Requires ``WHISPER_API_URL``.
                   Note the hosted ``whisper`` model retires 2026-12-15.
  3. ``azure``   — Azure Speech Fast Transcription. Needs
                   ``AZURE_SPEECH_REGION`` plus ``AZURE_SPEECH_KEY``, or the
                   ``AZURE_OPENAI_API_KEY`` a multi-service Azure AI Services
                   resource shares across all its services.
  4. ``mock``    — Placeholder transcript so the app stays runnable and
                   testable with no ASR credentials at all. Always the last
                   rung, and always reachable.

Swapping providers is a config change, not a code change. A provider that
errors degrades to the mock transcript rather than raising, because a failed
transcription must not end the interview — the patient can still answer by
touch, and the text prompt is always on screen.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import BinaryIO

import httpx

from app.interview import languages
from app.services.sarvam_keys import (
    acquire_key,
    attempt_budget,
    report_key_failure,
    report_key_success,
)

logger = logging.getLogger(__name__)

#: Explicit provider selection. Leave unset to auto-detect from whichever
#: credentials are present (see :func:`_resolve_provider`).
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "").strip().lower()

WHISPER_API_URL = os.getenv(
    "WHISPER_API_URL", ""
)  # e.g. "https://api.openai.com/v1/audio/transcriptions"
WHISPER_API_KEY = os.getenv("WHISPER_API_KEY", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_STT_ENDPOINT = "https://api.sarvam.ai/speech-to-text"
#: ``saaras:v3`` is Sarvam's documented default and the only model that honours
#: ``mode``. ``saaras:v4`` is newer and covers 22 Indic languages.
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3").strip()
#: ``transcribe`` keeps the patient's own language and normalises numbers, which
#: is what a clinical record wants. ``translate`` would silently render Hindi
#: answers as English and lose the original phrasing.
SARVAM_STT_MODE = os.getenv("SARVAM_STT_MODE", "transcribe").strip()

#: Sarvam's REST transcribe endpoint caps a request at 30 seconds of audio.
_SARVAM_STT_MAX_SECONDS = 30


def _to_bcp47(language: str | None) -> str:
    """Map a short code to BCP-47, or ``unknown`` to let Sarvam auto-detect.

    Saaras covers all 22 scheduled Indian languages plus English, so an
    unrecognised code is far more likely to be one we simply have not listed
    than one the model cannot handle. Asking it to detect beats refusing.
    """
    return languages.to_bcp47(language, auto_detect=True)


def _to_short_lang(bcp47: str | None, fallback: str) -> str:
    """Map Sarvam's returned BCP-47 tag back to our short code."""
    return languages.from_bcp47(bcp47, fallback=fallback)


@dataclass
class TranscriptResult:
    """Result of an ASR transcription."""

    text: str
    language: str  # detected or specified
    confidence: float  # 0.0 to 1.0 (estimated)
    is_mock: bool = False


# ---------------------------------------------------------------------------
# Azure Speech Services (Fast Transcription)
# ---------------------------------------------------------------------------

#: Candidate locales when the patient's language is unknown.
#:
#: Azure identifies the spoken language from the candidates it is given, so the
#: list has to be supplied rather than left blank. Kept to the languages the
#: kiosk actually serves: a wider list makes identification less accurate, and
#: the endpoint caps how many candidates it will weigh.
_AZURE_LID_CANDIDATES = ["en-IN", "hi-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN"]

AZURE_STT_API_VERSION = "2024-11-15"


async def _transcribe_azure(
    audio_file: BinaryIO,
    filename: str = "audio.webm",
    language: str | None = None,
) -> TranscriptResult:
    """Transcribe via Azure Speech Fast Transcription.

    Uses the REST endpoint over httpx rather than the Speech SDK: the SDK's
    ``SpeechRecognizer`` is synchronous and would block the event loop from
    inside this coroutine. Fast Transcription also fits the shape of this call
    better than the streaming recogniser — one upload, one synchronous response,
    which is exactly what a finished kiosk recording is.
    """
    from app.services.azure_ai import app_locale, azure_locale, get_speech_credentials

    credentials = get_speech_credentials()
    if credentials is None:
        raise RuntimeError(
            "Azure STT selected but not configured. Set AZURE_SPEECH_REGION, and "
            "either AZURE_SPEECH_KEY or AZURE_OPENAI_API_KEY (a multi-service "
            "Azure AI Services resource shares one key)."
        )
    key, region = credentials

    # A known language is passed alone; an unknown one becomes a candidate list
    # for Azure's language identification.
    if language and languages.is_supported(language):
        locales = [azure_locale(languages.to_bcp47(language))]
    else:
        locales = _AZURE_LID_CANDIDATES

    definition = {"locales": locales, "profanityFilterMode": "None"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"https://{region}.api.cognitive.microsoft.com"
            f"/speechtotext/transcriptions:transcribe",
            params={"api-version": AZURE_STT_API_VERSION},
            headers={"Ocp-Apim-Subscription-Key": key},
            files={"audio": (filename, audio_file, "application/octet-stream")},
            data={"definition": json.dumps(definition)},
        )

        if response.status_code >= 400:
            logger.warning(
                "asr: Azure returned HTTP %s (region=%s, locales=%s): %s",
                response.status_code,
                region,
                ",".join(locales),
                response.text[:500],
            )
            response.raise_for_status()

        result = response.json()

    # ``combinedPhrases`` is the whole utterance already stitched together;
    # ``phrases`` carries the per-segment detail we do not need here.
    combined = result.get("combinedPhrases") or []
    text = str(combined[0].get("text", "")).strip() if combined else ""

    # The detected locale lives on the phrases, not the combined view.
    phrases = result.get("phrases") or []
    detected = phrases[0].get("locale") if phrases else None

    return TranscriptResult(
        text=text,
        language=_to_short_lang(app_locale(detected), language or "en"),
        # Azure reports per-phrase confidence; averaging it across an utterance
        # would read as more precise than it is, so this stays an estimate in
        # line with the Sarvam and Whisper paths.
        confidence=0.9,
        is_mock=False,
    )


# ---------------------------------------------------------------------------
# Sarvam AI (Saaras)
# ---------------------------------------------------------------------------


async def _transcribe_sarvam(
    audio_file: BinaryIO,
    filename: str = "audio.webm",
    language: str | None = None,
) -> TranscriptResult:
    """Transcribe via Sarvam's Saaras model.

    Purpose-built for Indian languages, accents and code-mixed speech, which is
    the whole problem here: patients answer in Hindi, in English, or in both
    within one sentence.

    ``language=None`` sends ``unknown`` so Sarvam auto-detects, and the detected
    tag comes back in the response.
    """
    data: dict[str, str] = {
        "model": SARVAM_STT_MODEL,
        "language_code": _to_bcp47(language),
    }

    # ``mode`` is only honoured by saaras:v3. Sending it to another model risks
    # a rejected request for no gain.
    if SARVAM_STT_MODEL.startswith("saaras:v3"):
        data["mode"] = SARVAM_STT_MODE

    result: dict | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        for _attempt in range(attempt_budget()):
            key = acquire_key(SARVAM_API_KEY)
            if key is None:
                raise RuntimeError("Sarvam STT: no usable API key available")

            # The stream is consumed by each attempt, so it has to be rewound
            # before a retry or the next key would receive zero bytes.
            _rewind(audio_file)

            response = await client.post(
                SARVAM_STT_ENDPOINT,
                headers={"api-subscription-key": key},
                data=data,
                files={"file": (filename, audio_file, "audio/webm")},
            )

            if response.status_code >= 400:
                logger.warning(
                    "asr: Sarvam returned HTTP %s (model=%s): %s",
                    response.status_code,
                    SARVAM_STT_MODEL,
                    response.text[:500],
                )
                if report_key_failure(key, response.status_code, fallback=SARVAM_API_KEY):
                    continue
                response.raise_for_status()

            report_key_success(key)
            result = response.json()
            break

    if result is None:  # pragma: no cover - loop either breaks or raises
        raise RuntimeError("Sarvam STT: exhausted every key without a response")

    return TranscriptResult(
        text=result.get("transcript", ""),
        language=_to_short_lang(result.get("language_code"), language or "en"),
        # Sarvam returns ``language_probability``, which scores language
        # *detection* rather than transcription accuracy. Reporting it as
        # transcript confidence would misrepresent it, so this stays an estimate
        # in line with the Whisper path.
        confidence=0.9,
        is_mock=False,
    )


# ---------------------------------------------------------------------------
# Whisper (OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------


async def _transcribe_whisper(
    audio_file: BinaryIO,
    filename: str = "audio.webm",
    language: str | None = None,
) -> TranscriptResult:
    """Call a Whisper-compatible transcription endpoint."""
    headers = {}
    if WHISPER_API_KEY:
        headers["Authorization"] = f"Bearer {WHISPER_API_KEY}"

    data: dict[str, str] = {"model": WHISPER_MODEL}
    if language:
        data["language"] = language

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            WHISPER_API_URL,
            headers=headers,
            data=data,
            files={"file": (filename, audio_file, "audio/webm")},
        )
        response.raise_for_status()
        result = response.json()

    return TranscriptResult(
        text=result.get("text", ""),
        language=result.get("language", language or "en"),
        confidence=0.9,  # Whisper doesn't return confidence; estimate high
        is_mock=False,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _is_azure_configured() -> bool:
    """Check if Azure Speech is configured without importing the SDK."""
    from app.services.azure_ai import get_speech_credentials

    return get_speech_credentials() is not None


def _provider_configured(provider: str) -> bool:
    """Whether one named provider has what it needs to run."""
    if provider == "sarvam":
        # Either a single key or a pooled one counts as configured.
        return bool(SARVAM_API_KEY) or bool(acquire_key())
    if provider == "whisper":
        return bool(WHISPER_API_URL)
    if provider == "azure":
        return _is_azure_configured()
    return provider == "mock"


def _resolve_chain() -> list[str]:
    """Providers to try in order, always ending in ``mock``.

    ``ASR_PROVIDER`` may name a chain — ``sarvam,azure`` — so a spent Sarvam
    account escalates to Azure instead of handing the patient a mock transcript.
    Unset falls back to detection in the order Sarvam, Whisper, Azure: Sarvam
    handles Indian languages and code-mixed speech better than the alternatives,
    which is the actual workload.

    ``mock`` is always last and always reachable. A failed transcription must not
    end the interview — the patient can still answer by touch, and the question
    is on screen either way.
    """
    requested = [p.strip() for p in ASR_PROVIDER.split(",") if p.strip()]
    known = [p for p in requested if p in {"sarvam", "whisper", "azure", "mock"}]

    if known:
        chain = [p for p in known if p == "mock" or _provider_configured(p)]
    else:
        chain = [p for p in ("sarvam", "whisper", "azure") if _provider_configured(p)]

    if "mock" not in chain:
        chain.append("mock")
    return chain


def _rewind(audio_file: BinaryIO) -> None:
    """Return the stream to the start so a fallback provider can read it.

    A failed attempt leaves the pointer at EOF, so without this the fallback
    would upload zero bytes and "succeed" with an empty transcript.
    """
    try:
        audio_file.seek(0)
    except (AttributeError, OSError):  # pragma: no cover - non-seekable stream
        logger.debug("asr: audio stream is not seekable; cannot rewind")


async def transcribe_audio(
    audio_file: BinaryIO,
    filename: str = "audio.webm",
    language: str | None = None,
) -> TranscriptResult:
    """Transcribe an audio file to text.

    Providers are tried in the order ``ASR_PROVIDER`` names them — a chain such
    as ``sarvam,azure`` is honoured — and detection is used when it is unset.
    Every chain ends in the mock transcript rather than an error: a failed
    transcription must not end the interview, because the patient can still
    answer by touch.

    Args:
        audio_file: The audio data (file-like object).
        filename: Original filename (helps determine format).
        language: ISO language code hint (e.g. "hi" for Hindi). ``None`` lets
            the provider auto-detect.

    Returns:
        TranscriptResult with the transcribed text.
    """
    last_error = ""
    for provider in _resolve_chain():
        if provider == "mock":
            break

        _rewind(audio_file)
        try:
            if provider == "sarvam":
                return await _transcribe_sarvam(audio_file, filename, language)
            if provider == "whisper":
                return await _transcribe_whisper(audio_file, filename, language)
            if provider == "azure":
                return await _transcribe_azure(audio_file, filename, language)
        except Exception as e:
            last_error = str(e)
            logger.warning(
                "asr: provider %s failed; trying the next one in the chain",
                provider,
                exc_info=True,
            )
            continue

    err_msg = f" (Error: {last_error})" if last_error else ""
    return TranscriptResult(
        text=(
            f"[Mock ASR] Patient spoke here — ASR not configured or failed.{err_msg} "
            "Set SARVAM_API_KEY (recommended) or WHISPER_API_URL to enable."
        ),
        language=language or "en",
        confidence=0.0,
        is_mock=True,
    )
