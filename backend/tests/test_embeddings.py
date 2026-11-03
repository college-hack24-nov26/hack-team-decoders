"""Tests for A6 — real embeddings with provider selection and a safe fallback.

The load-bearing property is resilience: embedding runs inside document upload, so
a provider outage must degrade to the hash rather than fail the upload. These
assert the resolution logic, the 384-dim contract, and that every real-provider
failure lands on the hash.

No network and no model download: the Azure path is exercised through a mocked
httpx, and the local path is never auto-selected.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import embeddings as e


@pytest.fixture(autouse=True)
def _reset_provider(monkeypatch):
    """Default to auto-detect with no Azure, i.e. the hash path, unless a test
    says otherwise. Mirrors the hermetic test environment."""
    monkeypatch.setattr(e, "EMBEDDING_PROVIDER", "")
    monkeypatch.setattr(e, "EMBEDDING_MODEL", "")
    monkeypatch.setattr(e, "_azure_configured", lambda: False)


class TestResolution:
    def test_unset_without_azure_is_hash(self):
        assert e._resolve_provider() == "hash"

    def test_unset_with_azure_is_azure(self, monkeypatch):
        monkeypatch.setattr(e, "_azure_configured", lambda: True)
        assert e._resolve_provider() == "azure"

    def test_explicit_provider_wins(self, monkeypatch):
        monkeypatch.setattr(e, "EMBEDDING_PROVIDER", "hash")
        monkeypatch.setattr(e, "_azure_configured", lambda: True)
        assert e._resolve_provider() == "hash"

    def test_local_is_never_auto_selected(self, monkeypatch):
        """torch is too heavy to pull in implicitly — local must be explicit."""
        monkeypatch.setattr(e, "_azure_configured", lambda: False)
        assert e._resolve_provider() != "local"


class TestContract:
    def test_dimension_is_384(self):
        assert len(e.generate_embedding("chest pain")) == e.EMBEDDING_DIM

    def test_deterministic(self):
        assert e.generate_embedding("HbA1c 8.9%") == e.generate_embedding("HbA1c 8.9%")

    def test_unit_normalised(self):
        v = e.generate_embedding("some clinical text")
        assert abs(sum(x * x for x in v) ** 0.5 - 1.0) < 1e-6

    def test_empty_is_a_zero_vector(self):
        assert e.generate_embedding("") == [0.0] * e.EMBEDDING_DIM
        assert e.generate_embedding("   ") == [0.0] * e.EMBEDDING_DIM

    def test_batch_preserves_order_and_blanks(self):
        out = e.generate_embeddings_batch(["a", "", "b"])
        assert len(out) == 3
        assert out[1] == [0.0] * e.EMBEDDING_DIM
        assert out[0] == e.generate_embedding("a")
        assert out[2] == e.generate_embedding("b")

    def test_empty_batch(self):
        assert e.generate_embeddings_batch([]) == []


class TestAzureProvider:
    @pytest.fixture()
    def azure(self, monkeypatch):
        monkeypatch.setattr(e, "EMBEDDING_PROVIDER", "azure")
        monkeypatch.setattr(
            "app.services.azure_ai.get_azure_openai_v1_base_url",
            lambda: "https://res.openai.azure.com/openai/v1",
        )
        from app.core.config import Settings

        monkeypatch.setattr(
            "app.core.config.get_settings",
            lambda: Settings(azure_openai_api_key="k", azure_openai_endpoint="https://x"),
        )

    def test_calls_azure_and_returns_the_vector(self, azure, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [0.1] * e.EMBEDDING_DIM}]}
            )

        monkeypatch.setattr(httpx, "post", fake_post)

        v = e.generate_embedding("chest pain")

        assert len(v) == e.EMBEDDING_DIM
        assert captured["url"].endswith("/embeddings")
        # 384 dims requested so the vector fits the existing vector(384) column.
        assert captured["json"]["dimensions"] == e.EMBEDDING_DIM
        assert captured["json"]["input"] == ["chest pain"]

    def test_azure_failure_falls_back_to_hash(self, azure, monkeypatch):
        """A dead embeddings deployment must not break document upload."""

        def boom(*a, **k):
            return httpx.Response(404, json={"error": "DeploymentNotFound"})

        monkeypatch.setattr(httpx, "post", boom)

        v = e.generate_embedding("chest pain")

        assert v == e._hash_embedding("chest pain")

    def test_azure_transport_error_falls_back_to_hash(self, azure, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx, "post", boom)

        assert e.generate_embedding("x") == e._hash_embedding("x")
