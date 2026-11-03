"""Sarvam text translation, and the summariser's English bridge.

Runs against a stubbed transport, so these execute offline and bill nothing.
Two behaviours matter most and are pinned hardest: a failed translation must not
masquerade as a successful one, and the request must never exceed Sarvam's
2000-character limit no matter how long the interview ran.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import translation
from app.services.sarvam_keys import reset_pool
from app.services.summary import llm as llm_mod
from app.services.translation import (
    MAX_INPUT_CHARS,
    TRANSLATE_MODEL,
    TranslationUnavailableError,
    _split_for_translation,
    translate_to_english,
)


@pytest.fixture(autouse=True)
def _pool():
    """One usable key by default; the pool is process-wide state."""
    reset_pool(["sk-test"])
    yield
    reset_pool([])


class _TranslateStub:
    """Scripted Sarvam translate endpoint."""

    def __init__(self, status: int = 200, translated: str | None = None):
        self.status = status
        self.translated = translated
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        self.requests.append({"body": body, "headers": dict(request.headers)})

        if self.status >= 400:
            return httpx.Response(self.status, json={"error": "nope"})

        text = self.translated
        if text is None:
            text = f"EN[{body['input']}]"
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "translated_text": text,
                "source_language_code": body["source_language_code"],
            },
        )

    def install(self, monkeypatch):
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(self.handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return self


class TestChunking:
    """Sarvam rejects input over 2000 characters outright."""

    def test_short_text_is_one_chunk(self):
        assert _split_for_translation("short enough") == ["short enough"]

    def test_empty_text_yields_nothing(self):
        assert _split_for_translation("   ") == []

    def test_no_chunk_exceeds_the_limit(self):
        """A long interview must not be sent whole and rejected."""
        text = "\n\n".join(f"Question {n}. " + ("word " * 60) for n in range(40))

        chunks = _split_for_translation(text)

        assert len(chunks) > 1
        assert all(len(chunk) <= MAX_INPUT_CHARS for chunk in chunks)

    def test_unpunctuated_wall_of_text_is_still_split(self):
        """Pathological input has no paragraph or sentence boundary to use."""
        chunks = _split_for_translation("क" * 5000)

        assert all(len(chunk) <= MAX_INPUT_CHARS for chunk in chunks)
        assert "".join(chunks) == "क" * 5000

    def test_chunks_are_recombined_greedily(self):
        """Fewer chunks means fewer API calls; one per sentence would be wasteful."""
        text = "\n\n".join(["Short line."] * 50)

        chunks = _split_for_translation(text)

        assert len(chunks) == 1, "50 short lines fit comfortably inside one request"

    def test_paragraph_boundaries_are_preferred(self):
        """Cutting mid-clause costs the model the context to resolve it."""
        para = "word " * 300  # ~1500 chars, so two will not fit together
        chunks = _split_for_translation(f"{para.strip()}\n\n{para.strip()}")

        assert len(chunks) == 2
        assert all(chunk.strip() == para.strip() for chunk in chunks)


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_sends_the_documented_payload(self, monkeypatch):
        stub = _TranslateStub().install(monkeypatch)

        await translate_to_english("मुझे बुखार है", "hi")

        body = stub.requests[0]["body"]
        assert body["input"] == "मुझे बुखार है"
        assert body["source_language_code"] == "hi-IN"
        assert body["target_language_code"] == "en-IN"
        assert body["model"] == TRANSLATE_MODEL
        # sarvam-translate:v1 supports formal only.
        assert body["mode"] == "formal"
        # Lab values and dosages must stay machine-readable downstream.
        assert body["numerals_format"] == "international"

    @pytest.mark.asyncio
    async def test_authenticates_with_the_sarvam_header(self, monkeypatch):
        stub = _TranslateStub().install(monkeypatch)

        await translate_to_english("வணக்கம்", "ta")

        assert stub.requests[0]["headers"]["api-subscription-key"] == "sk-test"

    @pytest.mark.asyncio
    async def test_returns_the_translated_text(self, monkeypatch):
        _TranslateStub(translated="I have a fever").install(monkeypatch)

        assert await translate_to_english("मुझे बुखार है", "hi") == "I have a fever"

    @pytest.mark.asyncio
    async def test_long_text_makes_one_call_per_chunk(self, monkeypatch):
        stub = _TranslateStub().install(monkeypatch)
        text = "\n\n".join(f"Line {n}. " + ("word " * 60) for n in range(40))
        expected = len(_split_for_translation(text))

        await translate_to_english(text, "bn")

        assert len(stub.requests) == expected > 1

    @pytest.mark.asyncio
    async def test_chunked_output_is_rejoined(self, monkeypatch):
        _TranslateStub().install(monkeypatch)
        para = ("word " * 300).strip()

        result = await translate_to_english(f"{para}\n\n{para}", "ta")

        assert result.count("EN[") == 2


class TestShortCircuits:
    @pytest.mark.asyncio
    async def test_english_is_returned_untouched(self, monkeypatch):
        """No point paying to translate English into English."""
        stub = _TranslateStub().install(monkeypatch)

        assert await translate_to_english("I have a fever", "en") == "I have a fever"
        assert stub.requests == []

    @pytest.mark.asyncio
    async def test_empty_text_makes_no_call(self, monkeypatch):
        stub = _TranslateStub().install(monkeypatch)

        assert await translate_to_english("   ", "hi") == ""
        assert stub.requests == []


class TestFailureIsLoud:
    """A silent failure would hand the summariser untranslated text that looks
    translated. The physician cannot tell the difference, so it must raise."""

    @pytest.mark.asyncio
    async def test_http_error_raises(self, monkeypatch):
        _TranslateStub(status=500).install(monkeypatch)

        with pytest.raises(TranslationUnavailableError):
            await translate_to_english("मुझे बुखार है", "hi")

    @pytest.mark.asyncio
    async def test_empty_response_raises_rather_than_returning_blank(self, monkeypatch):
        """Still raises — but the message now comes from the last rung of the
        chain, not from Sarvam. With no hosted model configured in tests, Sarvam's
        "no text" is caught and the fallback's own unavailability is what
        surfaces. The property under test is that it raises at all."""
        _TranslateStub(translated="").install(monkeypatch)

        with pytest.raises(TranslationUnavailableError):
            await translate_to_english("मुझे बुखार है", "hi")

    @pytest.mark.asyncio
    async def test_sarvam_rung_reports_an_empty_reply_precisely(self, monkeypatch):
        """The chain hides Sarvam's message, so assert it at the rung itself."""
        _TranslateStub(translated="").install(monkeypatch)

        async with httpx.AsyncClient() as client:
            with pytest.raises(TranslationUnavailableError, match="no text"):
                await translation._translate_chunk_sarvam(client, "hi", "hi-IN", "en-IN")

    @pytest.mark.asyncio
    async def test_no_usable_key_raises(self, monkeypatch):
        _TranslateStub().install(monkeypatch)
        reset_pool([])

        with pytest.raises(TranslationUnavailableError):
            await translate_to_english("मुझे बुखार है", "hi")

    @pytest.mark.asyncio
    async def test_sarvam_rung_reports_a_drained_pool_precisely(self, monkeypatch):
        _TranslateStub().install(monkeypatch)
        reset_pool([])

        async with httpx.AsyncClient() as client:
            with pytest.raises(TranslationUnavailableError, match="no usable"):
                await translation._translate_chunk_sarvam(client, "hi", "hi-IN", "en-IN")

    @pytest.mark.asyncio
    async def test_exhausted_key_rotates_to_the_next(self, monkeypatch):
        """A spent teammate account must not end the visit."""
        reset_pool(["sk-dead", "sk-live"])
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            key = request.headers["api-subscription-key"]
            seen.append(key)
            if key == "sk-dead":
                return httpx.Response(402, json={"error": "out of credit"})
            return httpx.Response(
                200, json={"translated_text": "I have a fever", "source_language_code": "hi-IN"}
            )

        original = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda *a, **kw: original(*a, **{**kw, "transport": httpx.MockTransport(handler)}),
        )

        result = await translate_to_english("मुझे बुखार है", "hi")

        assert result == "I have a fever"
        assert seen == ["sk-dead", "sk-live"]


class TestOutboundTranslation:
    """Text the kiosk SPEAKS: consent sections and interview prompts.

    These exist only in English and Hindi. Without translating them, a patient
    who chose Kannada was asked English questions and read the consent aloud in
    English — which is not informed consent in any meaningful sense.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.services.translation import _OUTBOUND_CACHE

        _OUTBOUND_CACHE.clear()
        yield
        _OUTBOUND_CACHE.clear()

    @pytest.mark.asyncio
    async def test_translates_into_the_patients_language(self, monkeypatch):
        from app.services.translation import translate_from_english

        stub = _TranslateStub(translated="ಜ್ವರ").install(monkeypatch)

        assert await translate_from_english("fever", "kn") == "ಜ್ವರ"

        body = stub.requests[0]["body"]
        assert body["source_language_code"] == "en-IN"
        assert body["target_language_code"] == "kn-IN"

    @pytest.mark.asyncio
    async def test_english_target_is_a_no_op(self, monkeypatch):
        from app.services.translation import translate_from_english

        stub = _TranslateStub().install(monkeypatch)

        assert await translate_from_english("fever", "en") == "fever"
        assert stub.requests == []

    @pytest.mark.asyncio
    async def test_repeated_text_is_served_from_cache(self, monkeypatch):
        """The ontology is closed, so the same strings recur for every patient.
        Paying to translate them per visit would be waste."""
        from app.services.translation import translate_from_english

        stub = _TranslateStub(translated="ಜ್ವರ").install(monkeypatch)

        await translate_from_english("fever", "kn")
        await translate_from_english("fever", "kn")

        assert len(stub.requests) == 1

    @pytest.mark.asyncio
    async def test_cache_is_per_language(self, monkeypatch):
        from app.services.translation import translate_from_english

        stub = _TranslateStub().install(monkeypatch)

        await translate_from_english("fever", "kn")
        await translate_from_english("fever", "ta")

        assert len(stub.requests) == 2

    @pytest.mark.asyncio
    async def test_failure_returns_none_so_caller_can_fall_back(self, monkeypatch):
        """Speaking English is worse than speaking Kannada but better than silence."""
        from app.services.translation import translate_from_english

        _TranslateStub(status=500).install(monkeypatch)

        assert await translate_from_english("fever", "kn") is None

    @pytest.mark.asyncio
    async def test_batch_translates_prompt_and_all_option_labels(self, monkeypatch):
        """A question is a prompt plus up to eight labels; sequential calls would
        stall the first patient in a language for seconds."""
        from app.services.translation import translate_many_from_english

        stub = _TranslateStub().install(monkeypatch)
        source = ["Where is the pain?", "Chest", "Left arm", "Back"]

        result = await translate_many_from_english(source, "ta")

        assert len(result) == len(source)
        assert len(stub.requests) == len(source)
        assert all(value is not None for value in result)

    @pytest.mark.asyncio
    async def test_batch_preserves_order(self, monkeypatch):
        """Labels are zipped back onto their options, so order is load-bearing."""
        from app.services.translation import translate_many_from_english

        _TranslateStub().install(monkeypatch)

        result = await translate_many_from_english(["one", "two", "three"], "bn")

        assert result == ["EN[one]", "EN[two]", "EN[three]"]

    @pytest.mark.asyncio
    async def test_batch_is_a_no_op_for_english(self, monkeypatch):
        from app.services.translation import translate_many_from_english

        stub = _TranslateStub().install(monkeypatch)

        assert await translate_many_from_english(["a", "b"], "en") == ["a", "b"]
        assert stub.requests == []

    @pytest.mark.asyncio
    async def test_empty_batch_makes_no_call(self, monkeypatch):
        from app.services.translation import translate_many_from_english

        stub = _TranslateStub().install(monkeypatch)

        assert await translate_many_from_english([], "ta") == []
        assert stub.requests == []


class TestSummaryBridge:
    """The router decides whether a transcript needs translating at all."""

    class _Ctx:
        def __init__(self, language: str, text: str = "patient reports fever"):
            self.patient_language = language
            self._text = text

        def format_for_prompt(self) -> str:
            return self._text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("language", ["en", "hi"])
    async def test_english_and_hindi_skip_translation(self, monkeypatch, language):
        """The summariser handles both, and translating would discard the
        patient's own words for nothing."""
        from app.services.summary import router

        stub = _TranslateStub().install(monkeypatch)

        assert await router._english_prompt_text(self._Ctx(language)) is None
        assert stub.requests == []

    @pytest.mark.asyncio
    async def test_other_languages_are_translated(self, monkeypatch):
        from app.services.summary import router

        _TranslateStub(translated="I have a fever").install(monkeypatch)

        result = await router._english_prompt_text(self._Ctx("ta"))

        assert result == "I have a fever"

    @pytest.mark.asyncio
    async def test_translation_failure_degrades_to_the_original(self, monkeypatch):
        """A missing summary is worse than one built from untranslated text, and
        the deterministic tier is still behind this."""
        from app.services.summary import router

        _TranslateStub(status=503).install(monkeypatch)

        assert await router._english_prompt_text(self._Ctx("sat")) is None

    @pytest.mark.asyncio
    async def test_source_language_is_passed_through(self, monkeypatch):
        from app.services.summary import router

        stub = _TranslateStub().install(monkeypatch)

        await router._english_prompt_text(self._Ctx("mni"))

        assert stub.requests[0]["body"]["source_language_code"] == "mni-IN"


# ---------------------------------------------------------------------------
# Hosted-model fallback when Sarvam is spent
# ---------------------------------------------------------------------------


class TestAzureFallback:
    """Sarvam running dry must not cost a patient their language.

    This is the failure that looks like success: translation returns None, the
    caller falls back to the English source, and the kiosk reads a Marathi
    speaker their consent in English. Nothing raises, so nothing catches it
    except a test that asserts the fallback ran.
    """

    @pytest.fixture()
    def sarvam_dead(self, monkeypatch):
        async def spent(client, chunk, source, target):
            raise translation.TranslationUnavailableError("no usable Sarvam API key available")

        monkeypatch.setattr(translation, "_translate_chunk_sarvam", spent)

    @pytest.fixture()
    def hosted_model(self, monkeypatch):
        """A configured hosted model that echoes a marker translation."""
        calls: list[list[dict]] = []

        async def fake_post(messages, **kwargs):
            calls.append(messages)
            return json.dumps({"translation": "अनुवादित मजकूर"})

        monkeypatch.setattr(llm_mod, "main_api_is_configured", lambda: True)
        monkeypatch.setattr(llm_mod, "post_chat_completion", fake_post)
        return calls

    @pytest.mark.asyncio
    async def test_falls_back_when_sarvam_is_spent(self, monkeypatch, sarvam_dead, hosted_model):
        translation._OUTBOUND_CACHE.clear()

        result = await translation.translate_from_english("Health questions", "mr")

        assert result == "अनुवादित मजकूर"
        assert len(hosted_model) == 1

    @pytest.mark.asyncio
    async def test_the_target_language_reaches_the_model(
        self, monkeypatch, sarvam_dead, hosted_model
    ):
        translation._OUTBOUND_CACHE.clear()

        await translation.translate_from_english("Health questions", "kn")

        prompt = hosted_model[0][-1]["content"]
        assert "Kannada" in prompt

    @pytest.mark.asyncio
    async def test_placeholders_are_protected_in_the_prompt(
        self, monkeypatch, sarvam_dead, hosted_model
    ):
        """A localised {{name}} silently breaks interpolation and the patient sees
        raw braces, so the instruction has to be explicit."""
        translation._OUTBOUND_CACHE.clear()

        await translation.translate_from_english("Hello {{name}}", "ta")

        prompt = hosted_model[0][-1]["content"]
        assert "{{placeholder}}" in prompt

    @pytest.mark.asyncio
    async def test_returns_none_when_neither_provider_works(self, monkeypatch, sarvam_dead):
        """Honest failure: the caller falls back to the English source knowingly."""
        translation._OUTBOUND_CACHE.clear()
        monkeypatch.setattr(llm_mod, "main_api_is_configured", lambda: False)

        assert await translation.translate_from_english("Health questions", "mr") is None

    @pytest.mark.asyncio
    async def test_an_empty_model_reply_is_a_failure_not_empty_text(self, monkeypatch, sarvam_dead):
        translation._OUTBOUND_CACHE.clear()

        async def blank(messages, **kwargs):
            return json.dumps({"translation": "   "})

        monkeypatch.setattr(llm_mod, "main_api_is_configured", lambda: True)
        monkeypatch.setattr(llm_mod, "post_chat_completion", blank)

        assert await translation.translate_from_english("Health questions", "mr") is None

    @pytest.mark.asyncio
    async def test_sarvam_is_still_tried_first(self, monkeypatch, hosted_model):
        """Azure is the rung below, not a replacement: sarvam-translate is built
        for Indic pairs and keeps the formal register a clinical document wants."""
        translation._OUTBOUND_CACHE.clear()
        seen: list[str] = []

        async def sarvam_works(client, chunk, source, target):
            seen.append(target)
            return "सार्वम अनुवाद"

        monkeypatch.setattr(translation, "_translate_chunk_sarvam", sarvam_works)

        result = await translation.translate_from_english("Health questions", "mr")

        assert result == "सार्वम अनुवाद"
        assert seen == ["mr-IN"]
        assert hosted_model == [], "the hosted model must not be called when Sarvam works"

    @pytest.mark.asyncio
    async def test_transcript_translation_also_falls_back(
        self, monkeypatch, sarvam_dead, hosted_model
    ):
        """translate_to_english shares the chunk path, so it inherits the rung."""
        result = await translation.translate_to_english("मला ताप आहे", "mr")

        assert result == "अनुवादित मजकूर"
