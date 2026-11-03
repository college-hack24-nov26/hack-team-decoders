"""Azure OpenAI / Microsoft Foundry routing for the main LLM summariser path.

Covers the three things that were wrong when the Azure foundation first landed:

1. The sync ``AzureOpenAI`` client was called inside ``async def``, blocking the
   event loop for the whole completion and stalling the 3s red-flag path.
   Azure now rides the same ``httpx.AsyncClient`` transport as every other
   hosted provider, so there is no sync client left to misuse.
2. Ambient ``AZURE_OPENAI_*`` env vars silently overrode an explicitly
   configured ``MAIN_LLM_ENDPOINT``.
3. The classic ``?api-version=YYYY-MM-DD`` surface was hardcoded, which does not
   accommodate Foundry ``services.ai.azure.com`` resources. The v1 API is used
   instead and needs no dated api-version.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.services import azure_ai
from app.services.summary import llm as llm_mod

# A valid-but-minimal summary payload the validator accepts.
_SUMMARY_JSON = json.dumps({"chief_complaint": "fever"})


class _StubContext:
    """Stands in for RetrievedContext.

    ``patient_language`` defaults to English so the router's translation bridge
    is a no-op here; the bridge has its own tests.
    """

    def __init__(self, patient_language: str = "en") -> None:
        self.patient_language = patient_language

    def format_for_prompt(self) -> str:
        return "patient reports fever for two days"


@pytest.fixture()
def captured(monkeypatch):
    """Capture the outbound LLM request instead of performing it."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _SUMMARY_JSON}}]},
        )

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


def _configure(monkeypatch, **overrides) -> Settings:
    """Point both llm.py and azure_ai.py at the same throwaway Settings."""
    settings = Settings(**overrides)
    monkeypatch.setattr(llm_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(azure_ai, "get_settings", lambda: settings)
    return settings


class TestV1BaseUrlNormalization:
    """Whatever shape gets pasted out of the portal must resolve to /openai/v1."""

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            # Azure OpenAI resource, with and without a trailing slash
            (
                "https://res.openai.azure.com",
                "https://res.openai.azure.com/openai/v1",
            ),
            (
                "https://res.openai.azure.com/",
                "https://res.openai.azure.com/openai/v1",
            ),
            # Microsoft Foundry resource — the shape the classic client mishandled
            (
                "https://res.services.ai.azure.com",
                "https://res.services.ai.azure.com/openai/v1",
            ),
            (
                "https://res.services.ai.azure.com/",
                "https://res.services.ai.azure.com/openai/v1",
            ),
            # Partially or fully qualified already — must not double up
            (
                "https://res.openai.azure.com/openai",
                "https://res.openai.azure.com/openai/v1",
            ),
            (
                "https://res.openai.azure.com/openai/v1",
                "https://res.openai.azure.com/openai/v1",
            ),
            (
                "https://res.openai.azure.com/openai/v1/",
                "https://res.openai.azure.com/openai/v1",
            ),
        ],
    )
    def test_endpoint_shapes_normalize(self, monkeypatch, configured, expected):
        _configure(
            monkeypatch,
            azure_openai_endpoint=configured,
            azure_openai_api_key="az-key",
        )
        assert azure_ai.get_azure_openai_v1_base_url() == expected

    def test_returns_none_without_a_key(self, monkeypatch):
        """Half-configured Azure must not claim the hosted path."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="",
        )
        assert azure_ai.get_azure_openai_v1_base_url() is None

    def test_returns_none_without_an_endpoint(self, monkeypatch):
        _configure(
            monkeypatch,
            azure_openai_endpoint="",
            azure_openai_api_key="az-key",
        )
        assert azure_ai.get_azure_openai_v1_base_url() is None

    def test_no_dated_api_version_is_used(self, monkeypatch):
        """The v1 surface must not carry a ?api-version= parameter."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
        )
        assert "api-version" not in azure_ai.get_azure_openai_v1_base_url()


class TestAzureRequestShape:
    @pytest.mark.asyncio
    async def test_calls_the_v1_chat_completions_path(self, monkeypatch, captured):
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="gpt-4o-medikiosk",
        )

        summary = await llm_mod.summarize_main_api(_StubContext())

        assert summary.chief_complaint == "fever"
        assert captured["url"] == "https://res.openai.azure.com/openai/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_sends_the_deployment_name_not_the_model_name(self, monkeypatch, captured):
        """Azure addresses a deployment; sending main_llm_model would 404."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="gpt-4o-medikiosk",
            main_llm_model="gpt-4o-mini",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["body"]["model"] == "gpt-4o-medikiosk"

    @pytest.mark.asyncio
    async def test_authenticates_with_both_header_styles(self, monkeypatch, captured):
        """v1 takes bearer auth; api-key keeps classic-style endpoints working."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["headers"]["authorization"] == "Bearer az-key"
        assert captured["headers"]["api-key"] == "az-key"

    @pytest.mark.asyncio
    async def test_foundry_endpoint_is_routed(self, monkeypatch, captured):
        """A services.ai.azure.com resource must work, not just openai.azure.com."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.services.ai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="gpt-4o",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["url"] == "https://res.services.ai.azure.com/openai/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_requests_json_object_output(self, monkeypatch, captured):
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["body"]["response_format"] == {"type": "json_object"}


class TestProviderPrecedence:
    """Ambient Azure credentials must never hijack an explicit provider choice."""

    @pytest.mark.asyncio
    async def test_explicit_endpoint_beats_ambient_azure(self, monkeypatch, captured):
        """The regression: Azure env vars stole a configured Groq/Together URL."""
        _configure(
            monkeypatch,
            main_llm_endpoint="https://api.groq.com/openai/v1",
            main_llm_api_key="gsk-test",
            main_llm_model="llama-3.3-70b",
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
        assert captured["body"]["model"] == "llama-3.3-70b"
        assert "api-key" not in captured["headers"]

    @pytest.mark.asyncio
    async def test_gemini_beats_ambient_azure(self, monkeypatch, captured):
        _configure(
            monkeypatch,
            main_llm_provider="gemini",
            main_llm_api_key="gemini-key",
            main_llm_model="gemini-2.0-flash",
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert "generativelanguage.googleapis.com" in captured["url"]
        # Gemini rejects response_format, so it must stay off the payload.
        assert "response_format" not in captured["body"]

    @pytest.mark.asyncio
    async def test_provider_azure_forces_the_azure_path(self, monkeypatch, captured):
        _configure(
            monkeypatch,
            main_llm_provider="azure",
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="gpt-4o",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert "openai/v1/chat/completions" in captured["url"]

    @pytest.mark.asyncio
    async def test_provider_azure_without_config_raises(self, monkeypatch):
        """Explicitly asking for Azure and getting silence would hide a misconfig."""
        _configure(
            monkeypatch,
            main_llm_provider="azure",
            azure_openai_endpoint="",
            azure_openai_api_key="",
        )

        with pytest.raises(RuntimeError, match="MAIN_LLM_PROVIDER=azure"):
            await llm_mod.summarize_main_api(_StubContext())

    @pytest.mark.asyncio
    async def test_unconfigured_azure_leaves_the_default_path_alone(self, monkeypatch, captured):
        _configure(
            monkeypatch,
            main_llm_api_key="sk-test",
            main_llm_model="gpt-4o-mini",
            azure_openai_endpoint="",
            azure_openai_api_key="",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["url"] == "https://api.openai.com/v1/chat/completions"
        assert captured["body"]["model"] == "gpt-4o-mini"


class TestMainApiIsConfigured:
    """The router's gate for attempting a hosted LLM at all.

    This gate previously read only MAIN_LLM_API_KEY, so a fully working Azure
    deployment was never called and every summary quietly came from the
    deterministic tier.
    """

    def test_azure_alone_enables_the_hosted_path(self, monkeypatch):
        _configure(
            monkeypatch,
            main_llm_api_key="",
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
        )
        assert llm_mod.main_api_is_configured() is True

    def test_main_llm_key_alone_enables_it(self, monkeypatch):
        _configure(monkeypatch, main_llm_api_key="sk-test")
        assert llm_mod.main_api_is_configured() is True

    def test_nothing_configured_disables_it(self, monkeypatch):
        _configure(
            monkeypatch,
            main_llm_api_key="",
            azure_openai_endpoint="",
            azure_openai_api_key="",
        )
        assert llm_mod.main_api_is_configured() is False

    def test_half_configured_azure_does_not_count(self, monkeypatch):
        """An endpoint with no key would fail on every call."""
        _configure(
            monkeypatch,
            main_llm_api_key="",
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="",
        )
        assert llm_mod.main_api_is_configured() is False

    @pytest.mark.asyncio
    async def test_router_reaches_azure_with_only_azure_configured(self, monkeypatch, captured):
        """End to end: the regression that made every summary deterministic."""
        from app.services.summary import router as summary_router

        settings = _configure(
            monkeypatch,
            main_llm_api_key="",
            local_llm_endpoint="",
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="gpt-5.4-mini",
        )
        monkeypatch.setattr(summary_router, "get_settings", lambda: settings)

        summary, generated_by = await summary_router.generate_summary(_StubContext())

        assert generated_by == "main_api", "must not silently use the rule-based tier"
        assert summary.chief_complaint == "fever"
        assert "openai/v1/chat/completions" in captured["url"]


class TestSamplingParams:
    """GPT-5.x and the o-series removed ``temperature`` from the request schema.

    Sending it returns 400 ("Only the default (1) value is supported"), which the
    router treats as a dead main_api path — every summary would silently drop to
    the deterministic tier while looking like it succeeded.
    """

    @pytest.mark.parametrize(
        "deployment",
        [
            "gpt-5.4-mini",
            "gpt-5",
            "gpt-5.1",
            "gpt-5.6-sol",
            "o1",
            "o3-mini",
            "o4-mini",
            "medikiosk-gpt-5.4-mini",
        ],
    )
    @pytest.mark.asyncio
    async def test_temperature_omitted_for_reasoning_models(
        self, monkeypatch, captured, deployment
    ):
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment=deployment,
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert "temperature" not in captured["body"]

    @pytest.mark.parametrize("deployment", ["gpt-4o", "gpt-4o-mini", "gpt-4.1"])
    @pytest.mark.asyncio
    async def test_temperature_kept_for_non_reasoning_models(
        self, monkeypatch, captured, deployment
    ):
        """Older models still need it low — this is extraction, not authorship."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment=deployment,
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["body"]["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_gemini_still_gets_temperature(self, monkeypatch, captured):
        _configure(
            monkeypatch,
            main_llm_provider="gemini",
            main_llm_api_key="gemini-key",
            main_llm_model="gemini-2.0-flash",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert captured["body"]["temperature"] == 0.1


class TestUnsupportedParamRetry:
    """The backstop for a deployment name the pattern can't classify.

    Azure deployment names are free-form, so "summariser-prod" tells us nothing
    about whether it points at a reasoning model. Without a retry, one bad guess
    silently demotes every summary to the deterministic tier.
    """

    @pytest.fixture()
    def rejects_temperature(self, monkeypatch):
        """Stub that 400s on temperature, then succeeds once it's dropped."""
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body)
            if "temperature" in body:
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "code": "unsupported_value",
                            "message": (
                                "Unsupported value: 'temperature' does not support "
                                "0.1 with this model. Only the default (1) value "
                                "is supported."
                            ),
                        }
                    },
                )
            return httpx.Response(200, json={"choices": [{"message": {"content": _SUMMARY_JSON}}]})

        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return calls

    @pytest.mark.asyncio
    async def test_retries_without_temperature_and_succeeds(self, monkeypatch, rejects_temperature):
        # A name that gives away nothing about the underlying model.
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="summariser-prod",
        )

        summary = await llm_mod.summarize_main_api(_StubContext())

        assert summary.chief_complaint == "fever"
        assert len(rejects_temperature) == 2, "should send, get 400, then retry"
        assert "temperature" in rejects_temperature[0]
        assert "temperature" not in rejects_temperature[1]

    @pytest.mark.asyncio
    async def test_no_retry_when_temperature_was_never_sent(self, monkeypatch, rejects_temperature):
        """A recognised reasoning model omits it up front — one call, no retry."""
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="az-key",
            azure_openai_deployment="gpt-5.4-mini",
        )

        await llm_mod.summarize_main_api(_StubContext())

        assert len(rejects_temperature) == 1

    @pytest.mark.asyncio
    async def test_unrelated_400_is_not_retried(self, monkeypatch):
        """Only parameter complaints are retryable; a bad key must still fail."""
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content))
            return httpx.Response(
                401, json={"error": {"message": "Access denied due to invalid key"}}
            )

        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        _configure(
            monkeypatch,
            azure_openai_endpoint="https://res.openai.azure.com",
            azure_openai_api_key="wrong-key",
            azure_openai_deployment="gpt-4o-mini",
        )

        with pytest.raises(httpx.HTTPStatusError):
            await llm_mod.summarize_main_api(_StubContext())

        assert len(calls) == 1, "must not retry an auth failure"


class TestNoSyncClientRemains:
    def test_sync_azure_openai_factory_is_gone(self):
        """The sync factory was the event-loop blocker; it must not come back."""
        assert not hasattr(azure_ai, "get_azure_openai_client")

    def test_openai_sdk_is_not_imported(self):
        """The v1 path is pure httpx, so the openai package stays out of deps."""
        import inspect

        source = inspect.getsource(azure_ai)
        assert "from openai import" not in source
