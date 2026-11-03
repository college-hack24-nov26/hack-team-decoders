"""Sarvam text translation, used to hand the summariser reliable English.

The kiosk transcribes in the patient's own language and keeps those words: a
clinical record should preserve what the patient actually said, not a paraphrase
of it. But the summariser is an LLM, and its quality across India's 22 scheduled
languages is uneven — strong in Hindi, thinner in Santali, Bodo or Dogri. A
summary that quietly degrades is the worst failure mode here, because a physician
cannot tell a bad translation from a bad history.

So the transcript is translated to English once, at summary time, and both
versions are kept. Translating per answer instead would multiply cost and latency
by the number of questions for no benefit — nothing reads the English until the
summary is assembled.

``sarvam-translate:v1`` is used rather than ``mayura:v1``: it covers all 22
scheduled languages bidirectionally where Mayura covers 11, and its formal
register suits a clinical document. It caps input at 2000 characters, so longer
transcripts are split on paragraph and sentence boundaries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from app.interview import languages
from app.services.sarvam_keys import (
    acquire_key,
    attempt_budget,
    report_key_failure,
    report_key_success,
)

logger = logging.getLogger(__name__)

SARVAM_TRANSLATE_ENDPOINT = "https://api.sarvam.ai/translate"

#: Covers all 22 scheduled languages, formal register only.
TRANSLATE_MODEL = "sarvam-translate:v1"

#: Hard limit for ``sarvam-translate:v1``. Mayura's is 1000.
MAX_INPUT_CHARS = 2000


class TranslationUnavailableError(RuntimeError):
    """Translation could not be produced. Callers fall back to the original."""


def _split_for_translation(text: str, limit: int = MAX_INPUT_CHARS) -> list[str]:
    """Break text into chunks within the API's character limit.

    Splits on blank lines first, then sentence ends, then — only if a single
    sentence is still oversized — on a hard character boundary. Preferring
    natural boundaries matters for translation quality: a chunk cut mid-clause
    loses the context the model needs to resolve it.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []

    # Paragraphs, then sentences, as candidate atoms.
    atoms: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if len(block) <= limit:
            atoms.append(block)
            continue
        for sentence in re.split(r"(?<=[.!?।])\s+", block):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= limit:
                atoms.append(sentence)
            else:
                # Pathological: an unpunctuated wall of text. Cut it.
                atoms.extend(sentence[i : i + limit] for i in range(0, len(sentence), limit))

    # Recombine atoms greedily so we make as few API calls as possible.
    chunks: list[str] = []
    current = ""
    for atom in atoms:
        candidate = f"{current}\n\n{atom}" if current else atom
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = atom
    if current:
        chunks.append(current)

    return chunks


async def _translate_chunk_sarvam(
    client: httpx.AsyncClient, chunk: str, source: str, target: str
) -> str:
    """Translate one within-limit chunk, rotating keys on a spent account."""
    payload = {
        "input": chunk,
        "source_language_code": source,
        "target_language_code": target,
        "model": TRANSLATE_MODEL,
        # sarvam-translate:v1 supports formal only; stated rather than omitted
        # so the intent survives a future model swap.
        "mode": "formal",
        # Keep 0-9 so lab values and dosages stay machine-readable downstream.
        "numerals_format": "international",
    }

    for _attempt in range(attempt_budget()):
        key = acquire_key()
        if key is None:
            raise TranslationUnavailableError("no usable Sarvam API key available")

        response = await client.post(
            SARVAM_TRANSLATE_ENDPOINT,
            headers={"api-subscription-key": key, "Content-Type": "application/json"},
            json=payload,
        )

        if response.status_code >= 400:
            logger.warning(
                "translation: Sarvam returned HTTP %s: %s",
                response.status_code,
                response.text[:300],
            )
            if report_key_failure(key, response.status_code):
                continue
            raise TranslationUnavailableError(
                f"Sarvam translate failed: HTTP {response.status_code}"
            )

        report_key_success(key)
        translated = (response.json() or {}).get("translated_text")
        if not translated:
            raise TranslationUnavailableError("Sarvam translate returned no text")
        return str(translated)

    raise TranslationUnavailableError("every available Sarvam key was rejected")


_AZURE_TRANSLATE_SYSTEM = (
    "You are a professional translator for an Indian public hospital kiosk. "
    "You translate patient-facing clinical text. Reply with JSON only."
)

_AZURE_TRANSLATE_USER = """\
Translate the text below from {source_name} into {target_name}, using
{target_name}'s own script.

Rules:
- Preserve the meaning exactly. This is clinical and consent text: do not soften
  it, do not add reassurance, do not omit anything.
- Plain, everyday wording. The reader may be elderly or unable to read well.
- Leave any {{{{placeholder}}}} in double curly braces EXACTLY as written, in the
  same script. Translating a placeholder name breaks the interpolation and the
  patient sees raw braces on screen.
- Keep digits as 0-9 so lab values and dosages stay machine-readable.
- Return only the translation, no notes and no alternatives.

Reply as: {{"translation": "..."}}

Text:
{text}
"""


async def _translate_chunk_azure(chunk: str, source: str, target: str) -> str:
    """Translate one chunk with the Azure OpenAI deployment.

    The fallback for when Sarvam is out of credit. Without it, a dead Sarvam key
    takes down translation for the eight languages that have no authored source
    text — and because the callers fall back to the English original, the failure
    surfaces as a Kannada patient being shown and read English rather than as an
    error. That is the worst shape a failure can take here: it looks like the
    kiosk working.

    Not a replacement for ``sarvam-translate:v1``, which is purpose-built for
    Indic pairs and stays the primary. This is the rung below it.
    """
    from app.services.summary.llm import main_api_is_configured, post_chat_completion

    if not main_api_is_configured():
        raise TranslationUnavailableError("no hosted model configured for fallback translation")

    source_name = languages.from_bcp47(source, fallback="en")
    target_name = languages.from_bcp47(target, fallback="en")

    prompt = _AZURE_TRANSLATE_USER.format(
        source_name=languages.get(source_name).english_name,
        target_name=languages.get(target_name).english_name,
        text=chunk,
    )

    try:
        content = await post_chat_completion(
            [
                {"role": "system", "content": _AZURE_TRANSLATE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
            temperature=0.2,
        )
        translated = str((json.loads(content) or {}).get("translation", "")).strip()
    except Exception as exc:  # noqa: BLE001 - any failure means "unavailable"
        raise TranslationUnavailableError(f"fallback translation failed: {exc}") from exc

    if not translated:
        raise TranslationUnavailableError("fallback translation returned no text")
    return translated


async def _translate_chunk(
    client: httpx.AsyncClient,
    chunk: str,
    source: str,
    target: str,
) -> str:
    """Translate one chunk: Sarvam first, then the hosted model.

    Sarvam stays primary because ``sarvam-translate:v1`` is built for Indic pairs
    and keeps a formal register suited to a clinical document. Azure is the rung
    below, so a spent account costs quality rather than costing the patient their
    language entirely.
    """
    try:
        return await _translate_chunk_sarvam(client, chunk, source, target)
    except TranslationUnavailableError as exc:
        logger.info(
            "translation: Sarvam unavailable (%s); falling back to the hosted model",
            str(exc)[:150],
        )

    return await _translate_chunk_azure(chunk, source, target)


#: Cache of English source text -> target language -> translation.
#:
#: The strings translated out of English are a fixed, small set: four consent
#: sections and a few hundred interview prompts drawn from a closed ontology.
#: The same handful therefore repeats for every patient all day, so caching turns
#: per-visit translation cost into per-process cost. Bounded by the ontology
#: rather than by patient volume, so it cannot grow without limit.
_OUTBOUND_CACHE: dict[tuple[str, str], str] = {}


async def translate_from_english(text: str, target_language: str) -> str | None:
    """Translate English source text into the patient's language.

    Used for text the kiosk *speaks*: consent sections and interview prompts
    exist only in English and Hindi, so without this a patient who chose Kannada
    was read the consent aloud in English — audio they cannot act on, which is
    not informed consent in any meaningful sense.

    Returns ``None`` when translation is unavailable, leaving the caller to fall
    back to the English source. That is a worse experience but an honest one, and
    the alternative is silence.

    NOTE this is machine translation. It is a clear improvement on reading a
    patient terms in a language they do not speak, but it is not a substitute for
    reviewed human translation of consent wording, and the language a section was
    actually delivered in is recorded so an audit can tell the difference.
    """
    target = languages.get(target_language)
    if target.code == "en":
        return text
    if not target.translate:
        return None

    cache_key = (text, target.code)
    cached = _OUTBOUND_CACHE.get(cache_key)
    if cached is not None:
        return cached

    chunks = _split_for_translation(text)
    if not chunks:
        return ""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            parts = [
                await _translate_chunk(client, chunk, "en-IN", target.bcp47) for chunk in chunks
            ]
    except TranslationUnavailableError as exc:
        logger.warning("translation: could not render text in %s (%s)", target.code, str(exc)[:200])
        return None

    translated = "\n\n".join(part for part in parts if part)
    _OUTBOUND_CACHE[cache_key] = translated
    return translated


async def translate_many_from_english(texts: list[str], target_language: str) -> list[str | None]:
    """Translate several English strings at once, concurrently.

    A question carries a prompt plus up to eight option labels. Translating them
    one after another would cost eight round trips before the kiosk could show
    the question — several seconds of dead air for the first patient in a given
    language. Issued together instead, so it costs roughly one.

    Cached entries are resolved without a request, so this is nearly free once a
    language has been seen: the interview ontology is closed, so the same few
    hundred strings recur for every patient after the first.

    Returns a list positionally matching ``texts``, with ``None`` where a string
    could not be translated.
    """
    if not texts:
        return []

    target = languages.get(target_language)
    if target.code == "en":
        return list(texts)

    return list(
        await asyncio.gather(*(translate_from_english(text, target.code) for text in texts))
    )


async def translate_to_english(text: str, source_language: str) -> str:
    """Translate ``text`` into English.

    Raises :class:`TranslationUnavailableError` rather than returning the
    original on failure, so the caller decides explicitly whether to proceed
    untranslated. Silently returning the input would let a Santali transcript
    reach the summariser looking like a successful translation.
    """
    source = languages.get(source_language)
    if source.code == "en":
        return text

    if not source.translate:
        raise TranslationUnavailableError(
            f"Sarvam cannot translate {source.english_name} ({source.code})"
        )

    chunks = _split_for_translation(text)
    if not chunks:
        return ""

    if len(chunks) > 1:
        logger.info(
            "translation: %s transcript split into %d chunks for the 2000-char limit",
            source.code,
            len(chunks),
        )

    async with httpx.AsyncClient(timeout=60.0) as client:
        translated = [
            await _translate_chunk(client, chunk, source.bcp47, "en-IN") for chunk in chunks
        ]

    return "\n\n".join(part for part in translated if part)
