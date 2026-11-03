"""Document embedding generation for pgvector storage.

Generates text embeddings so Module C's summariser can retrieve relevant document
context by vector similarity. Three providers, chosen by ``EMBEDDING_PROVIDER``:

``azure``   Azure OpenAI embeddings over REST (httpx, no extra dependency). The
            ``dimensions`` parameter is pinned to 384 so the vector fits the
            existing ``vector(384)`` column — text-embedding-3-small is 1536 by
            default, which would not.
``local``   sentence-transformers/all-MiniLM-L6-v2, 384-dim natively. Only used
            when asked for explicitly: it drags in torch (~2 GB), so it is never
            selected automatically.
``hash``    The deterministic pseudo-embedding below. Not semantically meaningful
            — it exists so the storage/retrieval plumbing works with real
            pgvector rows and so tests run with no model and no network.

Resolution when ``EMBEDDING_PROVIDER`` is unset: Azure if Azure OpenAI is
configured, otherwise hash. This keeps the test suite hermetic (the fixtures
blank the Azure vars) while a configured deployment gets real embeddings for free.

Every real provider degrades to the hash on failure rather than raising. Embedding
happens inside document upload, and a transient embedding-service hiccup must not
fail the upload — a worse vector is recoverable, a lost document is not.

Embedding dimension: 384 (matches the ``document_embeddings.embedding`` column).
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Sequence

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384

#: "azure" | "local" | "hash". Unset means auto-detect (Azure if configured, else hash).
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()

#: Provider-specific model name. Azure wants a *deployment* name; local wants a
#: sentence-transformers model id. Each has a sensible default.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()

_AZURE_DEFAULT_MODEL = "text-embedding-3-small"
_LOCAL_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def _azure_configured() -> bool:
    from app.services.azure_ai import get_azure_openai_v1_base_url

    return get_azure_openai_v1_base_url() is not None


def _resolve_provider() -> str:
    """Which provider to use for this call.

    ``local`` is never auto-selected — the torch download is too heavy to pull in
    implicitly, so a deployment that wants it must say so.
    """
    if EMBEDDING_PROVIDER in {"azure", "local", "hash"}:
        return EMBEDDING_PROVIDER
    if _azure_configured():
        return "azure"
    return "hash"


# ---------------------------------------------------------------------------
# Hash (deterministic, offline, test-safe)
# ---------------------------------------------------------------------------


def _hash_embedding(text: str) -> list[float]:
    """A deterministic pseudo-embedding, unit-normalised.

    Not semantically meaningful. Kept as the always-available fallback so the
    plumbing works end to end with real pgvector rows and zero dependencies.
    """
    floats: list[float] = []
    data = text.encode("utf-8")
    i = 0
    while len(floats) < EMBEDDING_DIM:
        h = hashlib.sha256(data + i.to_bytes(4, "little")).digest()
        for byte in h:
            if len(floats) >= EMBEDDING_DIM:
                break
            floats.append((byte / 127.5) - 1.0)
        i += 1
    return _normalise(floats)


def _normalise(floats: list[float]) -> list[float]:
    magnitude = sum(f * f for f in floats) ** 0.5
    if magnitude < 1e-10:
        return [0.0] * EMBEDDING_DIM
    return [f / magnitude for f in floats]


# ---------------------------------------------------------------------------
# Azure OpenAI embeddings (REST)
# ---------------------------------------------------------------------------


def _azure_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed a batch via Azure OpenAI. Raises on any failure (caller falls back)."""
    from app.core.config import get_settings
    from app.services.azure_ai import get_azure_openai_v1_base_url

    base = get_azure_openai_v1_base_url()
    if base is None:
        raise RuntimeError("Azure OpenAI is not configured")

    settings = get_settings()
    key = settings.azure_openai_api_key
    model = EMBEDDING_MODEL or _AZURE_DEFAULT_MODEL

    resp = httpx.post(
        f"{base}/embeddings",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "api-key": key,
        },
        json={"model": model, "input": texts, "dimensions": EMBEDDING_DIM},
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    # The API returns items with an "index"; sort by it so the order matches the
    # input rather than trusting the response order.
    items = sorted(payload["data"], key=lambda d: d["index"])
    vectors = [_normalise([float(x) for x in item["embedding"]]) for item in items]
    if len(vectors) != len(texts):
        raise RuntimeError(f"Azure returned {len(vectors)} embeddings for {len(texts)} inputs")
    return vectors


# ---------------------------------------------------------------------------
# Local sentence-transformers
# ---------------------------------------------------------------------------

_local_model = None


def _get_local_model():
    """Load and cache the sentence-transformers model.

    Lazy and module-cached: the import pulls in torch, and loading the weights
    costs seconds, so it must happen at most once per process and never at import.
    """
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        _local_model = SentenceTransformer(EMBEDDING_MODEL or _LOCAL_DEFAULT_MODEL)
    return _local_model


def _local_embeddings(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    raw = model.encode(texts, normalize_embeddings=True)
    return [[float(x) for x in row] for row in raw]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_embedding(text: str) -> list[float]:
    """Return a 384-dim embedding for ``text``.

    Never raises: a real provider that fails degrades to the hash embedding, so
    document upload cannot be broken by an embedding-service outage.
    """
    if not text or not text.strip():
        # pgvector rejects NaN; an empty document gets a zero vector.
        return [0.0] * EMBEDDING_DIM
    return generate_embeddings_batch([text])[0]


def generate_embeddings_batch(texts: Sequence[str]) -> list[list[float]]:
    """Embed several texts, preserving order.

    Empty strings map to the zero vector without hitting a provider.
    """
    items = list(texts)
    if not items:
        return []

    provider = _resolve_provider()

    # Split out the blanks so a provider is never asked to embed "".
    to_embed = [(i, t) for i, t in enumerate(items) if t and t.strip()]
    result: list[list[float]] = [[0.0] * EMBEDDING_DIM for _ in items]

    if not to_embed:
        return result

    texts_only = [t for _, t in to_embed]

    try:
        if provider == "azure":
            vectors = _azure_embeddings(texts_only)
        elif provider == "local":
            vectors = _local_embeddings(texts_only)
        else:
            vectors = [_hash_embedding(t) for t in texts_only]
    except Exception:
        logger.warning(
            "embeddings: provider %s failed; falling back to hash embeddings",
            provider,
            exc_info=True,
        )
        vectors = [_hash_embedding(t) for t in texts_only]

    for (idx, _), vector in zip(to_embed, vectors, strict=True):
        result[idx] = vector
    return result
