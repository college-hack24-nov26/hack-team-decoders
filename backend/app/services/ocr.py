"""OCR pipeline â€” printed text extraction from document images.

Supported engines:
  1. SarvamOcrEngine â€” Sarvam Vision Document AI. Recommended: covers all 22
     constitutionally recognised Indian languages plus English, and is the only
     engine here that reads handwriting. Needs SARVAM_API_KEY (the same key
     already used for Saaras STT and Bulbul TTS). Async job API under the hood.
  2. TesseractOcrEngine â€” local and free, but needs the `tesseract` binary
     installed on the host, which it often is not.
  3. GoogleVisionOcrEngine â€” cloud, 1000 free requests/month.
     Supports two auth methods:
       (a) API key â€” set GOOGLE_VISION_API_KEY in .env
       (b) Service account JSON â€” set GOOGLE_VISION_CREDENTIALS_PATH in .env
  4. AzureDocIntelligenceOcrEngine â€” STUB (task A4), raises.
  5. HandwritingOcrEngine â€” STUB, superseded by Sarvam when a key is present.

Selection:
  Set OCR_ENGINE=sarvam | tesseract | google_vision | azure in .env.
  Default is "tesseract".

Interface:
    `OcrEngine.extract_text(image_path) -> str`

Every engine is synchronous. Sarvam's submits a job and polls, so callers in
async handlers must dispatch to a threadpool rather than awaiting inline â€” see
the documents upload route.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class OcrEngine(ABC):
    """Interface for all OCR engines."""

    @abstractmethod
    def extract_text(self, image_path: Path) -> str:
        """Run OCR on an image file. Returns extracted UTF-8 text."""
        ...

    @abstractmethod
    def supports_handwriting(self) -> bool: ...


# ---------------------------------------------------------------------------
# Tesseract (local, free)
# ---------------------------------------------------------------------------


class TesseractOcrEngine(OcrEngine):
    """Tesseract-based OCR for printed text.

    Requires `tesseract` binary + `pytesseract` Python package.
    Works well for clean printed Indian prescriptions and lab reports.
    Does NOT handle handwriting.
    """

    def extract_text(self, image_path: Path) -> str:
        try:
            import pytesseract
        except ImportError as e:
            raise RuntimeError("pytesseract is not installed. Run: pip install pytesseract") from e

        text: str = pytesseract.image_to_string(
            str(image_path),
            lang="eng+hin",
            config="--psm 6",  # assume a single uniform block of text
        )
        return text.strip()

    def supports_handwriting(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Google Cloud Vision (cloud, 1000 free/month, best accuracy)
# ---------------------------------------------------------------------------


class GoogleVisionOcrEngine(OcrEngine):
    """Google Cloud Vision OCR â€” supports API key and service account JSON auth.

    Auth method is chosen automatically:
      - If GOOGLE_VISION_API_KEY is set â†’ uses simple REST with API key
      - If GOOGLE_VISION_CREDENTIALS_PATH is set â†’ uses google-cloud-vision
        library with service account credentials
      - If both are set â†’ API key takes precedence (simpler, lighter)

    Handles printed text in English + Hindi with excellent table detection.
    1,000 requests/month on the free tier (no credit card for first 90 days).
    """

    def __init__(self, api_key: str = "", credentials_path: str = "") -> None:
        # ``api_key`` is the legacy single-key setting (GOOGLE_VISION_API_KEY).
        # The pool (google_keys) is checked automatically via the helpers below,
        # so callers that set only GOOGLE_AI_API_KEY[S/_N] and leave api_key
        # blank still work.
        self._api_key = api_key
        self._credentials_path = credentials_path

        from app.services.google_keys import acquire_key as _gk_acquire

        if not api_key and not credentials_path and not _gk_acquire():
            raise RuntimeError(
                "GoogleVisionOcrEngine requires GOOGLE_VISION_API_KEY, "
                "GOOGLE_AI_API_KEY[S/_N], or GOOGLE_VISION_CREDENTIALS_PATH "
                "to be set in .env"
            )

    def extract_text(self, image_path: Path) -> str:
        from app.services.google_keys import acquire_key as _gk_acquire

        # Use API-key path when any key is available (pool or single legacy key).
        if self._api_key or _gk_acquire(self._api_key):
            return self._extract_via_api_key(image_path)
        return self._extract_via_service_account(image_path)

    def supports_handwriting(self) -> bool:
        return False  # Could enable DOCUMENT_TEXT_DETECTION for handwriting

    # -- Option A: API Key with pool rotation --------------------------------

    def _extract_via_api_key(self, image_path: Path) -> str:
        """Call Vision API using API key + httpx, rotating keys on quota failures."""
        import httpx

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

        image_bytes = image_path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "requests": [
                {
                    "image": {"content": image_b64},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}],
                    "imageContext": {"languageHints": ["en", "hi"]},
                }
            ]
        }

        for _attempt in range(gk_budget()):
            key = gk_acquire(self._api_key)
            if key is None:
                raise RuntimeError("Google Vision OCR: no usable API key available")

            url = f"https://vision.googleapis.com/v1/images:annotate?key={key}"
            response = httpx.post(url, json=payload, timeout=30.0)

            if response.status_code != 200:
                logger.warning(
                    "ocr.google_vision: HTTP %s: %s",
                    response.status_code,
                    response.text[:500],
                )
                if gk_fail(key, response.status_code, body=response.text, fallback=self._api_key):
                    continue  # another key available — try it
                raise RuntimeError(
                    f"Google Vision API returned {response.status_code}: {response.text[:300]}"
                )

            gk_ok(key)
            result = response.json()
            responses = result.get("responses", [])
            if not responses:
                return ""
            annotation = responses[0].get("fullTextAnnotation", {})
            return annotation.get("text", "").strip()

        raise RuntimeError("Google Vision OCR: exhausted every key without a successful response")

    def _extract_via_service_account(self, image_path: Path) -> str:
        """Call Vision API using the google-cloud-vision library + service account.

        Requires: pip install google-cloud-vision
        Set GOOGLE_APPLICATION_CREDENTIALS env var or pass the path directly.
        """
        try:
            from google.cloud import vision
            from google.oauth2 import service_account
        except ImportError as e:
            raise RuntimeError(
                "google-cloud-vision is not installed. "
                "Run: pip install google-cloud-vision\n"
                "Or use the API key approach instead (set GOOGLE_VISION_API_KEY)."
            ) from e

        credentials = service_account.Credentials.from_service_account_file(
            self._credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-vision"],
        )

        client = vision.ImageAnnotatorClient(credentials=credentials)

        image_bytes = image_path.read_bytes()
        image = vision.Image(content=image_bytes)

        # Use DOCUMENT_TEXT_DETECTION for better table/layout understanding
        response = client.document_text_detection(
            image=image,
            image_context=vision.ImageContext(language_hints=["en", "hi"]),
        )

        if response.error.message:
            raise RuntimeError(f"Google Vision error: {response.error.message}")

        text = response.full_text_annotation.text if response.full_text_annotation else ""
        return text.strip()


# ---------------------------------------------------------------------------
# Sarvam Vision (Document AI) â€” 22 Indian languages + English, printed + handwritten
# ---------------------------------------------------------------------------


class _KeyRejectedError(RuntimeError):
    """The API key was refused, so another pooled key may still work.

    Distinct from an ordinary failure: a 413 or 422 will fail identically on
    every key, whereas a 402 or 429 is about this account only.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class SarvamOcrEngine(OcrEngine):
    """OCR via Sarvam's Document AI, powered by the Sarvam Vision VLM.

    The right default for this project: it is built for Indian-language documents
    and covers all 22 constitutionally recognised languages plus English, which is
    exactly the corpus a rural kiosk sees. It also reads handwriting, so it is the
    first engine here that can attempt a handwritten prescription.

    Unlike the other engines this is an **asynchronous job API**: submit the
    document, poll until the job reaches a terminal state, then fetch results.
    That whole lifecycle is wrapped in a blocking call to satisfy the synchronous
    ``OcrEngine`` interface, so callers must run it off the event loop â€” the
    documents route uses ``run_in_threadpool``.

    Limits worth knowing (all from Sarvam's published constraints):
      - 10 pages per PDF, 10 images per ZIP
      - 200 MB per file
      - 10 requests/minute on every plan

    See https://docs.sarvam.ai/api/api-guides-tutorials/document-intelligence/overview
    """

    BASE_URL = "https://api.sarvam.ai/doc-ai/v1/job"

    #: Job states after which polling should stop.
    TERMINAL_STATES = frozenset({"completed", "partially_completed", "failed", "rejected"})
    #: Terminal states that carry usable output.
    USABLE_STATES = frozenset({"completed", "partially_completed"})

    def __init__(
        self,
        api_key: str,
        language: str = "en-IN",
        model: str = "sarvam-vision-v1",
        handwriting: bool = False,
        timeout_seconds: int = 120,
        poll_seconds: float = 2.0,
    ) -> None:
        self._api_key = api_key
        self._language = language
        self._model = model
        self._handwriting = handwriting
        self._timeout_seconds = timeout_seconds
        self._poll_seconds = poll_seconds

    # -- public interface ---------------------------------------------------

    def extract_text(self, image_path: Path) -> str:
        import httpx

        from app.services.sarvam_keys import (
            acquire_key,
            attempt_budget,
            report_key_failure,
            report_key_success,
        )

        last_error: RuntimeError | None = None

        # One attempt per pooled key. A whole job is retried rather than a single
        # request, because a key that dies mid-poll cannot resume someone else's
        # job â€” the submit has to happen again under the new account.
        for _attempt in range(attempt_budget()):
            key = acquire_key(self._api_key)
            if key is None:
                raise RuntimeError(
                    "Sarvam OCR selected but no usable API key is available. Set "
                    "SARVAM_API_KEY or SARVAM_API_KEYS, or choose "
                    "OCR_ENGINE=tesseract / google_vision."
                )

            # A single client for the whole job so the connection is reused
            # across submit, the poll loop, and the results fetch.
            with httpx.Client(timeout=60.0, headers={"api-subscription-key": key}) as client:
                try:
                    job_id = self._submit(client, image_path)
                    status = self._poll(client, job_id)
                except _KeyRejectedError as rejected:
                    last_error = RuntimeError(str(rejected))
                    if report_key_failure(key, rejected.status_code, fallback=self._api_key):
                        logger.info(
                            "ocr.sarvam: key rejected (HTTP %d); retrying with the "
                            "next pooled key",
                            rejected.status_code,
                        )
                        continue
                    raise last_error from rejected

                if status not in self.USABLE_STATES:
                    raise RuntimeError(
                        f"Sarvam OCR job {job_id} finished as '{status}' with no usable output."
                    )

                report_key_success(key)
                return self._fetch_text(client, job_id)

        raise last_error or RuntimeError("Sarvam OCR: every available key was rejected")

    def supports_handwriting(self) -> bool:
        # Sarvam Vision reads handwritten documents; content_type selects the mode.
        return True

    # -- job lifecycle -----------------------------------------------------

    def _submit(self, client, image_path: Path) -> str:
        """Create a digitise job and return its id."""
        data = {
            "language": self._language,
            # "md" keeps layout and reading order as plain-ish text, which suits
            # downstream entity extraction better than HTML tag soup. Sarvam
            # rejects "markdown" â€” the value must be "md".
            "output_format": "md",
            "content_type": "handwritten" if self._handwriting else "printed",
            "model": self._model,
        }

        with image_path.open("rb") as fh:
            response = client.post(
                f"{self.BASE_URL}/digitise",
                data=data,
                files={"file": (image_path.name, fh, self._media_type(image_path))},
            )

        self._raise_for_status(response, "submit")
        job_id = response.json().get("job_id")
        if not job_id:
            raise RuntimeError("Sarvam OCR: digitise response contained no job_id")

        logger.info("ocr.sarvam: job %s submitted for %s", job_id, image_path.name)
        return job_id

    def _poll(self, client, job_id: str) -> str:
        """Block until the job is terminal; return its final status."""
        import time

        deadline = time.monotonic() + self._timeout_seconds

        while True:
            response = client.get(f"{self.BASE_URL}/{job_id}/status")
            self._raise_for_status(response, "status")
            status = str(response.json().get("status", "")).lower()

            if status in self.TERMINAL_STATES:
                logger.info("ocr.sarvam: job %s finished as %s", job_id, status)
                return status

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Sarvam OCR job {job_id} did not finish within "
                    f"{self._timeout_seconds}s (last status: {status or 'unknown'})."
                )

            time.sleep(self._poll_seconds)

    def _fetch_text(self, client, job_id: str) -> str:
        response = client.get(f"{self.BASE_URL}/{job_id}/results", params={"format": "json"})
        self._raise_for_status(response, "results")
        return self._collect_text(response.json()).strip()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _collect_text(payload: object) -> str:
        """Pull every text fragment out of a digitise result, in order.

        Walks the payload rather than indexing a fixed path on purpose. Sarvam
        documents that digitise results contain ``documents`` with blocks
        carrying ``text``, but does not publish the full nesting, and it differs
        by ``output_format``. A recursive collect degrades to "slightly odd
        ordering" if the shape changes, where a hardcoded path would return
        nothing at all and look like an empty document.
        """
        fragments: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    # Skip the annotation/metadata sidecars: they mirror the
                    # content shape and would duplicate every fragment.
                    if key in {"annotations", "usage", "sources", "bbox", "bounding_box"}:
                        continue
                    if key in {"text", "content", "markdown", "md"} and isinstance(value, str):
                        if value.strip():
                            fragments.append(value.strip())
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)

        # De-duplicate while preserving order: a payload that carries both a
        # page-level markdown blob and its constituent blocks would otherwise
        # repeat the whole page.
        seen: set[str] = set()
        unique = [f for f in fragments if not (f in seen or seen.add(f))]
        return SarvamOcrEngine._flatten_html("\n".join(unique))

    @staticmethod
    def _flatten_html(text: str) -> str:
        """Turn HTML tables into plain aligned lines.

        Sarvam preserves tables as HTML even when ``output_format`` is ``md``,
        which is good fidelity and useless to us: ``entity_extraction`` is
        line-oriented, so a lab report arriving as ``<tr><td>HbA1c</td>...``
        yields *zero* investigation values. That is worse than an OCR failure â€”
        the document is marked ``ocr_status=done`` with nothing extracted, so
        nobody notices the values are missing.

        Flattening each row to one line restores the "name value unit range"
        layout the extractor was written against. Measured on a synthetic lab
        report: 0 values recovered before, 4 after, including an abnormal HbA1c.
        """
        if "<" not in text:
            return text

        def cell_text(cell_html: str) -> str:
            # Cells can contain markup and newlines; both collapse to one space.
            plain = re.sub(r"<[^>]+>", " ", cell_html)
            return re.sub(r"\s+", " ", html.unescape(plain)).strip()

        def flatten_table(match: re.Match[str]) -> str:
            rows = []
            for row_html in re.findall(r"(?is)<tr[^>]*>(.*?)</\s*tr\s*>", match.group(0)):
                cells = [
                    cell_text(c)
                    for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</\s*t[dh]\s*>", row_html)
                ]
                line = "   ".join(c for c in cells if c)
                if line:
                    rows.append(line)
            return "\n".join(rows)

        # Only tables are rewritten. A global tag-strip would also fold the
        # newlines in ordinary prose, merging unrelated lines into one.
        text = re.sub(r"(?is)<table[^>]*>.*?</\s*table\s*>", flatten_table, text)

        # Any stray tags left outside a table (headings, emphasis) just go.
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))

        lines = []
        for raw_line in text.splitlines():
            collapsed = re.sub(r"[ \t]{2,}", "   ", raw_line).strip()
            if collapsed:
                lines.append(collapsed)
        return "\n".join(lines)

    @staticmethod
    def _media_type(image_path: Path) -> str:
        return {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".zip": "application/zip",
        }.get(image_path.suffix.lower(), "application/octet-stream")

    @staticmethod
    def _raise_for_status(response, stage: str) -> None:
        """Turn an error response into a message that names the actual problem.

        Billing and rate-limit statuses raise :class:`_KeyRejectedError` so the caller
        can rotate to another pooled key. Everything else is the request's own
        fault â€” rotating on a malformed document would burn the whole pool on it.
        """
        if response.status_code < 400:
            return

        hints = {
            400: "invalid request or schema â€” a PDF over the 10-page limit lands here",
            402: "billing or entitlement problem",
            403: "billing or entitlement problem",
            404: "job not found",
            409: "results requested before the job reached a terminal state",
            413: "file too large (limit 200 MB)",
            422: "invalid or corrupted file format",
            429: "rate limit exceeded (10 requests/minute on all plans)",
            503: "Sarvam billing unavailable",
        }
        hint = hints.get(response.status_code, "")
        detail = response.text[:300]
        message = (
            f"Sarvam OCR {stage} failed: HTTP {response.status_code}"
            f"{f' ({hint})' if hint else ''}. {detail}"
        )

        from app.services.sarvam_keys import EXHAUSTED_STATUSES, RATE_LIMITED_STATUS

        if response.status_code in EXHAUSTED_STATUSES or response.status_code == (
            RATE_LIMITED_STATUS
        ):
            raise _KeyRejectedError(message, response.status_code)

        raise RuntimeError(message)


# ---------------------------------------------------------------------------
# Handwriting stub (out of scope)
# ---------------------------------------------------------------------------


class HandwritingOcrEngine(OcrEngine):
    """STUB â€” handwriting OCR is out of scope for this wave.

    A real implementation would call AI4Bharat OCR or a cloud handwriting
    endpoint. This stub raises NotImplementedError so the system fails
    loudly if accidentally invoked.
    """

    def extract_text(self, image_path: Path) -> str:
        raise NotImplementedError(
            "Handwriting OCR is not implemented in this wave. "
            "Use TesseractOcrEngine or GoogleVisionOcrEngine for printed text, "
            "or implement this class with AI4Bharat / a cloud handwriting service."
        )

    def supports_handwriting(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Azure Document Intelligence (stub â€” full implementation in task A4)
# ---------------------------------------------------------------------------


class AzureDocIntelligenceOcrEngine(OcrEngine):
    """Azure Document Intelligence OCR â€” stub for task A4.

    The full implementation will use the ``azure-ai-documentintelligence`` SDK
    with ``prebuilt-read`` or ``prebuilt-layout`` models for high-quality OCR
    of printed text, tables, and structured documents.

    Supports printed + handwritten text in English, Hindi, and many other
    languages out of the box.
    """

    def extract_text(self, image_path: Path) -> str:
        raise NotImplementedError(
            "Azure Document Intelligence OCR â€” full implementation in task A4. "
            "Set OCR_ENGINE=tesseract or OCR_ENGINE=google_vision to use existing engines."
        )

    def supports_handwriting(self) -> bool:
        return True  # Azure Doc Intelligence handles handwriting natively


# ---------------------------------------------------------------------------
# Factory â€” the only function callers should use
# ---------------------------------------------------------------------------


def _sarvam_engine(settings, handwriting: bool) -> SarvamOcrEngine:
    return SarvamOcrEngine(
        api_key=settings.sarvam_api_key,
        language=settings.sarvam_ocr_language,
        model=settings.sarvam_ocr_model,
        handwriting=handwriting,
        timeout_seconds=settings.sarvam_ocr_timeout_seconds,
        poll_seconds=settings.sarvam_ocr_poll_seconds,
    )


def get_ocr_engine(handwriting: bool = False) -> OcrEngine:
    """Return the configured OCR engine based on settings.

    Selection logic:
      1. handwriting=True â†’ Sarvam Vision when a key is configured, since it is
         the only engine here that actually reads handwriting. Falls back to
         HandwritingOcrEngine (which raises) so the failure stays loud rather
         than silently returning printed-text output for a handwritten page.
      2. OCR_ENGINE=sarvam â†’ SarvamOcrEngine
      3. OCR_ENGINE=azure â†’ AzureDocIntelligenceOcrEngine (still a stub, task A4)
      4. OCR_ENGINE=google_vision â†’ GoogleVisionOcrEngine
         - Uses API key if GOOGLE_VISION_API_KEY is set
         - Falls back to service account JSON if GOOGLE_VISION_CREDENTIALS_PATH is set
      5. Default â†’ TesseractOcrEngine (local, but needs the tesseract binary)

    NOTE: every engine here is synchronous, and Sarvam's is a polling job API.
    Call it from a threadpool, not directly inside an async handler.
    """
    from app.core.config import get_settings

    settings = get_settings()

    if handwriting:
        if settings.sarvam_api_key:
            return _sarvam_engine(settings, handwriting=True)
        return HandwritingOcrEngine()

    if settings.ocr_engine == "sarvam":
        return _sarvam_engine(settings, handwriting=False)

    if settings.ocr_engine == "azure":
        return AzureDocIntelligenceOcrEngine()

    if settings.ocr_engine == "google_vision":
        return GoogleVisionOcrEngine(
            api_key=settings.google_vision_api_key,
            credentials_path=settings.google_vision_credentials_path,
        )

    # Default: Tesseract (local, free, no internet needed)
    return TesseractOcrEngine()
