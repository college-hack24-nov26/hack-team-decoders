"""Tests for the TTS provider layer.

The provider HTTP calls are exercised against a stubbed transport rather than the
real APIs, so these run offline and in CI. What they pin is the request shape and
the response decoding for each provider — the two things that silently break when
a vendor changes their contract.
"""

import base64
import json

import httpx
import pytest

from app.interview import tts


@pytest.fixture(autouse=True)
def _clean_cache(tmp_path, monkeypatch):
    """Point the cache at a temp dir so tests never touch the real one."""
    monkeypatch.setattr(tts, "TTS_CACHE_DIR", tmp_path / "tts_cache")
    yield


def _stub_transport(capture: dict) -> httpx.MockTransport:
    """A transport that records the outgoing request and returns fake audio."""

    def handler(request: httpx.Request) -> httpx.Response:
        capture["url"] = str(request.url)
        capture["headers"] = dict(request.headers)
        capture["body"] = request.read().decode()

        fake_audio = base64.b64encode(b"FAKE_AUDIO_BYTES").decode()
        if "sarvam" in str(request.url):
            return httpx.Response(200, json={"request_id": "r1", "audios": [fake_audio]})
        return httpx.Response(200, json={"audioContent": fake_audio})

    return httpx.MockTransport(handler)


@pytest.fixture()
def stubbed_http(monkeypatch):
    """Route httpx.AsyncClient through the stub transport."""
    capture: dict = {}
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = _stub_transport(capture)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return capture


class TestProviderSelection:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "none")
        assert tts.is_enabled() is False

    def test_google_needs_a_credential(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "google")
        monkeypatch.setattr(tts, "GOOGLE_TTS_API_KEY", "")
        monkeypatch.setattr(tts, "GOOGLE_CREDENTIALS_PATH", "")
        assert tts.is_enabled() is False

        monkeypatch.setattr(tts, "GOOGLE_TTS_API_KEY", "test-key")
        assert tts.is_enabled() is True

    def test_sarvam_needs_a_key(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "")
        assert tts.is_enabled() is False

        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")
        assert tts.is_enabled() is True

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "none")
        assert await tts.synthesize("hello", "en") is None


class TestGoogleProvider:
    @pytest.mark.asyncio
    async def test_request_shape_and_mp3_decoding(self, monkeypatch, stubbed_http):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "google")
        monkeypatch.setattr(tts, "GOOGLE_TTS_API_KEY", "test-key")
        monkeypatch.setattr(tts, "GOOGLE_CREDENTIALS_PATH", "")

        name = await tts.synthesize("आपको बुखार है?", "hi")

        assert name is not None
        assert name.endswith(".mp3"), "Google returns MP3"
        assert name.startswith("hi_")

        # API key travels as a query param, not a header.
        assert "key=test-key" in stubbed_http["url"]
        assert "texttospeech.googleapis.com" in stubbed_http["url"]
        # Hindi must map to the BCP-47 tag and a matching voice.
        assert '"languageCode": "hi-IN"' in stubbed_http["body"]
        assert "hi-IN-Standard-A" in stubbed_http["body"]
        assert '"audioEncoding": "MP3"' in stubbed_http["body"]

        # The base64 payload was decoded to bytes on disk.
        assert tts.cached_path(name).read_bytes() == b"FAKE_AUDIO_BYTES"

    @pytest.mark.asyncio
    async def test_second_call_is_served_from_cache(self, monkeypatch, stubbed_http):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "google")
        monkeypatch.setattr(tts, "GOOGLE_TTS_API_KEY", "test-key")
        monkeypatch.setattr(tts, "GOOGLE_CREDENTIALS_PATH", "")

        first = await tts.synthesize("Where is the pain?", "en")
        stubbed_http.clear()
        second = await tts.synthesize("Where is the pain?", "en")

        assert first == second
        assert stubbed_http == {}, "cache hit must not call the API again"


class TestSarvamProvider:
    """Sarvam is the kiosk's default voice provider (Indic languages/accents).

    bulbul:v3 and v2 take different parameters, so most of what is asserted here
    is the difference between them. Sending a v2-only field or a v2 speaker to v3
    is rejected outright, which would silence the whole audio path.
    """

    @pytest.fixture(autouse=True)
    def _use_sarvam(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

    @pytest.mark.asyncio
    async def test_request_shape_and_wav_decoding(self, monkeypatch, stubbed_http):
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v3")
        monkeypatch.setattr(tts, "SARVAM_SPEAKER", "")

        name = await tts.synthesize("आपको बुखार है?", "hi")

        assert name is not None
        assert name.endswith(".wav"), "Sarvam returns WAV"

        assert stubbed_http["url"] == tts.SARVAM_TTS_ENDPOINT
        # Sarvam authenticates with its own header, not Bearer.
        assert stubbed_http["headers"]["api-subscription-key"] == "sk-test"

        sent = json.loads(stubbed_http["body"])
        assert sent["language_code"] == "hi-IN"
        assert sent["model"] == "bulbul:v3"
        # Unset speaker must be omitted so Sarvam applies its own per-model
        # default, rather than us guessing a name that may not exist on v3.
        assert "speaker" not in sent
        # v3 normalises numbers natively and rejects this parameter.
        assert "enable_preprocessing" not in sent

        assert tts.cached_path(name).read_bytes() == b"FAKE_AUDIO_BYTES"

    @pytest.mark.asyncio
    async def test_v2_still_gets_its_preprocessing_flag(self, monkeypatch, stubbed_http):
        """v2 has to be told to normalise "1 से 10 में"; v3 does it for free."""
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v2")
        monkeypatch.setattr(tts, "SARVAM_SPEAKER", "")

        await tts.synthesize("1 से 10 में", "hi")

        sent = json.loads(stubbed_http["body"])
        assert sent["model"] == "bulbul:v2"
        assert sent["enable_preprocessing"] is True

    @pytest.mark.asyncio
    async def test_char_limit_follows_the_model(self, monkeypatch, stubbed_http):
        """Over-long text is clipped, not sent whole and rejected."""
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v3")

        await tts.synthesize("क" * 4000, "hi")
        assert len(json.loads(stubbed_http["body"])["text"]) == 2500

        stubbed_http.clear()
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v2")
        await tts.synthesize("ख" * 4000, "hi")
        assert len(json.loads(stubbed_http["body"])["text"]) == 1500

    @pytest.mark.asyncio
    async def test_configured_speaker_is_sent_lowercased(self, monkeypatch, stubbed_http):
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v3")
        monkeypatch.setattr(tts, "SARVAM_SPEAKER", "Ritu")

        await tts.synthesize("नमस्ते", "hi")

        # Sarvam speaker names are case-sensitive and must be lowercase.
        assert json.loads(stubbed_http["body"])["speaker"] == "ritu"

    @pytest.mark.asyncio
    async def test_speaker_from_the_wrong_model_is_dropped(self, monkeypatch, stubbed_http):
        """The upgrade trap: anushka is a v2 voice and 400s on v3.

        Losing the preferred voice is recoverable; losing all audio is not, since
        the audio path is the primary one for a low-literacy patient.
        """
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v3")
        monkeypatch.setattr(tts, "SARVAM_SPEAKER", "anushka")

        name = await tts.synthesize("नमस्ते", "hi")

        assert name is not None, "must still produce audio"
        assert "speaker" not in json.loads(stubbed_http["body"])

    @pytest.mark.asyncio
    async def test_valid_v2_speaker_is_kept_on_v2(self, monkeypatch, stubbed_http):
        monkeypatch.setattr(tts, "SARVAM_MODEL", "bulbul:v2")
        monkeypatch.setattr(tts, "SARVAM_SPEAKER", "anushka")

        await tts.synthesize("नमस्ते", "hi")

        assert json.loads(stubbed_http["body"])["speaker"] == "anushka"


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_provider_error_degrades_to_text_only(self, monkeypatch):
        """A TTS outage must not take the interview down with it."""
        monkeypatch.setattr(tts, "TTS_PROVIDER", "google")
        monkeypatch.setattr(tts, "GOOGLE_TTS_API_KEY", "test-key")
        monkeypatch.setattr(tts, "GOOGLE_CREDENTIALS_PATH", "")

        original = httpx.AsyncClient

        def failing(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(
                lambda request: httpx.Response(500, text="upstream exploded")
            )
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", failing)

        # No exception; the caller just gets no audio.
        assert await tts.synthesize("Where is the pain?", "en") is None

    @pytest.mark.asyncio
    async def test_empty_text_is_not_sent(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "google")
        monkeypatch.setattr(tts, "GOOGLE_TTS_API_KEY", "test-key")
        assert await tts.synthesize("   ", "en") is None


class TestCacheKeying:
    def test_language_and_provider_both_affect_the_key(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "google")
        en_name = tts._cache_name("Same text", "en", ".mp3")
        hi_name = tts._cache_name("Same text", "hi", ".mp3")
        assert en_name != hi_name, "same text in two languages must not collide"

        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam")
        sarvam_name = tts._cache_name("Same text", "en", ".wav")
        assert (
            sarvam_name != en_name
        ), "switching provider must not serve clips in the old provider's voice"


# ---------------------------------------------------------------------------
# Azure Speech + the provider chain (task A3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def azure_configured(monkeypatch):
    """Pretend a multi-service Azure resource is available in eastus2."""
    from app.services import azure_ai

    monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: ("az-key", "eastus2"))
    return "az-key", "eastus2"


@pytest.fixture()
def azure_http(monkeypatch):
    """Transport returning raw MP3 bytes, as the Azure TTS endpoint does."""
    capture: dict = {}
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        capture["url"] = str(request.url)
        capture["headers"] = dict(request.headers)
        capture["body"] = request.read().decode()
        return httpx.Response(200, content=b"FAKE_MP3_BYTES")

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return capture


class TestAzureVoiceSelection:
    def test_each_interface_language_has_a_voice(self):
        """All ten translated languages, so Azure can carry the whole set."""
        for tag in (
            "en-IN",
            "hi-IN",
            "bn-IN",
            "mr-IN",
            "te-IN",
            "ta-IN",
            "gu-IN",
            "kn-IN",
            "ml-IN",
            "pa-IN",
        ):
            assert tag in tts._AZURE_VOICES

    def test_odia_is_not_downgraded(self):
        """Bulbul cannot speak Odia; Azure can, so the Sarvam ceiling must not
        be borrowed here. Routing this through tts_language() would make an Odia
        speaker hear Hindi from a provider perfectly capable of Odia.

        Note the tag translation: the registry follows Sarvam and spells Odia
        ``od-IN``, while Azure wants ISO ``or-IN`` and rejects ``od-IN``.
        """
        tag, voice = tts._azure_voice("od")

        assert tag == "or-IN"
        assert voice == "or-IN-SubhasiniNeural"

    def test_a_language_azure_cannot_speak_falls_back(self):
        tag, voice = tts._azure_voice("sat")

        assert tag in tts._AZURE_VOICES
        assert voice == tts._AZURE_VOICES[tag]


class TestSsml:
    def test_wraps_text_with_the_voice(self):
        doc = tts._ssml("Namaste", "hi-IN", "hi-IN-SwaraNeural")

        assert "xml:lang='hi-IN'" in doc
        assert "name='hi-IN-SwaraNeural'" in doc
        assert "Namaste" in doc

    def test_escapes_markup_characters(self):
        """An unescaped & or < makes the whole document invalid and 400s."""
        doc = tts._ssml("BP < 120 & rising", "en-IN", "en-IN-NeerjaNeural")

        assert "&lt;" in doc and "&amp;" in doc
        assert "< 120" not in doc


class TestAzureSynthesis:
    @pytest.mark.asyncio
    async def test_request_shape(self, monkeypatch, azure_configured, azure_http):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "azure")

        audio = await tts._synthesize_azure("Namaste", "hi")

        assert audio == b"FAKE_MP3_BYTES"
        assert azure_http["url"] == (
            "https://eastus2.tts.speech.microsoft.com/cognitiveservices/v1"
        )
        headers = azure_http["headers"]
        assert headers["ocp-apim-subscription-key"] == "az-key"
        assert headers["content-type"] == "application/ssml+xml"
        assert headers["x-microsoft-outputformat"] == tts.AZURE_TTS_OUTPUT_FORMAT
        # Azure documents User-Agent as required and rejects requests without one.
        assert headers["user-agent"] == "MediKiosk"
        assert "hi-IN-SwaraNeural" in azure_http["body"]

    @pytest.mark.asyncio
    async def test_unconfigured_raises_with_a_usable_message(self, monkeypatch):
        from app.services import azure_ai

        monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: None)

        with pytest.raises(RuntimeError, match="AZURE_SPEECH_REGION"):
            await tts._synthesize_azure("hello", "en")

    @pytest.mark.asyncio
    async def test_an_empty_body_is_an_error_not_silence(self, monkeypatch, azure_configured):
        """A zero-byte clip would be cached and served forever as valid audio."""
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"")
            )
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        with pytest.raises(RuntimeError, match="empty"):
            await tts._synthesize_azure("hello", "en")


class TestProviderChain:
    def test_a_single_provider_has_no_fallback(self, monkeypatch):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        assert tts._provider_chain() == ["sarvam"]

    def test_a_comma_list_becomes_an_ordered_chain(self, monkeypatch, azure_configured):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        assert tts._provider_chain() == ["sarvam", "azure"]

    def test_whitespace_is_tolerated(self, monkeypatch, azure_configured):
        monkeypatch.setattr(tts, "TTS_PROVIDER", " sarvam , azure ")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        assert tts._provider_chain() == ["sarvam", "azure"]

    def test_unconfigured_providers_are_dropped(self, monkeypatch):
        """Naming Azure without a region should not cost a wasted round trip."""
        from app.services import azure_ai

        monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: None)
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        assert tts._provider_chain() == ["sarvam"]

    def test_enabled_when_any_provider_is_usable(self, monkeypatch, azure_configured):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "")

        assert tts.is_enabled() is True


class TestChainFailover:
    @pytest.mark.asyncio
    async def test_azure_serves_when_sarvam_is_spent(
        self, monkeypatch, azure_configured, azure_http
    ):
        """The whole point of the chain: a drained account must not cost the
        patient the audio path."""
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        async def spent(text, language):
            raise RuntimeError("402 No credits available")

        monkeypatch.setattr(tts, "_synthesize_sarvam", spent)

        name = await tts.synthesize("Namaste", "hi")

        assert name is not None
        # Served by Azure, so it must be labelled MP3 or the browser refuses it.
        assert name.endswith(".mp3")
        assert (tts.TTS_CACHE_DIR / name).read_bytes() == b"FAKE_MP3_BYTES"

    @pytest.mark.asyncio
    async def test_returns_none_when_every_provider_fails(self, monkeypatch, azure_configured):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        async def boom(text, language):
            raise RuntimeError("down")

        monkeypatch.setattr(tts, "_synthesize_sarvam", boom)
        monkeypatch.setattr(tts, "_synthesize_azure", boom)

        assert await tts.synthesize("Namaste", "hi") is None

    @pytest.mark.asyncio
    async def test_an_empty_clip_falls_through_rather_than_being_cached(
        self, monkeypatch, azure_configured, azure_http
    ):
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        async def silent(text, language):
            return b""

        monkeypatch.setattr(tts, "_synthesize_sarvam", silent)

        name = await tts.synthesize("Namaste", "hi")

        assert name is not None and name.endswith(".mp3")


class TestCacheNaming:
    def test_keyed_on_the_serving_provider(self):
        """Sarvam and Azure renderings of the same sentence must not collide.

        Hashing the configured chain instead would let a Sarvam-voiced WAV be
        served under an Azure MP3 filename — a file the browser refuses to play,
        with nothing in the logs to explain it.
        """
        sarvam = tts._cache_name("Namaste", "hi", "sarvam")
        azure = tts._cache_name("Namaste", "hi", "azure")

        assert sarvam != azure
        assert sarvam.endswith(".wav")
        assert azure.endswith(".mp3")

    def test_suffix_matches_the_served_media_type(self):
        assert tts.media_type_for(tts._cache_name("x", "hi", "azure")) == "audio/mpeg"
        assert tts.media_type_for(tts._cache_name("x", "hi", "sarvam")) == "audio/wav"

    @pytest.mark.asyncio
    async def test_a_cached_clip_from_any_chain_member_is_reused(
        self, monkeypatch, azure_configured
    ):
        """The point of the cache is not paying twice for the same sentence; it
        does not matter which voice got there first."""
        monkeypatch.setattr(tts, "TTS_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(tts, "SARVAM_API_KEY", "sk-test")

        cached = tts._cache_name("Namaste", "hi", "azure")
        tts.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (tts.TTS_CACHE_DIR / cached).write_bytes(b"ALREADY_THERE")

        async def must_not_run(text, language):
            raise AssertionError("cache hit should have short-circuited synthesis")

        monkeypatch.setattr(tts, "_synthesize_sarvam", must_not_run)
        monkeypatch.setattr(tts, "_synthesize_azure", must_not_run)

        assert await tts.synthesize("Namaste", "hi") == cached


class TestSpeechCredentials:
    def test_falls_back_to_the_openai_key(self, monkeypatch):
        """A multi-service Azure AI Services resource issues ONE key covering
        OpenAI, Speech, Vision and Document Intelligence. Requiring the same
        secret under a second name would make the common case look unconfigured.
        """
        from app.core.config import Settings
        from app.services import azure_ai

        settings = Settings(
            azure_speech_key="",
            azure_openai_api_key="shared-key",
            azure_speech_region="eastus2",
        )
        monkeypatch.setattr(azure_ai, "get_settings", lambda: settings)

        assert azure_ai.get_speech_credentials() == ("shared-key", "eastus2")

    def test_an_explicit_speech_key_wins(self, monkeypatch):
        from app.core.config import Settings
        from app.services import azure_ai

        settings = Settings(
            azure_speech_key="speech-key",
            azure_openai_api_key="openai-key",
            azure_speech_region="centralindia",
        )
        monkeypatch.setattr(azure_ai, "get_settings", lambda: settings)

        assert azure_ai.get_speech_credentials() == ("speech-key", "centralindia")

    def test_no_region_means_unavailable(self, monkeypatch):
        """A key is scoped to its resource's region and the wrong one returns
        401, so there is no safe default to guess."""
        from app.core.config import Settings
        from app.services import azure_ai

        settings = Settings(azure_openai_api_key="k", azure_speech_region="")
        monkeypatch.setattr(azure_ai, "get_settings", lambda: settings)

        assert azure_ai.get_speech_credentials() is None
