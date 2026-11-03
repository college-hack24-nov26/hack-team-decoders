"""ASR provider selection and the Sarvam Saaras transcription path.

Provider calls run against a stubbed transport, so these execute offline and in
CI. What they pin is the request shape and the response decoding — the two
things that break silently when a vendor changes their contract.
"""

import io

import httpx
import pytest

from app.interview import asr

_SARVAM_OK = {
    "request_id": "req-123",
    "transcript": "सीने में दर्द हो रहा है",
    "language_code": "hi-IN",
    "language_probability": 0.98,
}


def _audio() -> io.BytesIO:
    return io.BytesIO(b"FAKE_AUDIO_BYTES")


@pytest.fixture()
def captured(monkeypatch):
    """Capture the outbound transcription request instead of performing it."""
    seen: dict = {}
    status = {"code": 200, "json": _SARVAM_OK}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        # Multipart body: assert on the decoded text rather than parsing it.
        seen["body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(status["code"], json=status["json"])

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    seen["_control"] = status
    return seen


@pytest.fixture(autouse=True)
def _neutral_env(monkeypatch):
    """Start every test with no provider configured."""
    monkeypatch.setattr(asr, "ASR_PROVIDER", "")
    monkeypatch.setattr(asr, "SARVAM_API_KEY", "")
    monkeypatch.setattr(asr, "WHISPER_API_URL", "")
    monkeypatch.setattr(asr, "_is_azure_configured", lambda: False)


class TestProviderResolution:
    def test_nothing_configured_is_mock(self):
        assert asr._resolve_chain() == ["mock"]

    def test_sarvam_first_by_default(self, monkeypatch):
        """Sarvam first: it handles Indic and code-mixed speech best."""
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        monkeypatch.setattr(asr, "WHISPER_API_URL", "https://whisper.example/v1")
        assert asr._resolve_chain()[0] == "sarvam"

    def test_whisper_used_when_only_whisper_configured(self, monkeypatch):
        monkeypatch.setattr(asr, "WHISPER_API_URL", "https://whisper.example/v1")
        assert asr._resolve_chain() == ["whisper", "mock"]

    def test_azure_used_when_only_azure_configured(self, monkeypatch):
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
        assert asr._resolve_chain() == ["azure", "mock"]

    @pytest.mark.parametrize("pinned", ["sarvam", "whisper", "azure"])
    def test_explicit_provider_overrides_detection(self, monkeypatch, pinned):
        """A stray key must not decide the provider for a deployment."""
        monkeypatch.setattr(asr, "ASR_PROVIDER", pinned)
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        monkeypatch.setattr(asr, "WHISPER_API_URL", "https://whisper.example/v1")
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
        assert asr._resolve_chain() == [pinned, "mock"]

    def test_unrecognised_provider_falls_back_to_detection(self, monkeypatch):
        monkeypatch.setattr(asr, "ASR_PROVIDER", "nonsense")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        assert asr._resolve_chain()[0] == "sarvam"

    def test_mock_is_always_the_last_rung(self, monkeypatch):
        """A failed transcription must never end the interview."""
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
        assert asr._resolve_chain() == ["sarvam", "azure", "mock"]

    def test_an_unconfigured_provider_is_dropped_from_the_chain(self, monkeypatch):
        """Naming Azure without a region should not cost a wasted round trip."""
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: False)
        assert asr._resolve_chain() == ["sarvam", "mock"]

    def test_whitespace_in_the_chain_is_tolerated(self, monkeypatch):
        monkeypatch.setattr(asr, "ASR_PROVIDER", " sarvam , azure ")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
        assert asr._resolve_chain() == ["sarvam", "azure", "mock"]


class TestLanguageMapping:
    @pytest.mark.parametrize(
        ("short", "expected"),
        [("hi", "hi-IN"), ("en", "en-IN")],
    )
    def test_short_codes_become_bcp47(self, short, expected):
        assert asr._to_bcp47(short) == expected

    def test_no_language_asks_sarvam_to_autodetect(self):
        """A patient may answer in either language; let the model decide."""
        assert asr._to_bcp47(None) == "unknown"

    @pytest.mark.parametrize(
        ("short", "expected"),
        [
            ("ta", "ta-IN"),
            ("bn", "bn-IN"),
            ("sat", "sat-IN"),
            ("mni", "mni-IN"),
            ("ur", "ur-IN"),
        ],
    )
    def test_indian_languages_map_to_their_own_tag(self, short, expected):
        """Saaras covers all 22 scheduled languages, not just English and Hindi."""
        assert asr._to_bcp47(short) == expected

    def test_unrecognised_language_autodetects_rather_than_guessing(self):
        """A code we have never heard of is likelier unlisted than unsupported."""
        assert asr._to_bcp47("xx") == "unknown"

    def test_returned_tag_maps_back_to_a_short_code(self):
        assert asr._to_short_lang("hi-IN", "en") == "hi"

    def test_missing_tag_uses_the_fallback(self):
        assert asr._to_short_lang(None, "hi") == "hi"


class TestSarvamTranscription:
    @pytest.fixture(autouse=True)
    def _use_sarvam(self, monkeypatch):
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        monkeypatch.setattr(asr, "SARVAM_STT_MODEL", "saaras:v3")
        monkeypatch.setattr(asr, "SARVAM_STT_MODE", "transcribe")

    @pytest.mark.asyncio
    async def test_request_shape_and_transcript_parsing(self, captured):
        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert captured["url"] == asr.SARVAM_STT_ENDPOINT
        # Sarvam authenticates with its own header, not Bearer.
        assert captured["headers"]["api-subscription-key"] == "sk-test"
        assert "multipart/form-data" in captured["headers"]["content-type"]

        body = captured["body"]
        assert 'name="model"' in body and "saaras:v3" in body
        assert 'name="language_code"' in body and "hi-IN" in body
        assert 'name="mode"' in body and "transcribe" in body
        assert "FAKE_AUDIO_BYTES" in body, "audio must actually be uploaded"

        assert result.text == "सीने में दर्द हो रहा है"
        assert result.language == "hi"
        assert result.is_mock is False

    @pytest.mark.asyncio
    async def test_mode_is_omitted_for_non_v3_models(self, monkeypatch, captured):
        """`mode` is only honoured by saaras:v3; sending it elsewhere risks a 400."""
        monkeypatch.setattr(asr, "SARVAM_STT_MODEL", "saaras:v4")

        await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        body = captured["body"]
        assert 'name="model"' in body and "saaras:v4" in body
        assert 'name="mode"' not in body

    @pytest.mark.asyncio
    async def test_no_language_hint_requests_autodetection(self, captured):
        await asr.transcribe_audio(_audio(), "answer.webm", None)
        assert "unknown" in captured["body"]

    @pytest.mark.asyncio
    async def test_detected_language_overrides_the_hint(self, captured):
        """Patient asked for English but answered in Hindi — trust the audio."""
        result = await asr.transcribe_audio(_audio(), "answer.webm", "en")
        assert result.language == "hi"

    @pytest.mark.asyncio
    async def test_empty_transcript_is_not_treated_as_a_mock(self, captured):
        captured["_control"]["json"] = {"transcript": "", "language_code": "hi-IN"}

        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert result.text == ""
        assert result.is_mock is False


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_provider_error_degrades_to_mock(self, monkeypatch, captured):
        """A failed transcription must not end the interview.

        The text prompt is always on screen and the patient can answer by touch,
        so a dead ASR provider is a degraded experience, not a blocked one.
        """
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")
        captured["_control"]["code"] = 500
        captured["_control"]["json"] = {"error": "boom"}

        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert result.is_mock is True
        assert result.confidence == 0.0
        assert "[Mock ASR]" in result.text

    @pytest.mark.asyncio
    async def test_mock_mode_names_the_recommended_provider(self):
        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert result.is_mock is True
        assert "SARVAM_API_KEY" in result.text

    @pytest.mark.asyncio
    async def test_stream_is_rewound_before_upload(self, monkeypatch, captured):
        """A consumed stream would upload zero bytes and "succeed" empty."""
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")

        audio = _audio()
        audio.read()  # exhaust it, as a failed earlier attempt would

        await asr.transcribe_audio(audio, "answer.webm", "hi")

        assert "FAKE_AUDIO_BYTES" in captured["body"]

    def test_rewind_tolerates_a_non_seekable_stream(self):
        class NotSeekable:
            def seek(self, *_args):
                raise OSError("pipe")

        asr._rewind(NotSeekable())  # must not raise


# ---------------------------------------------------------------------------
# Azure Speech Fast Transcription (task A3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def azure_asr(monkeypatch):
    """Configure Azure and capture the outbound transcription request."""
    from app.services import azure_ai

    monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: ("az-key", "eastus2"))
    # The module-level autouse fixture pins this False for the detection tests.
    monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
    monkeypatch.setattr(asr, "ASR_PROVIDER", "azure")

    capture: dict = {}
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        capture["url"] = str(request.url)
        capture["headers"] = dict(request.headers)
        capture["body"] = request.read().decode("utf-8", errors="replace")
        return httpx.Response(
            200,
            json={
                "durationMilliseconds": 2400,
                "combinedPhrases": [{"text": "सीने में दर्द हो रहा है"}],
                "phrases": [{"locale": "hi-IN", "text": "सीने में दर्द हो रहा है", "confidence": 0.94}],
            },
        )

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return capture


class TestAzureTranscription:
    @pytest.mark.asyncio
    async def test_request_shape_and_transcript_parsing(self, azure_asr):
        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert "eastus2.api.cognitive.microsoft.com" in azure_asr["url"]
        assert "transcriptions:transcribe" in azure_asr["url"]
        assert f"api-version={asr.AZURE_STT_API_VERSION}" in azure_asr["url"]
        assert azure_asr["headers"]["ocp-apim-subscription-key"] == "az-key"

        body = azure_asr["body"]
        assert 'name="definition"' in body and "hi-IN" in body
        assert "FAKE_AUDIO_BYTES" in body, "audio must actually be uploaded"

        assert result.text == "सीने में दर्द हो रहा है"
        assert result.language == "hi"
        assert result.is_mock is False

    @pytest.mark.asyncio
    async def test_unknown_language_sends_candidates_for_identification(self, azure_asr):
        """Azure identifies the language from the candidates it is given, so the
        list has to be supplied rather than left blank."""
        await asr.transcribe_audio(_audio(), "answer.webm", None)

        body = azure_asr["body"]
        assert "en-IN" in body and "hi-IN" in body and "ta-IN" in body

    @pytest.mark.asyncio
    async def test_detected_locale_overrides_the_hint(self, azure_asr):
        """Patient asked for English but answered in Hindi — trust the audio."""
        result = await asr.transcribe_audio(_audio(), "answer.webm", "en")

        assert result.language == "hi"

    @pytest.mark.asyncio
    async def test_an_empty_result_is_not_a_crash(self, monkeypatch):
        from app.services import azure_ai

        monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: ("az-key", "eastus2"))
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
        monkeypatch.setattr(asr, "ASR_PROVIDER", "azure")

        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(
                lambda request: httpx.Response(200, json={"combinedPhrases": []})
            )
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert result.text == ""
        assert result.is_mock is False

    @pytest.mark.asyncio
    async def test_unconfigured_raises_with_a_usable_message(self, monkeypatch):
        from app.services import azure_ai

        monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: None)

        with pytest.raises(RuntimeError, match="AZURE_SPEECH_REGION"):
            await asr._transcribe_azure(_audio(), "answer.webm", "hi")


class TestAsrChainFailover:
    @pytest.mark.asyncio
    async def test_azure_serves_when_sarvam_is_spent(self, monkeypatch, azure_asr):
        """A drained Sarvam account must not cost the patient a real transcript."""
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")

        async def spent(audio_file, filename, language):
            raise RuntimeError("402 No credits available")

        monkeypatch.setattr(asr, "_transcribe_sarvam", spent)

        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert result.is_mock is False
        assert result.text == "सीने में दर्द हो रहा है"

    @pytest.mark.asyncio
    async def test_the_stream_is_rewound_between_providers(self, monkeypatch, azure_asr):
        """A consumed stream would make the fallback upload zero bytes and
        "succeed" with an empty transcript."""
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")

        async def drains_then_fails(audio_file, filename, language):
            audio_file.read()  # leave the pointer at EOF
            raise RuntimeError("boom")

        monkeypatch.setattr(asr, "_transcribe_sarvam", drains_then_fails)

        await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert "FAKE_AUDIO_BYTES" in azure_asr["body"]

    @pytest.mark.asyncio
    async def test_mock_is_the_final_rung(self, monkeypatch):
        """Every provider failing still has to leave the interview usable."""
        from app.services import azure_ai

        monkeypatch.setattr(azure_ai, "get_speech_credentials", lambda: ("az-key", "eastus2"))
        monkeypatch.setattr(asr, "_is_azure_configured", lambda: True)
        monkeypatch.setattr(asr, "ASR_PROVIDER", "sarvam,azure")
        monkeypatch.setattr(asr, "SARVAM_API_KEY", "sk-test")

        async def boom(audio_file, filename, language):
            raise RuntimeError("down")

        monkeypatch.setattr(asr, "_transcribe_sarvam", boom)
        monkeypatch.setattr(asr, "_transcribe_azure", boom)

        result = await asr.transcribe_audio(_audio(), "answer.webm", "hi")

        assert result.is_mock is True
