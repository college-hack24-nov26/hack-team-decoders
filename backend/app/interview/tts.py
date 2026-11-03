"""TTS (Text-to-Speech) for audio question prompts.

Every question prompt the kiosk shows is also spoken aloud. This is not a
nicety: the target user in the problem statement is an elderly or low-literacy
first-time patient, so the audio path is the primary path for them and the text
is the fallback, not the other way round.

``TTS_PROVIDER`` names an ordered chain, not a single provider:

    TTS_PROVIDER=sarvam,azure

Each is tried in turn until one returns audio. That ordering is the point: the
team pools several Sarvam accounts and they run dry one at a time, so when the
last one is spent the kiosk should keep speaking rather than fall silent
mid-interview. A single value still means what it always did — that provider, no
fallback.

===============  ==========================================================
``azure``        Azure Speech neural voices. Auth by ``AZURE_SPEECH_KEY``,
                 falling back to ``AZURE_OPENAI_API_KEY`` because a
                 multi-service Azure AI Services resource issues one key for
                 everything. Needs ``AZURE_SPEECH_REGION`` — a key is scoped
                 to its resource's region and the wrong one returns 401.
                 Returns MP3. Covers all ten interface languages plus Odia,
                 which Bulbul cannot speak at all, so this is the only
                 provider that can voice the full set.
``google``       Google Cloud Text-to-Speech. Auth by API key
                 (``GOOGLE_TTS_API_KEY``) or by service-account JSON
                 (``GOOGLE_APPLICATION_CREDENTIALS`` → path to the .json).
                 Returns MP3.
``sarvam``       Sarvam AI (``SARVAM_API_KEY``). Purpose-built for Indian
                 languages and accents, so it is the default choice for the
                 kiosk's Hindi audio. Returns WAV. ``SARVAM_MODEL`` defaults to
                 ``bulbul:v3`` (2500 chars, 30+ voices). ``bulbul:v2`` is
                 Sarvam-designated legacy and kept only as an escape hatch —
                 self-hosted Sarvam endpoints reject it outright. Speakers are
                 model-specific, so leave ``SARVAM_SPEAKER`` unset to take
                 Sarvam's own per-model default.

                 Note: always feed Devanagari, never romanised Hindi. Sarvam
                 documents that transliterated Indic input ("Aapka order
                 confirm ho gaya hai") measurably degrades output quality.
``none`` / unset Disabled. ``synthesize`` returns None and the UI falls back
                 to text-only. Keeps the app runnable with no credentials.
===============  ==========================================================

Synthesised clips are cached on disk. Question prompts are drawn from a fixed
ontology, so the same few hundred strings repeat for every patient all day —
without a cache we would pay for and wait on an identical API call each time.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

import httpx

from app.interview import languages
from app.services.google_keys import (
    acquire_key as google_acquire_key,
)
from app.services.google_keys import (
    attempt_budget as google_attempt_budget,
)
from app.services.google_keys import (
    report_key_failure as google_report_key_failure,
)
from app.services.google_keys import (
    report_key_success as google_report_key_success,
)
from app.services.sarvam_keys import (
    acquire_key,
    attempt_budget,
    report_key_failure,
    report_key_success,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Ordered provider chain, e.g. ``sarvam,azure``.
#:
#: A list rather than a single name because credits run out mid-demo: the team
#: pools several Sarvam accounts, and when the last one is spent the kiosk should
#: keep speaking rather than fall silent. Ordering is data so the preference can
#: be changed without touching code. A single value still works and means
#: exactly what it always did — that provider and no fallback.
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "none").strip().lower()
TTS_CACHE_DIR = Path(os.getenv("TTS_CACHE_DIR", "tts_cache"))


def _provider_chain() -> list[str]:
    """Providers to try in order, skipping any that are not configured."""
    requested = [p.strip() for p in TTS_PROVIDER.split(",") if p.strip()]
    return [p for p in requested if p != "none" and _provider_configured(p)]


def _provider_configured(provider: str) -> bool:
    """Whether one named provider has what it needs to run."""
    if provider == "azure":
        from app.services.azure_ai import get_speech_credentials

        return get_speech_credentials() is not None
    if provider == "google":
        return bool(GOOGLE_TTS_API_KEY or GOOGLE_CREDENTIALS_PATH or google_acquire_key())
    if provider == "sarvam":
        # Either a single key or a pooled one counts as configured.
        return bool(SARVAM_API_KEY) or bool(acquire_key())
    return False


GOOGLE_TTS_API_KEY = os.getenv("GOOGLE_TTS_API_KEY", "").strip()
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
GOOGLE_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_TTS_ENDPOINT = "https://api.sarvam.ai/text-to-speech"
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "bulbul:v3").strip()
#: Left empty on purpose. Speakers are model-specific and Sarvam already picks a
#: sensible per-model default (``shubh`` for v3, ``anushka`` for v2), so omitting
#: the field is safer than shipping a name that may not exist on the chosen model.
SARVAM_SPEAKER = os.getenv("SARVAM_SPEAKER", "").strip()

#: Google voice names per language. Standard tier: cheap and clear enough.
#: Only the two the interface is translated into — Google is the secondary
#: provider, and Sarvam is what carries the Indic languages.
_GOOGLE_VOICES = {"en-IN": "en-IN-Standard-A", "hi-IN": "hi-IN-Standard-A"}

AZURE_TTS_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"

#: Azure neural voice per locale — female, standard tier.
#:
#: Covers every language the interface is translated into, plus Odia, which
#: Bulbul cannot speak at all. That makes Azure the only provider able to voice
#: the full set, so it is worth keeping this map complete rather than treating
#: Azure as English-and-Hindi cover the way the Google map does.
_AZURE_VOICES = {
    "en-IN": "en-IN-NeerjaNeural",
    "hi-IN": "hi-IN-SwaraNeural",
    "bn-IN": "bn-IN-TanishaaNeural",
    "mr-IN": "mr-IN-AarohiNeural",
    "te-IN": "te-IN-ShrutiNeural",
    "ta-IN": "ta-IN-PallaviNeural",
    "gu-IN": "gu-IN-DhwaniNeural",
    "kn-IN": "kn-IN-SapnaNeural",
    "ml-IN": "ml-IN-SobhanaNeural",
    "pa-IN": "pa-IN-VaaniNeural",
    "or-IN": "or-IN-SubhasiniNeural",
}

#: Per-request character cap, which differs by Sarvam model.
_SARVAM_MAX_CHARS = {"bulbul:v3": 2500, "bulbul:v2": 1500}
_SARVAM_DEFAULT_MAX_CHARS = 1500

#: Valid speakers per model. Sarvam rejects a speaker that belongs to the other
#: model version, so a stale ``SARVAM_SPEAKER`` would 400 every request. The
#: names are case-sensitive and lowercase.
_SARVAM_SPEAKERS = {
    "bulbul:v3": frozenset(
        """shubh aditya ritu priya neha rahul pooja rohan simran kavya amit dev
        ishita shreya ratan varun manan sumit roopa kabir aayan ashutosh advait
        anand tanya tarun sunny mani gokul vijay shruti suhani mohit kavitha
        rehan soham rupali niharika""".split()
    ),
    "bulbul:v2": frozenset("anushka manisha vidya arya abhilash karun hitesh".split()),
}


def is_enabled() -> bool:
    """Whether at least one usable TTS provider is configured."""
    return bool(_provider_chain())


def _bcp47(language: str) -> str:
    """BCP-47 tag to synthesise in, honouring what the provider can actually say.

    Routed through :func:`languages.tts_language` rather than mapped directly,
    because Bulbul v3 speaks 11 of the 23 languages Saaras can transcribe. A
    patient may legitimately have chosen Santali — accepted for speech input —
    and sending ``sat-IN`` here would be rejected, leaving them with silence.
    Falling back to a language they are likely to follow is the lesser harm.
    """
    return languages.get(languages.tts_language(language)).bcp47


#: Container each provider returns, which decides both the cache suffix and the
#: Content-Type the audio route serves.
_PROVIDER_SUFFIX = {"sarvam": ".wav", "azure": ".mp3", "google": ".mp3"}


def _cache_name(text: str, language: str, provider: str) -> str:
    """Content-addressed cache filename for one provider's rendering.

    Keyed on the provider that *served* the clip, not the configured chain.
    Hashing the whole chain instead would mean a clip synthesised by Sarvam and
    one synthesised by Azure as fallback collide on the same filename, so the
    kiosk would serve a Sarvam-voiced clip labelled as MP3 — a file the browser
    refuses to play, with nothing in the logs to say why.
    """
    digest = hashlib.sha256(f"{provider}:{language}:{text}".encode()).hexdigest()[:24]
    return f"{language}_{digest}{_PROVIDER_SUFFIX.get(provider, '.wav')}"


# ---------------------------------------------------------------------------
# Google Cloud Text-to-Speech
# ---------------------------------------------------------------------------


def _google_access_token() -> str:
    """Mint an OAuth2 access token from the service-account JSON.

    Imported lazily so the dependency is only needed by deployments that
    actually authenticate this way; API-key users never hit this path.
    """
    try:
        from google.auth.transport.requests import Request  # type: ignore[import-untyped]
        from google.oauth2 import service_account  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS is set but google-auth is not installed. "
            "Either `pip install google-auth` or use GOOGLE_TTS_API_KEY instead."
        ) from exc

    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials.refresh(Request())
    return str(credentials.token)


async def _synthesize_google(text: str, language: str) -> bytes:
    """Return MP3 bytes from Google Cloud TTS, rotating API keys as quotas run dry.

    Service-account credentials (``GOOGLE_APPLICATION_CREDENTIALS``) are tried
    once and do not rotate — there is only one service account per deployment.
    Key rotation only applies to the API-key path.
    """
    tag = _bcp47(language)
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": tag, "name": _GOOGLE_VOICES.get(tag, _GOOGLE_VOICES["en-IN"])},
        "audioConfig": {"audioEncoding": "MP3"},
    }

    # Service-account path: single identity, no pool rotation.
    if not GOOGLE_TTS_API_KEY and not google_acquire_key(GOOGLE_TTS_API_KEY):
        if GOOGLE_CREDENTIALS_PATH:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_google_access_token()}",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GOOGLE_TTS_ENDPOINT, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
            encoded = body.get("audioContent")
            if not encoded:
                raise RuntimeError("Google TTS response contained no audioContent")
            return base64.b64decode(encoded)
        raise RuntimeError("Google TTS: no API key or credentials configured")

    # API-key path: rotate through the pool on quota / auth failures.
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _attempt in range(google_attempt_budget()):
            key = google_acquire_key(GOOGLE_TTS_API_KEY)
            if key is None:
                raise RuntimeError("Google TTS: no usable API key available")

            response = await client.post(
                GOOGLE_TTS_ENDPOINT,
                params={"key": key},
                headers={"Content-Type": "application/json"},
                json=payload,
            )

            if response.status_code >= 400:
                logger.warning(
                    "tts: Google TTS returned HTTP %s: %s",
                    response.status_code,
                    response.text[:500],
                )
                if google_report_key_failure(
                    key, response.status_code, body=response.text, fallback=GOOGLE_TTS_API_KEY
                ):
                    continue  # another key is available — try it
                response.raise_for_status()

            google_report_key_success(key)
            body = response.json()
            encoded = body.get("audioContent")
            if not encoded:
                raise RuntimeError("Google TTS response contained no audioContent")
            return base64.b64decode(encoded)

    raise RuntimeError("Google TTS: exhausted every key without a response")


# ---------------------------------------------------------------------------
# Sarvam AI
# ---------------------------------------------------------------------------


def _sarvam_speaker() -> str | None:
    """Return a speaker valid for ``SARVAM_MODEL``, or None to use the default.

    A speaker from the wrong model version is rejected outright, so an operator
    who upgrades ``SARVAM_MODEL`` to v3 while leaving a v2 voice like ``anushka``
    configured would lose audio on every question. Dropping the mismatch costs
    the preferred voice; keeping it costs the whole audio path.
    """
    if not SARVAM_SPEAKER:
        return None

    valid = _SARVAM_SPEAKERS.get(SARVAM_MODEL)
    if valid and SARVAM_SPEAKER.lower() not in valid:
        logger.warning(
            "tts: speaker %r is not available on %s; falling back to the model "
            "default. Valid speakers: %s",
            SARVAM_SPEAKER,
            SARVAM_MODEL,
            ", ".join(sorted(valid)),
        )
        return None
    return SARVAM_SPEAKER.lower()


async def _synthesize_sarvam(text: str, language: str) -> bytes:
    """Return WAV bytes from Sarvam AI, rotating keys as accounts run dry."""
    limit = _SARVAM_MAX_CHARS.get(SARVAM_MODEL, _SARVAM_DEFAULT_MAX_CHARS)
    payload: dict = {
        "text": text[:limit],
        "language_code": _bcp47(language),
        "model": SARVAM_MODEL,
    }

    speaker = _sarvam_speaker()
    if speaker:
        payload["speaker"] = speaker

    # v2 needs to be told to normalise numbers and English words inside Hindi
    # text, which is exactly what these prompts are (e.g. "1 से 10 में").
    # v3 does it natively and rejects the parameter.
    if SARVAM_MODEL == "bulbul:v2":
        payload["enable_preprocessing"] = True

    body: dict | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for _attempt in range(attempt_budget()):
            key = acquire_key(SARVAM_API_KEY)
            if key is None:
                raise RuntimeError("Sarvam TTS: no usable API key available")

            response = await client.post(
                SARVAM_TTS_ENDPOINT,
                headers={"api-subscription-key": key, "Content-Type": "application/json"},
                json=payload,
            )

            if response.status_code >= 400:
                # synthesize() swallows exceptions by design, so without the body
                # here a rejected parameter or bad speaker is undiagnosable.
                logger.warning(
                    "tts: Sarvam returned HTTP %s (model=%s): %s",
                    response.status_code,
                    SARVAM_MODEL,
                    response.text[:500],
                )
                if report_key_failure(key, response.status_code, fallback=SARVAM_API_KEY):
                    continue  # a teammate's key is still good — try it
                response.raise_for_status()

            report_key_success(key)
            body = response.json()
            break

    if body is None:  # pragma: no cover - loop either breaks or raises
        raise RuntimeError("Sarvam TTS: exhausted every key without a response")

    audios = body.get("audios") or []
    if not audios:
        raise RuntimeError("Sarvam TTS response contained no audios")
    return base64.b64decode(audios[0])


# ---------------------------------------------------------------------------
# Azure Speech Services
# ---------------------------------------------------------------------------


def _azure_voice(language: str) -> tuple[str, str]:
    """Return ``(bcp47_tag, voice_name)`` Azure should speak in.

    Deliberately not routed through :func:`languages.tts_language`, which exists
    to keep requests inside what *Bulbul* can say. Azure's coverage is wider —
    Odia being the clearest case — so borrowing Sarvam's ceiling here would make
    an Odia speaker hear Hindi from a provider perfectly capable of Odia.
    """
    from app.services.azure_ai import azure_locale

    tag = azure_locale(languages.get(language).bcp47)
    if tag in _AZURE_VOICES:
        return tag, _AZURE_VOICES[tag]

    # Unknown to Azure as well: fall back the same way Sarvam does, so the
    # patient hears a language they are likely to follow rather than silence.
    fallback = azure_locale(languages.get(languages.tts_language(language)).bcp47)
    return fallback, _AZURE_VOICES.get(fallback, _AZURE_VOICES["en-IN"])


def _ssml(text: str, tag: str, voice: str) -> str:
    """Wrap text in the SSML document the REST endpoint requires.

    Escaped, because the prompts contain clinical copy and an unescaped ``&`` or
    ``<`` would make the whole document invalid and 400 the request.
    """
    from xml.sax.saxutils import escape

    return (
        f"<speak version='1.0' xml:lang='{tag}'>"
        f"<voice xml:lang='{tag}' name='{voice}'>{escape(text)}</voice>"
        f"</speak>"
    )


async def _synthesize_azure(text: str, language: str) -> bytes:
    """Return MP3 bytes from Azure Speech.

    Uses the REST endpoint over httpx rather than the Speech SDK, because the
    SDK's ``SpeechSynthesizer`` is synchronous and this coroutine runs on the
    request loop — a blocking call here would stall every other request,
    including the red-flag path.
    """
    from app.services.azure_ai import get_speech_credentials

    credentials = get_speech_credentials()
    if credentials is None:
        raise RuntimeError(
            "Azure TTS selected but not configured. Set AZURE_SPEECH_REGION, and "
            "either AZURE_SPEECH_KEY or AZURE_OPENAI_API_KEY (a multi-service "
            "Azure AI Services resource shares one key)."
        )
    key, region = credentials
    tag, voice = _azure_voice(language)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": AZURE_TTS_OUTPUT_FORMAT,
                # Azure documents User-Agent as required and rejects requests
                # without one.
                "User-Agent": "MediKiosk",
            },
            content=_ssml(text, tag, voice).encode("utf-8"),
        )

        if response.status_code >= 400:
            # synthesize() swallows exceptions by design, so without the body
            # here a wrong voice name or region is undiagnosable.
            logger.warning(
                "tts: Azure returned HTTP %s (region=%s, voice=%s): %s",
                response.status_code,
                region,
                voice,
                response.text[:500],
            )
            response.raise_for_status()

    if not response.content:
        raise RuntimeError("Azure TTS returned an empty body")
    return response.content


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def synthesize(text: str, language: str = "en") -> str | None:
    """Return the cache filename of spoken ``text``, or None if unavailable.

    The filename (not a path) is returned so the caller can build a URL against
    the audio route without leaking the cache directory layout.

    Providers are tried in the order ``TTS_PROVIDER`` names them, so a spent
    Sarvam account falls through to Azure instead of costing the patient the
    audio path entirely.

    Never raises. A TTS outage must not take the interview down with it: the
    patient can still read the question and answer by touch, so a failure here
    degrades the experience rather than blocking care.
    """
    if not text.strip():
        return None

    chain = _provider_chain()
    if not chain:
        return None

    # A clip already rendered by any provider in the chain is good enough — the
    # point of the cache is not paying twice for the same sentence, and it does
    # not matter which voice got there first.
    for provider in chain:
        name = _cache_name(text, language, provider)
        path = TTS_CACHE_DIR / name
        if path.exists() and path.stat().st_size > 0:
            return name

    for provider in chain:
        try:
            if provider == "azure":
                audio = await _synthesize_azure(text, language)
            elif provider == "google":
                audio = await _synthesize_google(text, language)
            elif provider == "sarvam":
                audio = await _synthesize_sarvam(text, language)
            else:  # pragma: no cover - filtered by _provider_chain()
                continue
        except Exception:
            # Logged, not raised. See the docstring. The next provider in the
            # chain gets a turn; only the last failure leaves the patient
            # without audio.
            logger.warning(
                "tts: synthesis failed (provider=%s, lang=%s)",
                provider,
                language,
                exc_info=True,
            )
            continue

        if not audio:
            logger.warning("tts: %s returned empty audio (lang=%s)", provider, language)
            continue

        name = _cache_name(text, language, provider)
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (TTS_CACHE_DIR / name).write_bytes(audio)
        return name

    logger.warning("tts: every provider in the chain failed (%s)", ", ".join(chain))
    return None


def cached_path(name: str) -> Path | None:
    """Resolve a cache filename to a path, or None if it escapes the cache dir.

    The name arrives from a URL, so it is untrusted. Rejecting anything whose
    resolved parent is not the cache directory is what stops
    ``../../etc/passwd`` from being served.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None

    cache_root = TTS_CACHE_DIR.resolve()
    candidate = (cache_root / name).resolve()

    if candidate.parent != cache_root or not candidate.is_file():
        return None
    return candidate


def media_type_for(name: str) -> str:
    return "audio/mpeg" if name.endswith(".mp3") else "audio/wav"
