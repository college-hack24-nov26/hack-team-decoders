"""LLM summarizer — constrained to the fixed structured schema.

The prompt template forces the model to output JSON matching StructuredSummary.
The output is validated with Pydantic before being stored — if the model freestyles
the structure, we catch it here rather than letting garbage reach the physician.

Two paths, selected by the router module:
- Main API: hosted LLM (OpenAI-compatible endpoint) — better quality, needs internet
- Local Offline: local model via Ollama or similar — works without connectivity

The routing decision is NOT made here. This module provides two functions:
`summarize_main_api` and `summarize_local`, and the router picks which to call.
"""

from __future__ import annotations

import json
import logging
import re

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.services.summary.retrieval import RetrievedContext
from app.services.summary.schemas import StructuredSummary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a clinical documentation assistant for an Indian OPD (outpatient department).
You produce structured clinical summaries from patient interview data and medical documents.

CRITICAL RULES:
1. Output ONLY valid JSON matching the exact schema provided. No markdown, no explanation.
2. You are NOT making a diagnosis. The "clinical_impression" field is a SUGGESTED impression
   that the physician will verify, edit, or reject.
3. Write "hpi.narrative" as a flowing 3-4 sentence clinical narrative — the story of
   this illness in prose, the way a clinician would present it, not a list of fragments.
   The other HPI fields (site, onset, etc.) stay as short structured values, and every
   other field is at most 1-3 sentences.
4. Use medical terminology appropriate for a physician audience. Every physician-facing
   field is in English (the physician's working language).
5. "patient_summary" is the ONE exception: write it in {patient_language} — the patient's
   own language — in that language's own script. Two short, plain, reassuring sentences
   a frightened non-clinician can understand. No jargon, no numbers they cannot act on.
   It is read aloud to the patient at the end of the visit.
6. "sources" maps each section you filled to where it came from: "interview" (the patient
   said it), "document" (from an uploaded report), or "ai-inferred" (you concluded it).
   An inferred line gets more physician scrutiny, so be honest about which is which.
7. If information is not available from the interview or documents, leave the field empty ("").
8. Never fabricate information. Only use data present in the provided context.
9. Summarize red flags prominently in the red_flags_summary field.
10. Leave "physician_notes" as an empty string — the physician fills it themselves.
"""

USER_PROMPT_TEMPLATE = """Based on the following patient interview data and medical documents,
produce a structured clinical summary in JSON format.

The patient's own language is {patient_language}. Write patient_summary in that language;
everything else in English.

{context}

=== REQUIRED OUTPUT SCHEMA ===
{{
  "chief_complaint": "string",
  "hpi": {{
    "narrative": "string - a 3-4 sentence clinical narrative in prose",
    "site": "string",
    "onset": "string",
    "character": "string",
    "radiation": "string",
    "associations": "string",
    "time_course": "string",
    "exacerbating_relieving": "string",
    "severity": "string"
  }},
  "past_medical_history": "string",
  "past_surgical_history": "string",
  "drug_history": [{{"drug": "string", "dose": "string", "frequency": "string"}}],
  "allergies": "string",
  "family_history": "string",
  "personal_history": "string",
  "review_of_systems": "string",
  "prior_investigations": [{{"test": "string", "value": "string", "unit": "string", "reference_range": "string", "is_abnormal": boolean, "date": "string"}}],
  "ayush_assessment": "string (overall Ayurvedic assessment, only if AYUSH mode)",
  "ayush_prakriti": "string (Prakriti determination — dominant dosha, only if AYUSH mode)",
  "ayush_vikriti": "string (current dosha imbalance, only if AYUSH mode)",
  "ayush_ashtavidha": "string (Ashtavidha Pariksha findings, only if AYUSH mode)",
  "ayush_nidana": "string (Nidana/causative factors + Upashaya/relief, only if AYUSH mode)",
  "ayush_ahara_vihara": "string (diet + lifestyle assessment, only if AYUSH mode)",
  "ayush_treatment_direction": "string (Shamana or Shodhana direction, NOT a prescription, only if AYUSH mode)",
  "clinical_impression": "string - SUGGESTED impression only, NOT a diagnosis",
  "red_flags_summary": "string - summarize any red flags that fired",
  "patient_summary": "string - 2 plain sentences in {patient_language}, for the patient",
  "physician_notes": "",
  "sources": {{"chief_complaint": "interview|document|ai-inferred", "hpi": "...", "...": "..."}}
}}

Output ONLY the JSON. No other text."""


# ---------------------------------------------------------------------------
# Main API path (hosted LLM — OpenAI or Gemini)
# ---------------------------------------------------------------------------

# Gemini's OpenAI-compatible endpoint
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

#: Model families that reject the legacy sampling parameters.
#:
#: GPT-5.x and the o-series are reasoning models: they spend tokens thinking
#: before answering, so ``temperature``/``top_p`` were removed from the request
#: schema rather than merely ignored. Sending ``temperature`` returns HTTP 400
#: ("Only the default (1) value is supported"), which the router would catch and
#: treat as a dead main_api path, silently demoting every summary to the
#: deterministic tier. Matched against the *deployment* name on Azure.
_NO_SAMPLING_PARAMS = re.compile(
    r"(^|[-_/])(gpt-5|o1|o3|o4)([-_.]|$)",
    re.IGNORECASE,
)

#: Substrings in a 400 body that mean "you sent a parameter I don't accept".
#: Azure deployment names are arbitrary, so the name check above can miss. This
#: is the backstop: retry once without the sampling params.
_UNSUPPORTED_PARAM_MARKERS = (
    "unsupported_value",
    "unsupported parameter",
    "unsupported_parameter",
    "does not support",
    "only the default",
)


def _rejects_sampling_params(model: str) -> bool:
    """Whether ``model`` is a reasoning model that refuses ``temperature``."""
    return bool(_NO_SAMPLING_PARAMS.search(model or ""))


def _is_unsupported_param_error(response: httpx.Response) -> bool:
    """Whether a 400 is complaining about a parameter we can simply drop."""
    if response.status_code != 400:
        return False
    body = response.text.lower()
    return any(marker in body for marker in _UNSUPPORTED_PARAM_MARKERS)


# Extra instruction appended to the user prompt for providers that don't
# support response_format: json_object (i.e. Gemini). OpenAI enforces JSON
# mode at the API level so doesn't need this.
_JSON_INSTRUCTION = (
    "\n\nIMPORTANT: Your response must be ONLY valid JSON. "
    "No markdown fences, no explanation, no preamble. "
    "Start your response with { and end with }."
)


def _patient_language_name(context: RetrievedContext) -> str:
    """English name of the patient's language, for the prompt's patient_summary rule.

    The model is told to write patient_summary in this language; the name (not the
    code) is used because "Marathi" steers a model far more reliably than "mr".
    Falls back to English, which is a safe default — an English patient_summary is
    still usable, whereas a blank language instruction is not.
    """
    from app.interview import languages

    try:
        return languages.get(context.patient_language).english_name
    except Exception:  # noqa: BLE001 - name resolution must never break a summary
        return "English"


def main_api_is_configured() -> bool:
    """Whether any hosted LLM provider is usable.

    Lives here rather than in the router because this module already owns the
    provider precedence rules, and the two drifting apart is what broke: the
    router gated solely on ``MAIN_LLM_API_KEY``, so a fully configured Azure
    deployment was never attempted. Summaries silently came out of the
    deterministic tier while the dashboard reported them as such and nobody
    connected that to "Azure is not wired up".
    """
    settings = get_settings()
    if settings.main_llm_api_key:
        return True
    return bool(settings.azure_openai_endpoint and settings.azure_openai_api_key)


async def post_chat_completion(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = True,
    temperature: float | None = 0.1,
    timeout: float = 60.0,
) -> str:
    """Send a chat completion to whichever hosted provider is configured.

    Returns the assistant's message content, with markdown fences already
    stripped. Raises on a non-2xx response so callers can treat failure as
    failure rather than as empty output.

    This exists so there is exactly one place that knows how to reach a hosted
    model. The provider precedence ladder, the Azure deployment-vs-model
    distinction, the dual Azure auth headers and the GPT-5.x sampling-parameter
    dance are all subtle enough that a second copy would drift — which is the
    failure this codebase has already had once, when the router's idea of
    "configured" diverged from this module's and every summary silently came out
    of the deterministic tier.

    Args:
        messages: OpenAI-format chat messages.
        json_mode: Ask the provider to guarantee JSON. Gemini has no such
            parameter, so for Gemini this appends an instruction to the last
            user message instead.
        temperature: Sampling temperature, or None to omit it entirely.
            Ignored for reasoning models, which reject it.
        timeout: Per-request timeout in seconds.
    """
    settings = get_settings()
    provider = settings.main_llm_provider.lower().strip()
    api_key = settings.main_llm_api_key
    is_gemini = provider == "gemini"

    # Decide whether to take the Azure OpenAI / Foundry v1 path.
    #
    # Precedence is explicit-config-first, so Azure credentials sitting in the
    # environment can never hijack a deliberately configured provider:
    #   1. MAIN_LLM_PROVIDER=azure          -> Azure, always
    #   2. MAIN_LLM_PROVIDER=gemini         -> never Azure
    #   3. MAIN_LLM_ENDPOINT set explicitly -> never Azure (honour the endpoint,
    #      e.g. Groq / Together / a self-hosted gateway)
    #   4. otherwise, Azure creds present   -> Azure (zero-config convenience)
    if provider == "azure":
        use_azure = True
    elif is_gemini or settings.main_llm_endpoint:
        use_azure = False
    else:
        use_azure = bool(settings.azure_openai_endpoint and settings.azure_openai_api_key)

    azure_base_url: str | None = None
    if use_azure:
        from app.services.azure_ai import get_azure_openai_v1_base_url

        azure_base_url = get_azure_openai_v1_base_url()
        if azure_base_url is None:
            if provider == "azure":
                raise RuntimeError(
                    "MAIN_LLM_PROVIDER=azure but Azure OpenAI is not configured. "
                    "Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY."
                )
            logger.warning(
                "summary.llm: Azure OpenAI partially configured; falling back to "
                "the default OpenAI-compatible path"
            )

    # Resolve endpoint — Azure first, then explicit config, then provider default
    if azure_base_url:
        # The Azure/Foundry v1 API speaks the OpenAI wire format, so it reuses
        # the same async httpx call below. That keeps a single tested transport
        # for every hosted provider and avoids the sync-SDK-inside-async-def
        # trap, which would block the event loop and stall the red-flag path.
        endpoint = f"{azure_base_url}/chat/completions"
        # Azure addresses a *deployment*, not a bare model name.
        model = settings.azure_openai_deployment
        # v1 takes bearer auth; ``api-key`` is sent too so a classic-style
        # endpoint pasted into AZURE_OPENAI_ENDPOINT still authenticates.
        api_key = settings.azure_openai_api_key
        logger.info(
            "summary.llm: using Azure OpenAI v1 (deployment=%s)",
            settings.azure_openai_deployment,
        )
    elif settings.main_llm_endpoint:
        endpoint = settings.main_llm_endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        model = settings.main_llm_model
    elif is_gemini:
        endpoint = _GEMINI_ENDPOINT
        model = settings.main_llm_model
    else:
        endpoint = _OPENAI_ENDPOINT
        model = settings.main_llm_model

    payload: dict = {"model": model, "messages": list(messages)}

    # Gemini has no response_format, so JSON is enforced through the prompt.
    if json_mode and is_gemini:
        payload["messages"] = _append_json_instruction(payload["messages"])
    elif json_mode:
        payload["response_format"] = {"type": "json_object"}

    # Reasoning models (GPT-5.x, o-series) removed temperature from the schema
    # and 400 on it. Everything else still wants it low: this is factual
    # extraction from what the patient said, not creative writing.
    if temperature is not None and not _rejects_sampling_params(model):
        payload["temperature"] = temperature

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        if azure_base_url:
            headers["api-key"] = api_key

    # ------------------------------------------------------------------
    # Gemini path: rotate through the key pool on quota / auth failures.
    # Azure and OpenAI use a single org key and have no pool, so they go
    # through the simple one-shot path below.
    # ------------------------------------------------------------------
    if is_gemini:
        from app.services.google_keys import (
            acquire_key as gk_acquire,
        )
        from app.services.google_keys import (
            attempt_budget as gk_budget,
        )
        from app.services.google_keys import (
            report_key_failure as gk_fail,
        )
        from app.services.google_keys import (
            report_key_success as gk_ok,
        )

        # The legacy single-key var is the fallback for pools that aren't
        # configured; gk_acquire honours it automatically.
        fallback_key = settings.main_llm_api_key

        async with httpx.AsyncClient(timeout=timeout) as client:
            for _attempt in range(gk_budget()):
                key = gk_acquire(fallback_key)
                if key is None:
                    raise RuntimeError(
                        "Gemini: no usable API key available. "
                        "Set MAIN_LLM_API_KEY or GOOGLE_AI_API_KEY[S/_N]."
                    )

                gemini_headers = {**headers, "Authorization": f"Bearer {key}"}

                response = await client.post(endpoint, json=payload, headers=gemini_headers)

                # Backstop: reasoning-model parameter rejection (not a key fault).
                if "temperature" in payload and _is_unsupported_param_error(response):
                    logger.info(
                        "summary.llm: %s rejected sampling params; retrying without temperature",
                        model,
                    )
                    payload.pop("temperature", None)
                    response = await client.post(endpoint, json=payload, headers=gemini_headers)

                if response.status_code >= 400:
                    logger.warning(
                        "summary.llm: Gemini returned HTTP %s: %s",
                        response.status_code,
                        response.text[:500],
                    )
                    if gk_fail(
                        key, response.status_code, body=response.text, fallback=fallback_key
                    ):
                        continue  # another key is available — try it
                    response.raise_for_status()

                gk_ok(key)
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                return _strip_markdown_fences(content)

        raise RuntimeError("Gemini: exhausted every API key without a successful response")

    # ------------------------------------------------------------------
    # Azure / OpenAI path: single key, one shot, no pool rotation.
    # ------------------------------------------------------------------
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload, headers=headers)

        # Backstop for a deployment name the pattern above didn't recognise.
        if "temperature" in payload and _is_unsupported_param_error(response):
            logger.info(
                "summary.llm: %s rejected sampling params; retrying without temperature",
                model,
            )
            payload.pop("temperature", None)
            response = await client.post(endpoint, json=payload, headers=headers)

        response.raise_for_status()
        result = response.json()

    content = result["choices"][0]["message"]["content"]
    return content


def _append_json_instruction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Append the JSON-only instruction to the last user message.

    Appended to the user turn rather than the system prompt because Gemini
    follows recency more reliably than role precedence for format constraints.
    """
    updated = [dict(m) for m in messages]
    for message in reversed(updated):
        if message.get("role") == "user":
            message["content"] = f"{message.get('content', '')}{_JSON_INSTRUCTION}"
            return updated
    updated.append({"role": "user", "content": _JSON_INSTRUCTION.strip()})
    return updated


async def summarize_main_api(
    context: RetrievedContext, prompt_text: str | None = None
) -> StructuredSummary:
    """Call the hosted LLM API and return a validated StructuredSummary.

    Supports:
      - Azure OpenAI / Microsoft Foundry via the v1 API
        Set MAIN_LLM_PROVIDER=azure to force it, or just set
        AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY and leave
        MAIN_LLM_ENDPOINT unset to have it picked up automatically.
        An explicitly configured MAIN_LLM_ENDPOINT or a gemini provider
        always wins over ambient Azure credentials.

      - OpenAI and compatible endpoints (Groq, Together, etc.)
        Set MAIN_LLM_PROVIDER=openai (default)
        Set MAIN_LLM_MODEL=gpt-4o-mini (or any OpenAI model)

      - Google Gemini via its OpenAI-compatible endpoint
        Set MAIN_LLM_PROVIDER=gemini
        Set MAIN_LLM_API_KEY to your Gemini API key
        Set MAIN_LLM_MODEL=gemini-2.0-flash or gemini-1.5-flash
        Get key at: https://aistudio.google.com/apikey

    The key difference: Gemini does not support response_format: json_object.
    For Gemini, JSON output is enforced via the prompt instead, which works
    reliably with gemini-1.5-flash and gemini-2.0-flash.
    """
    # ``prompt_text`` is the router's English translation for a language the
    # model handles poorly. Falls back to the raw context when absent.
    user_prompt = USER_PROMPT_TEMPLATE.format(
        context=prompt_text if prompt_text is not None else context.format_for_prompt(),
        patient_language=_patient_language_name(context),
    )

    content = await post_chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=True,
        temperature=0.1,
    )
    return _parse_and_validate(content)


# ---------------------------------------------------------------------------
# Local Offline path (Ollama or compatible)
# ---------------------------------------------------------------------------


async def summarize_local(
    context: RetrievedContext, prompt_text: str | None = None
) -> StructuredSummary:
    """Call the local LLM (Ollama) for offline summarization.

    The local model is typically smaller/less capable, so the output may need
    more aggressive validation. Quality is traded for availability.
    """
    settings = get_settings()
    endpoint = settings.local_llm_endpoint or "http://localhost:11434"
    endpoint = f"{endpoint.rstrip('/')}/api/chat"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        context=prompt_text if prompt_text is not None else context.format_for_prompt(),
        patient_language=_patient_language_name(context),
    )

    payload = {
        "model": settings.local_llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        result = response.json()

    content = result.get("message", {}).get("content", "{}")
    return _parse_and_validate(content)


# ---------------------------------------------------------------------------
# Fallback: rule-based summary (no LLM at all)
# ---------------------------------------------------------------------------


def summarize_deterministic(context: RetrievedContext) -> StructuredSummary:
    """Produce a summary without any LLM — purely from structured interview data.

    This is the guaranteed-available path: no API key needed, no model needed,
    works fully offline. The output is less polished than an LLM summary (it's
    essentially a reformatted dump of the interview answers) but it's always
    available and always correct — it can't hallucinate because it only copies.

    Used as the final fallback when both Main API and Local model fail.
    """
    answers = context.answers_by_field()
    entities = context.entities_grouped()

    # Build HPI from SOCRATES fields
    hpi_fields = {k.replace("hpi.", ""): v for k, v in answers.items() if k.startswith("hpi.")}

    # Build drug history from entities
    drug_history = []
    for med in entities.get("medication", []):
        drug_history.append(
            {
                "drug": med.get("drug", "Unknown"),
                "dose": med.get("dose", ""),
                "frequency": med.get("frequency", ""),
            }
        )
    # Also from interview answer if available
    if answers.get("drug_history.current_meds"):
        drug_history.append(
            {
                "drug": answers["drug_history.current_meds"],
                "dose": "",
                "frequency": "",
            }
        )

    # Build investigations from entities
    investigations = []
    for inv in entities.get("investigation_value", []):
        investigations.append(
            {
                "test": inv.get("test", "Unknown"),
                "value": str(inv.get("value", "")),
                "unit": inv.get("unit", ""),
                "reference_range": inv.get("ref_range", ""),
                "is_abnormal": inv.get("is_abnormal", False),
                "date": inv.get("date", ""),
            }
        )

    # Red flags summary
    red_flags_text = ""
    if context.red_flags:
        flags = [f"{rf.symptom} (severity: {rf.severity})" for rf in context.red_flags]
        red_flags_text = "RED FLAGS TRIGGERED: " + "; ".join(flags)

    # AYUSH assessment
    ayush_text = ""
    ayush_prakriti = ""
    ayush_vikriti = ""
    ayush_ashtavidha = ""
    ayush_nidana = ""
    ayush_ahara_vihara = ""
    ayush_treatment_direction = ""
    if context.mode == "ayush":
        ayush_fields = {k: v for k, v in answers.items() if k.startswith("ayush.")}
        if ayush_fields:
            ayush_text = "; ".join(f"{k.split('.')[-1]}: {v}" for k, v in ayush_fields.items())

            # Prakriti
            prakriti_parts = []
            if answers.get("ayush.prakriti"):
                prakriti_parts.append(f"Dominant dosha: {answers['ayush.prakriti']}")
            if answers.get("ayush.prakriti.skin_type"):
                prakriti_parts.append(f"Skin: {answers['ayush.prakriti.skin_type']}")
            if answers.get("ayush.prakriti.temperament"):
                prakriti_parts.append(f"Temperament: {answers['ayush.prakriti.temperament']}")
            ayush_prakriti = "; ".join(prakriti_parts)

            # Vikriti
            if answers.get("ayush.vikriti"):
                ayush_vikriti = f"Aggravated dosha: {answers['ayush.vikriti']}"

            # Ashtavidha
            ashta_parts = []
            for key in ["mutra", "mala", "jihva", "shabda", "akruti"]:
                val = answers.get(f"ayush.ashtavidha.{key}")
                if val:
                    ashta_parts.append(f"{key.capitalize()}: {val}")
            ayush_ashtavidha = "; ".join(ashta_parts)

            # Nidana
            nidana_parts = []
            if answers.get("ayush.nidana.hetu"):
                nidana_parts.append(f"Hetu: {answers['ayush.nidana.hetu']}")
            if answers.get("ayush.nidana.purvarupa"):
                nidana_parts.append(f"Purvarupa: {answers['ayush.nidana.purvarupa']}")
            if answers.get("ayush.nidana.upashaya"):
                nidana_parts.append(f"Upashaya: {answers['ayush.nidana.upashaya']}")
            ayush_nidana = "; ".join(nidana_parts)

            # Ahara-Vihara
            av_parts = []
            if answers.get("ayush.ahara.rasa_preference"):
                av_parts.append(f"Rasa: {answers['ayush.ahara.rasa_preference']}")
            if answers.get("ayush.ahara.meal_pattern"):
                av_parts.append(f"Meals: {answers['ayush.ahara.meal_pattern']}")
            if answers.get("ayush.vihara.dinacharya"):
                av_parts.append(f"Dinacharya: {answers['ayush.vihara.dinacharya']}")
            if answers.get("ayush.vihara.nidra"):
                av_parts.append(f"Nidra: {answers['ayush.vihara.nidra']}")
            if answers.get("ayush.ahara_vihara"):
                av_parts.append(answers["ayush.ahara_vihara"])
            ayush_ahara_vihara = "; ".join(av_parts)

    from app.services.summary.schemas import HPISection, InvestigationItem, MedicationItem

    return StructuredSummary(
        chief_complaint=context.chief_complaint,
        hpi=HPISection(
            narrative=hpi_fields.get("description", ""),
            site=hpi_fields.get("site", ""),
            onset=hpi_fields.get("onset", ""),
            character=hpi_fields.get("character", ""),
            radiation=hpi_fields.get("radiation", ""),
            associations=hpi_fields.get("associations", ""),
            time_course=hpi_fields.get("time_course", ""),
            exacerbating_relieving=(
                f"Worse: {hpi_fields.get('exacerbating', '')}; "
                f"Better: {hpi_fields.get('relieving', '')}"
            ).strip("; "),
            severity=hpi_fields.get("severity", ""),
        ),
        past_medical_history=answers.get("past_medical.conditions", ""),
        past_surgical_history=answers.get("past_surgical.history", ""),
        drug_history=[MedicationItem(**m) for m in drug_history],
        allergies=answers.get("allergy.known", ""),
        family_history=answers.get("family_history.conditions", ""),
        personal_history=(
            f"Smoking: {answers.get('personal_history.smoking', 'N/A')}; "
            f"Alcohol: {answers.get('personal_history.alcohol', 'N/A')}"
        ),
        review_of_systems="; ".join(
            f"{k.split('.')[-1]}: {'Yes' if v else 'No'}"
            for k, v in answers.items()
            if k.startswith("ros.")
        ),
        prior_investigations=[InvestigationItem(**i) for i in investigations],
        ayush_assessment=ayush_text,
        ayush_prakriti=ayush_prakriti,
        ayush_vikriti=ayush_vikriti,
        ayush_ashtavidha=ayush_ashtavidha,
        ayush_nidana=ayush_nidana,
        ayush_ahara_vihara=ayush_ahara_vihara,
        ayush_treatment_direction=ayush_treatment_direction,
        clinical_impression="",  # No LLM = no impression. Honest.
        red_flags_summary=red_flags_text,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences that some models add despite instructions.

    Handles ```json ... ``` and ``` ... ``` wrapping.
    """
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        # Remove closing fence
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


class SummaryValidationError(RuntimeError):
    """An LLM returned output that does not match the fixed schema."""


def _parse_and_validate(raw_json: str) -> StructuredSummary:
    """Parse LLM output and validate it against the fixed schema.

    Raises rather than returning a placeholder. The earlier version swallowed
    the failure and returned an empty-but-valid StructuredSummary, which the
    router could not distinguish from success — so a Main API that returned
    prose instead of JSON counted as a win, and the local and deterministic
    paths never ran. An unparseable response has to look like a failure for the
    failover to mean anything.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON output: %s", raw_json[:300])
        raise SummaryValidationError(f"response was not JSON: {exc}") from exc

    try:
        return StructuredSummary.model_validate(data)
    except ValidationError as exc:
        logger.warning("LLM JSON did not match the summary schema: %s", exc)
        raise SummaryValidationError(f"response did not match the schema: {exc}") from exc
