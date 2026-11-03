"""Sarvam Vision Document AI OCR engine.

Runs against a stubbed transport, so these execute offline and in CI without
touching a paid provider. What they pin is the three-step job lifecycle
(submit -> poll -> results) and the request shape, which is what silently breaks
when a vendor changes their contract.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.ocr import (
    HandwritingOcrEngine,
    SarvamOcrEngine,
    TesseractOcrEngine,
    get_ocr_engine,
)

_JOB_ID = "019fb81e-2543-70bd-a737-b5a2d62a3bb7"


@pytest.fixture()
def document(tmp_path):
    path = tmp_path / "lab-report.pdf"
    path.write_bytes(b"%PDF-1.4 FAKE_SCAN_BYTES")
    return path


class _SarvamStub:
    """Scripted Sarvam Doc AI: records requests, replays a job lifecycle."""

    def __init__(self, statuses=None, results=None, submit_status=201):
        # Statuses are consumed one per poll, so a test can script pending->done.
        self.statuses = list(statuses or ["completed"])
        self.results = (
            results
            if results is not None
            else {
                "type": "digitise",
                "job_id": _JOB_ID,
                "status": "completed",
                "documents": [
                    {
                        "filename": "lab-report.pdf",
                        "pages": [{"blocks": [{"tag": "p", "text": "HbA1c 8.9 %"}]}],
                    }
                ],
            }
        )
        self.submit_status = submit_status
        self.submits: list[httpx.Request] = []
        self.poll_count = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path.endswith("/digitise"):
            self.submits.append(request)
            if self.submit_status >= 400:
                return httpx.Response(self.submit_status, json={"error": "nope"})
            return httpx.Response(
                self.submit_status,
                json={"job_id": _JOB_ID, "status": "pending", "run_id": "run-1"},
            )

        if path.endswith("/status"):
            self.poll_count += 1
            status = self.statuses.pop(0) if self.statuses else "completed"
            return httpx.Response(200, json={"job_id": _JOB_ID, "status": status})

        if path.endswith("/results"):
            return httpx.Response(200, json=self.results)

        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    def install(self, monkeypatch):
        original = httpx.Client

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(self.handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", factory)
        # Nothing should actually sleep between polls in tests.
        monkeypatch.setattr("time.sleep", lambda _s: None)
        return self


def _engine(**kw) -> SarvamOcrEngine:
    defaults = {"api_key": "sk-test", "poll_seconds": 0}
    return SarvamOcrEngine(**{**defaults, **kw})


class TestRequestShape:
    def test_submits_multipart_digitise_with_expected_fields(self, monkeypatch, document):
        stub = _SarvamStub().install(monkeypatch)

        _engine(language="hi-IN").extract_text(document)

        req = stub.submits[0]
        assert req.url.path == "/doc-ai/v1/job/digitise"
        # Sarvam authenticates with its own header, not Bearer.
        assert req.headers["api-subscription-key"] == "sk-test"
        assert "multipart/form-data" in req.headers["content-type"]

        body = req.content.decode("utf-8", errors="replace")
        assert 'name="language"' in body and "hi-IN" in body
        # Document AI rejects "markdown"; the value must be "md".
        assert 'name="output_format"' in body and "md" in body
        assert 'name="model"' in body and "sarvam-vision-v1" in body
        assert "FAKE_SCAN_BYTES" in body, "the document itself must be uploaded"

    def test_printed_is_the_default_content_type(self, monkeypatch, document):
        stub = _SarvamStub().install(monkeypatch)

        _engine().extract_text(document)

        assert "printed" in stub.submits[0].content.decode("utf-8", errors="replace")

    def test_handwriting_flag_switches_content_type(self, monkeypatch, document):
        """A handwritten prescription needs the handwritten mode to read at all."""
        stub = _SarvamStub().install(monkeypatch)

        _engine(handwriting=True).extract_text(document)

        assert "handwritten" in stub.submits[0].content.decode("utf-8", errors="replace")

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("scan.pdf", "application/pdf"),
            ("scan.png", "image/png"),
            ("scan.jpg", "image/jpeg"),
            ("scan.jpeg", "image/jpeg"),
            ("scan.zip", "application/zip"),
            ("scan.tiff", "application/octet-stream"),
        ],
    )
    def test_media_type_follows_the_extension(self, tmp_path, name, expected):
        assert SarvamOcrEngine._media_type(tmp_path / name) == expected


class TestJobLifecycle:
    def test_polls_until_terminal_then_returns_text(self, monkeypatch, document):
        stub = _SarvamStub(statuses=["pending", "running", "completed"]).install(monkeypatch)

        text = _engine().extract_text(document)

        assert stub.poll_count == 3, "must keep polling while the job is not terminal"
        assert "HbA1c 8.9 %" in text

    def test_partially_completed_still_yields_output(self, monkeypatch, document):
        """Some pages failing is not a reason to discard the pages that worked."""
        _SarvamStub(statuses=["partially_completed"]).install(monkeypatch)

        assert "HbA1c" in _engine().extract_text(document)

    @pytest.mark.parametrize("bad", ["failed", "rejected"])
    def test_failed_and_rejected_raise(self, monkeypatch, document, bad):
        _SarvamStub(statuses=[bad]).install(monkeypatch)

        with pytest.raises(RuntimeError, match=bad):
            _engine().extract_text(document)

    def test_gives_up_rather_than_polling_forever(self, monkeypatch, document):
        """One stuck document must not hold a kiosk upload open indefinitely."""
        _SarvamStub(statuses=["running"] * 50).install(monkeypatch)

        with pytest.raises(RuntimeError, match="did not finish within"):
            _engine(timeout_seconds=0).extract_text(document)

    def test_missing_job_id_is_reported(self, monkeypatch, document):
        stub = _SarvamStub()
        stub.handler = lambda request: httpx.Response(201, json={"status": "pending"})
        stub.install(monkeypatch)

        with pytest.raises(RuntimeError, match="no job_id"):
            _engine().extract_text(document)

    def test_no_api_key_fails_before_any_request(self, monkeypatch, document):
        stub = _SarvamStub().install(monkeypatch)

        with pytest.raises(RuntimeError, match="SARVAM_API_KEY"):
            SarvamOcrEngine(api_key="").extract_text(document)

        assert stub.submits == [], "must not call the API without a key"


class TestErrorMessages:
    @pytest.mark.parametrize(
        ("code", "fragment"),
        [
            (400, "10-page limit"),
            (413, "200 MB"),
            (422, "corrupted"),
            (429, "10 requests/minute"),
            (402, "billing"),
        ],
    )
    def test_status_codes_explain_the_actual_problem(self, monkeypatch, document, code, fragment):
        """A bare "HTTP 413" sends someone reading docs; the limit is the answer."""
        _SarvamStub(submit_status=code).install(monkeypatch)

        with pytest.raises(RuntimeError, match=fragment):
            _engine().extract_text(document)


class TestTextCollection:
    def test_collects_nested_block_text_in_order(self):
        payload = {
            "documents": [
                {"pages": [{"blocks": [{"text": "Line one"}, {"text": "Line two"}]}]},
            ]
        }
        assert SarvamOcrEngine._collect_text(payload) == "Line one\nLine two"

    def test_ignores_annotation_and_usage_sidecars(self):
        """annotations mirror the content shape and would duplicate everything."""
        payload = {
            "documents": [{"blocks": [{"text": "Real content"}]}],
            "annotations": {"field": {"text": "Should not appear"}},
            "usage": {"text": "nor this"},
        }
        assert SarvamOcrEngine._collect_text(payload) == "Real content"

    def test_deduplicates_repeated_fragments(self):
        """A payload carrying both a page blob and its blocks would repeat itself."""
        payload = {
            "documents": [
                {"markdown": "Whole page", "blocks": [{"text": "Whole page"}]},
            ]
        }
        assert SarvamOcrEngine._collect_text(payload) == "Whole page"

    def test_empty_payload_yields_empty_string(self):
        assert SarvamOcrEngine._collect_text({"documents": []}) == ""

    def test_shape_change_still_finds_text(self):
        """Sarvam does not publish the full digitise nesting, so stay tolerant."""
        payload = {"result": {"unexpected": {"deeper": [{"content": "Found anyway"}]}}}
        assert SarvamOcrEngine._collect_text(payload) == "Found anyway"


class TestHtmlTableFlattening:
    """Sarvam returns tables as HTML even when output_format is "md".

    entity_extraction is line-oriented, so an un-flattened lab table yields zero
    investigation values while the document is still marked ocr_status=done.
    Silent loss of clinical data is worse than a visible OCR failure, so these
    tests pin the flattening rather than the HTML.
    """

    LAB_TABLE = (
        "Date: 12/08/2026\n"
        "<table>\n<thead>\n<tr>\n<th>TEST</th>\n<th>RESULT</th>\n</tr>\n</thead>\n"
        "<tbody>\n"
        "<tr>\n<td>HbA1c</td>\n<td>8.9 % 4.0 - 5.6</td>\n<td></td>\n</tr>\n"
        "<tr>\n<td>Fasting Glucose</td>\n<td>156 mg/dL 70 - 100</td>\n<td></td>\n</tr>\n"
        "</tbody>\n</table>"
    )

    def test_each_row_becomes_one_line(self):
        """The killer detail: source newlines sit *between* the <td> elements."""
        out = SarvamOcrEngine._flatten_html(self.LAB_TABLE)

        assert "HbA1c   8.9 % 4.0 - 5.6" in out
        assert "Fasting Glucose   156 mg/dL 70 - 100" in out

    def test_test_name_and_value_land_on_the_same_line(self):
        out = SarvamOcrEngine._flatten_html(self.LAB_TABLE)

        hba1c_line = next(ln for ln in out.splitlines() if "HbA1c" in ln)
        assert "8.9" in hba1c_line, "a split line yields no investigation value"

    def test_entity_extraction_recovers_the_values(self):
        """End to end: this is the regression that matters clinically."""
        from app.services.entity_extraction import extract_entities

        raw = extract_entities(self.LAB_TABLE, gender="male")
        flat = extract_entities(SarvamOcrEngine._flatten_html(self.LAB_TABLE), gender="male")

        def tests_found(result):
            return {
                e.value.get("test", "").strip()
                for e in result.entities
                if isinstance(e.value, dict)
            }

        assert "HbA1c" not in tests_found(raw), "precondition: raw HTML loses the value"
        assert {"HbA1c", "Fasting Glucose"} <= tests_found(flat)

    def test_abnormal_flag_survives_flattening(self):
        """HbA1c 8.9% is diabetic range; losing the flag loses the point."""
        from app.services.entity_extraction import extract_entities

        result = extract_entities(SarvamOcrEngine._flatten_html(self.LAB_TABLE), gender="male")
        hba1c = next(
            e
            for e in result.entities
            if isinstance(e.value, dict) and e.value.get("test") == "HbA1c"
        )
        assert hba1c.is_abnormal is True

    def test_html_entities_are_decoded(self):
        out = SarvamOcrEngine._flatten_html(
            "<table><tr><td>Cholesterol</td><td>&lt; 200</td></tr></table>"
        )
        assert "< 200" in out
        assert "&lt;" not in out

    def test_empty_cells_are_dropped_not_padded(self):
        out = SarvamOcrEngine._flatten_html("<table><tr><td>A</td><td></td><td>B</td></tr></table>")
        assert out == "A   B"

    def test_prose_outside_tables_keeps_its_line_breaks(self):
        """A global tag-strip would fold these into one line."""
        out = SarvamOcrEngine._flatten_html(
            "Line one\nLine two\n<table><tr><td>X</td></tr></table>"
        )

        assert "Line one" in out.splitlines()
        assert "Line two" in out.splitlines()

    def test_plain_text_is_returned_untouched(self):
        text = "Haemoglobin   11.2 g/dL   13.0 - 17.0"
        assert SarvamOcrEngine._flatten_html(text) == text

    def test_stray_non_table_tags_are_removed(self):
        out = SarvamOcrEngine._flatten_html("<h1>REPORT</h1>")
        assert out == "REPORT"

    def test_collect_text_applies_flattening(self):
        """The engine must return flattened text, not just offer the helper."""
        payload = {"documents": [{"blocks": [{"text": self.LAB_TABLE}]}]}

        out = SarvamOcrEngine._collect_text(payload)

        assert "<td>" not in out
        assert "HbA1c   8.9 % 4.0 - 5.6" in out


class TestEngineSelection:
    def _settings(self, monkeypatch, **overrides):
        """Point the factory at throwaway Settings.

        get_ocr_engine imports get_settings inside the function body, so patching
        it on the config module is what takes effect.
        """
        from app.core.config import Settings

        settings = Settings(**overrides)
        monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
        return settings

    def test_ocr_engine_sarvam_selects_sarvam(self, monkeypatch):
        self._settings(monkeypatch, ocr_engine="sarvam", sarvam_api_key="sk-test")
        assert isinstance(get_ocr_engine(), SarvamOcrEngine)

    def test_default_is_still_tesseract(self, monkeypatch):
        self._settings(monkeypatch, ocr_engine="tesseract", sarvam_api_key="sk-test")
        assert isinstance(get_ocr_engine(), TesseractOcrEngine)

    def test_handwriting_uses_sarvam_when_configured(self, monkeypatch):
        """Sarvam is the only engine here that can actually read handwriting."""
        self._settings(monkeypatch, ocr_engine="tesseract", sarvam_api_key="sk-test")

        engine = get_ocr_engine(handwriting=True)

        assert isinstance(engine, SarvamOcrEngine)
        assert engine._handwriting is True

    def test_handwriting_without_sarvam_stays_loud(self, monkeypatch):
        """Falling back to a printed-text engine would silently return garbage."""
        self._settings(monkeypatch, ocr_engine="tesseract", sarvam_api_key="")

        engine = get_ocr_engine(handwriting=True)

        assert isinstance(engine, HandwritingOcrEngine)
        with pytest.raises(NotImplementedError):
            engine.extract_text("whatever")

    def test_sarvam_engine_reports_handwriting_support(self):
        assert _engine().supports_handwriting() is True


class TestResultsRequest:
    def test_results_are_requested_as_json(self, monkeypatch, document):
        seen: list[str] = []

        stub = _SarvamStub()
        original_handler = stub.handler

        def spy(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return original_handler(request)

        stub.handler = spy
        stub.install(monkeypatch)

        _engine().extract_text(document)

        results_url = next(u for u in seen if "/results" in u)
        assert "format=json" in results_url
        assert _JOB_ID in results_url

    def test_status_and_results_target_the_returned_job_id(self, monkeypatch, document):
        seen: list[str] = []

        stub = _SarvamStub()
        original_handler = stub.handler

        def spy(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return original_handler(request)

        stub.handler = spy
        stub.install(monkeypatch)

        _engine().extract_text(document)

        assert f"/doc-ai/v1/job/{_JOB_ID}/status" in seen
        assert f"/doc-ai/v1/job/{_JOB_ID}/results" in seen


def test_schema_json_is_not_sent_for_digitise(monkeypatch, document):
    """digitise takes no schema; that is the extract endpoint's parameter."""
    stub = _SarvamStub().install(monkeypatch)

    _engine().extract_text(document)

    body = stub.submits[0].content.decode("utf-8", errors="replace")
    assert 'name="schema"' not in body
    assert json.dumps({}) not in body
