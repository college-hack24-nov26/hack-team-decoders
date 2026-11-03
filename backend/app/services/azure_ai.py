"""Unified Azure AI client initialization.

Factory functions for the three Azure services used by MediKiosk:
  1. Azure OpenAI  — conversational AI, document analysis, summaries
  2. Azure Speech  — STT and TTS with native Hindi support
  3. Azure Document Intelligence — high-quality OCR

Each function returns ``None`` when the required env vars are not set,
so the app continues to work without any Azure configuration — existing
Whisper/Sarvam/Tesseract/mock providers remain as fallbacks.

All Azure SDK imports are **lazy** (inside the function body). This avoids
import-time crashes when the optional Azure packages are not installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from azure.ai.documentintelligence import DocumentIntelligenceClient

logger = logging.getLogger(__name__)

# Path suffix for the Azure OpenAI / Microsoft Foundry v1 API.
#
# The v1 API (GA since August 2025) is OpenAI-wire-compatible and needs no
# dated ``api-version`` query parameter, which removes the monthly-deprecation
# treadmill the older ``?api-version=YYYY-MM-DD`` surface imposed. Microsoft
# documents this same base URL for both resource shapes:
#   - Azure OpenAI resource : https://<res>.openai.azure.com/openai/v1/
#   - Foundry resource      : https://<res>.services.ai.azure.com/openai/v1/
# See https://learn.microsoft.com/en-us/azure/ai-services/openai/api-version-lifecycle
_V1_SUFFIX = "/openai/v1"


def get_azure_openai_v1_base_url() -> str | None:
    """Return the normalized Azure OpenAI **v1** base URL, or ``None``.

    Accepts whatever shape the user pasted out of the Azure portal and
    normalizes it to a ``/openai/v1`` base, so all of these work:

    ``https://res.openai.azure.com``            -> ``.../openai/v1``
    ``https://res.openai.azure.com/``           -> ``.../openai/v1``
    ``https://res.services.ai.azure.com``       -> ``.../openai/v1``  (Foundry)
    ``https://res.openai.azure.com/openai``     -> ``.../openai/v1``
    ``https://res.openai.azure.com/openai/v1/`` -> unchanged

    Returns ``None`` when ``AZURE_OPENAI_ENDPOINT`` or ``AZURE_OPENAI_API_KEY``
    is unset, so callers can fall through to another provider.
    """
    settings = get_settings()
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        return None

    base = settings.azure_openai_endpoint.strip().rstrip("/")
    if base.endswith(_V1_SUFFIX):
        return base
    if base.endswith("/openai"):
        return f"{base}/v1"
    return f"{base}{_V1_SUFFIX}"


#: Locale tags where Azure disagrees with the tag the rest of the app uses.
#:
#: The language registry follows Sarvam, which spells Odia ``od-IN``. Azure uses
#: the ISO 639-1 code, ``or-IN``. Azure rejects ``od-IN`` outright, so without
#: this an Odia patient loses the only provider that can actually speak to them —
#: Bulbul cannot voice Odia at all.
_LOCALE_ALIASES = {"od-IN": "or-IN"}
_LOCALE_ALIASES_REVERSE = {v: k for k, v in _LOCALE_ALIASES.items()}


def azure_locale(tag: str) -> str:
    """Translate an app locale tag into the one Azure expects."""
    return _LOCALE_ALIASES.get(tag, tag)


def app_locale(tag: str | None) -> str | None:
    """Translate a locale Azure returned back into the app's spelling."""
    if not tag:
        return tag
    return _LOCALE_ALIASES_REVERSE.get(tag, tag)


def get_speech_credentials() -> tuple[str, str] | None:
    """Return ``(key, region)`` for Azure Speech, or ``None`` if unavailable.

    ``AZURE_SPEECH_KEY`` wins when set. When it is not, the Azure OpenAI key is
    used instead, because a **multi-service** Azure AI Services / Foundry
    resource issues a single key that covers OpenAI, Speech, Vision and Document
    Intelligence alike. Requiring the same secret to be pasted under a second
    name would mean the common case — one Foundry resource for everything — looks
    unconfigured while being perfectly usable.

    The region is not guessable and has no safe default: a key is scoped to the
    region its resource lives in, and using the wrong one returns 401 rather than
    a redirect. ``AZURE_SPEECH_REGION`` therefore has to be right, and
    ``centralindia`` is only the default because that is where an Indian
    deployment belongs — not because it is where any given resource is.

    This is the single source of truth for both ``tts.py`` and ``asr.py``, so
    the two cannot disagree about whether Speech is available.
    """
    settings = get_settings()
    key = (settings.azure_speech_key or settings.azure_openai_api_key or "").strip()
    region = (settings.azure_speech_region or "").strip()
    if not key or not region:
        return None
    return key, region


def get_speech_config():
    """Return an ``azure.cognitiveservices.speech.SpeechConfig``, or ``None``.

    Only for callers that genuinely need the SDK object. The STT and TTS paths
    deliberately do not: they use the REST endpoints over ``httpx`` because the
    SDK's recognizer and synthesizer are synchronous, and calling them from the
    ``async def`` handlers here would block the event loop and stall the
    red-flag path.

    The return type is not annotated to avoid importing the Speech SDK at
    module level — callers should ``import azure.cognitiveservices.speech``
    themselves when they need type information.
    """
    credentials = get_speech_credentials()
    if credentials is None:
        return None
    key, region = credentials

    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        logger.warning(
            "azure_ai: azure-cognitiveservices-speech is not installed. "
            "Run: pip install 'azure-cognitiveservices-speech==1.51.2'"
        )
        return None

    return speechsdk.SpeechConfig(subscription=key, region=region)


def get_doc_intelligence_client() -> DocumentIntelligenceClient | None:
    """Return a ``DocumentIntelligenceClient``, or ``None`` if not configured.

    Requires both ``AZURE_DOC_INTELLIGENCE_ENDPOINT`` and
    ``AZURE_DOC_INTELLIGENCE_KEY`` to be set.
    """
    settings = get_settings()
    if not settings.azure_doc_intelligence_endpoint or not settings.azure_doc_intelligence_key:
        return None

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        logger.warning(
            "azure_ai: azure-ai-documentintelligence is not installed. "
            "Run: pip install 'azure-ai-documentintelligence==1.0.2'"
        )
        return None

    return DocumentIntelligenceClient(
        endpoint=settings.azure_doc_intelligence_endpoint,
        credential=AzureKeyCredential(settings.azure_doc_intelligence_key),
    )
