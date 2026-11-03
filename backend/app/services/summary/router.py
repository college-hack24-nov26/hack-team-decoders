"""Main-API vs Local-Offline routing with automatic failover.

This is the single place in the codebase where the routing decision lives,
per the architecture doc's requirement. It is NOT scattered across call sites.

The logic:
1. If any hosted provider is configured → try Main API first. "Configured"
   means MAIN_LLM_API_KEY, or an Azure OpenAI endpoint + key. The check lives in
   llm.main_api_is_configured() so it cannot drift from the provider precedence
   rules that module implements.
2. If Main API fails (timeout, 5xx, no key) → try Local model (Ollama)
3. If Local model also fails → fall back to deterministic (rule-based) summary
4. The deterministic path ALWAYS works — no API, no model, no internet needed

The caller gets a StructuredSummary regardless of which path succeeded.
The `generated_by` field on the Summary model records which path was used,
so the physician can see whether it was AI-generated or rule-assembled.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.interview.languages import needs_translation_for_summary
from app.services.summary.llm import (
    main_api_is_configured,
    summarize_deterministic,
    summarize_local,
    summarize_main_api,
)
from app.services.summary.retrieval import RetrievedContext
from app.services.summary.schemas import StructuredSummary
from app.services.translation import TranslationUnavailableError, translate_to_english

logger = logging.getLogger(__name__)


async def _english_prompt_text(context: RetrievedContext) -> str | None:
    """Return an English rendering of the transcript, or ``None`` to use it as-is.

    The interview is transcribed in the patient's own language and stored that
    way, because a clinical record should hold what the patient actually said.
    The summariser, though, is an LLM whose quality across India's 22 scheduled
    languages is uneven — dependable in Hindi, thin in Santali or Bodo. A summary
    that silently degrades is the worst outcome available, since a physician
    cannot distinguish a bad translation from a bad history.

    So the assembled transcript is translated once here, not per answer: nothing
    reads the English until this point, and per-answer translation would multiply
    cost and latency by the question count for no gain.

    A translation failure returns ``None`` rather than raising. Sending the
    original is a worse summary; failing the request outright denies the
    physician any summary at all, and the deterministic tier is still behind us.
    """
    language = context.patient_language
    if not needs_translation_for_summary(language):
        return None

    original = context.format_for_prompt()
    try:
        translated = await translate_to_english(original, language)
    except TranslationUnavailableError as exc:
        logger.warning(
            "summary.translation_failed: language=%s falling back to the original "
            "transcript (%s)",
            language,
            str(exc)[:200],
        )
        return None

    logger.info("summary.translated_for_llm: language=%s -> en", language)
    return translated


async def generate_summary(context: RetrievedContext) -> tuple[StructuredSummary, str]:
    """Generate a structured summary using the best available path.

    Returns:
        (summary, generated_by) where generated_by is one of:
        "main_api", "local_offline", "deterministic"
    """
    settings = get_settings()

    # Path 1: Main API (hosted LLM).
    # `except Exception` is deliberate and broad: a transport error, a 5xx, a
    # rate limit and a schema-invalid response are all just "this path did not
    # work", and any of them must hand over to the next path rather than fail
    # the request. SummaryValidationError from _parse_and_validate lands here.
    prompt_text = await _english_prompt_text(context)

    if main_api_is_configured():
        try:
            logger.info("summary.routing: trying main_api")
            summary = await summarize_main_api(context, prompt_text=prompt_text)
            return summary, "main_api"
        except Exception as e:
            logger.warning("summary.main_api_failed: %s", str(e)[:200])

    # Path 2: Local model (Ollama)
    if settings.local_llm_endpoint:
        try:
            logger.info("summary.routing: trying local_offline")
            summary = await summarize_local(context, prompt_text=prompt_text)
            return summary, "local_offline"
        except Exception as e:
            logger.warning("summary.local_failed: %s", str(e)[:200])

    # Path 3: Deterministic fallback (always available)
    logger.info("summary.routing: using deterministic fallback")
    summary = summarize_deterministic(context)
    return summary, "deterministic"
