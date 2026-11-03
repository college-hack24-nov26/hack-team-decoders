"""Tests for A5 — real PDF export, patient audio, and the summary schema fields.

The PDF is exercised both as a unit (does it produce a valid PDF, does it survive
the awkward inputs) and through the route (does the endpoint serve application/pdf
now, not the text/plain it used to). The renderer must never raise on a summary —
a physician clicking Download during a consult cannot be met with a 500.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.summary.pdf import render_summary_pdf
from app.services.summary.schemas import StructuredSummary


def _patient(**over):
    base = {"name": "SYNTHETIC Kamla", "age": 62, "gender": "female", "abha_id": "12-3456"}
    base.update(over)
    return SimpleNamespace(**base)


def _summary(**over):
    base = {"generated_by": "main_api", "status": "confirmed", "physician_edited": True}
    base.update(over)
    return SimpleNamespace(**base)


class TestSchemaFields:
    def test_new_fields_default_empty(self):
        s = StructuredSummary()
        assert s.patient_summary == ""
        assert s.physician_notes == ""
        assert s.sources == {}

    def test_existing_content_still_validates(self):
        """Older stored summaries have none of the new keys; they must still load."""
        s = StructuredSummary.model_validate({"chief_complaint": "fever"})
        assert s.chief_complaint == "fever"
        assert s.patient_summary == ""


class TestPdfRendering:
    def test_produces_a_valid_pdf(self):
        pdf = render_summary_pdf(
            patient=_patient(),
            summary=_summary(),
            content={"chief_complaint": "Chest pain", "hpi": {"narrative": "Two days of pain."}},
            physician_name="Dr Test",
        )
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 800

    def test_empty_summary_does_not_raise(self):
        """A deterministic summary with mostly blank fields must still render."""
        pdf = render_summary_pdf(
            patient=_patient(age=None, gender=None, abha_id=None),
            summary=_summary(generated_by="deterministic", physician_edited=False),
            content={},
            physician_name="Dr Test",
        )
        assert pdf[:5] == b"%PDF-"

    def test_markup_characters_do_not_break_rendering(self):
        """An unescaped & or < in a drug name would abort the paragraph."""
        pdf = render_summary_pdf(
            patient=_patient(name="A & B <test>"),
            summary=_summary(),
            content={
                "drug_history": [{"drug": "Vitamin A & D <forte>", "dose": "1", "frequency": "OD"}],
                "allergies": "none < known",
            },
            physician_name="Dr <b>Test</b>",
        )
        assert pdf[:5] == b"%PDF-"

    def test_hpi_falls_back_to_socrates_fields_without_a_narrative(self):
        """The deterministic path fills structured fields but no narrative — the
        HPI must not come out blank."""
        from app.services.summary.pdf import _hpi_narrative

        text = _hpi_narrative({"site": "central", "onset": "sudden", "severity": "9"})
        assert "central" in text and "sudden" in text

    def test_narrative_is_preferred_when_present(self):
        from app.services.summary.pdf import _hpi_narrative

        text = _hpi_narrative({"narrative": "A flowing story.", "site": "central"})
        assert text == "A flowing story."

    def test_long_content_does_not_overflow_the_frame(self):
        """The reported bug: long table values ran off the page edge.

        Table cells are Paragraphs now, so they wrap instead of overflowing. A
        200-char unbroken token, a long drug name and a long reference range must
        all render without reportlab raising a LayoutError for content too wide
        or too tall for the frame.
        """
        long_token = "Supercalifragilisticexpialidocious" * 6  # 200+ chars, no spaces
        pdf = render_summary_pdf(
            patient=_patient(name="Name " * 40, abha_id="9" * 60),
            summary=_summary(),
            content={
                "chief_complaint": "chest pain " * 50,
                "hpi": {"narrative": "The patient reports " * 60},
                "drug_history": [
                    {"drug": long_token, "dose": "500mg with water " * 5, "frequency": "BD"}
                ],
                "prior_investigations": [
                    {
                        "test": long_token,
                        "value": "8.9",
                        "unit": "mg/dL",
                        "reference_range": "4.0-5.6 (fasting, morning sample, venous) " * 3,
                        "is_abnormal": True,
                    }
                ],
                "allergies": long_token,
                "clinical_impression": long_token,
            },
            physician_name="Dr " + long_token,
        )
        assert pdf[:5] == b"%PDF-"

    def test_devanagari_uses_the_fallback_font_not_notdef_boxes(self):
        """The reported bug: Hindi/Marathi text rendered as black dots.

        Helvetica has no Devanagari glyphs, so those code points came out as the
        .notdef box. `_rich` must route Devanagari runs to the bundled Noto font
        (leaving Latin in the base font), and that font must actually embed.
        """
        from app.services.summary.pdf import _DEVA, _deva_available, _rich

        assert _deva_available, "bundled Devanagari font must be present"
        markup = _rich("Metformin सुबह-शाम")
        # Latin stays in the base font, Devanagari is switched to the Noto font.
        assert f'<font name="{_DEVA}">' in markup
        assert "Metformin" in markup and 'name="' not in markup.split("Metformin")[0]

        pdf = render_summary_pdf(
            patient=_patient(name="रमेश कुमार"),
            summary=_summary(),
            content={
                "drug_history": [
                    {"drug": "Metformin", "dose": "500mg", "frequency": "सुबह-शाम भोजन के बाद"}
                ],
                "red_flags_summary": "सीने में तेज़ दर्द (CRITICAL)",
            },
            physician_name="Dr Test",
        )
        assert pdf[:5] == b"%PDF-"
        # The Devanagari font is subset-embedded (TrueType FontFile2).
        assert b"Devanagari" in pdf
        assert b"FontFile2" in pdf

    def test_unsupported_symbols_are_never_left_to_render_as_boxes(self):
        """Arrows / warning signs map to ASCII or a placeholder, not a black box."""
        from app.services.summary.pdf import _rich

        assert _rich("1\u21920\u21921") == "1-&gt;0-&gt;1"  # arrows -> "->"
        assert _rich("\u26a0 danger") == "? danger"  # warning sign -> "?"
        # A char Helvetica already has (multiplication sign) is left untouched.
        assert _rich("2\u00d7 daily") == "2× daily"

    def test_abnormal_investigations_render(self):
        """Smoke: a red-flagged lab value path builds without error."""
        pdf = render_summary_pdf(
            patient=_patient(),
            summary=_summary(),
            content={
                "prior_investigations": [
                    {
                        "test": "HbA1c",
                        "value": "8.9",
                        "unit": "%",
                        "reference_range": "4.0-5.6",
                        "is_abnormal": True,
                    }
                ],
                "red_flags_summary": "Cardiac chest pain with breathlessness (critical)",
            },
            physician_name="Dr Test",
        )
        assert pdf[:5] == b"%PDF-"


class TestReportEndpoint:
    @pytest.fixture()
    def summary_id(self, sql_client, seeded_patient, physician_headers) -> str:
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def test_report_is_now_a_pdf(self, sql_client, seeded_patient, physician_headers, summary_id):
        res = sql_client.get(
            f"/api/v1/dashboard/patients/{seeded_patient['patient_id']}/report",
            headers=physician_headers,
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf"
        assert res.content[:5] == b"%PDF-"
        assert res.headers["content-disposition"].endswith('.pdf"')

    def test_report_needs_a_physician(self, sql_client, seeded_patient, patient_headers):
        res = sql_client.get(
            f"/api/v1/dashboard/patients/{seeded_patient['patient_id']}/report",
            headers=patient_headers,
        )
        assert res.status_code == 401


class TestPatientAudio:
    @pytest.fixture()
    def summary_id(self, sql_client, seeded_patient, physician_headers) -> str:
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def test_no_patient_summary_is_a_404(self, sql_client, patient_headers, summary_id):
        """The deterministic summary has no patient_summary, so there is nothing
        to speak — the client should fall back to showing text."""
        res = sql_client.get(
            f"/api/v1/summaries/{summary_id}/patient-audio", headers=patient_headers
        )
        assert res.status_code == 404

    def test_another_patient_cannot_fetch_it(self, sql_client, sql_db, summary_id):
        """Ownership is a 404, so a guessed id cannot even confirm the record exists."""
        from app.models.models import Patient
        from app.services.jwt import create_patient_token

        other = Patient(id=uuid.uuid4(), name="SYNTHETIC Other", preferred_language="en")
        sql_db.add(other)
        sql_db.commit()
        headers = {"Authorization": f"Bearer {create_patient_token(other.id)}"}

        res = sql_client.get(f"/api/v1/summaries/{summary_id}/patient-audio", headers=headers)
        assert res.status_code == 404

    def test_speaks_the_patient_summary_when_present(
        self, sql_client, sql_db, patient_headers, summary_id, monkeypatch, tmp_path
    ):
        from app.interview import tts
        from app.models.models import Summary

        # Give the summary a patient-facing line to speak.
        summary = sql_db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).one()
        content = dict(summary.structured_content)
        content["patient_summary"] = "आपल्याला बरे वाटेल. डॉक्टर तुम्हाला भेटतील."
        summary.structured_content = content
        sql_db.commit()

        clip = tmp_path / "clip.mp3"
        clip.write_bytes(b"ID3FAKEMP3")

        async def fake_synth(text, language):
            assert "बरे" in text  # the patient_summary, not the clinical body
            return "clip.mp3"

        monkeypatch.setattr(tts, "synthesize", fake_synth)
        monkeypatch.setattr(tts, "cached_path", lambda name: clip)

        res = sql_client.get(
            f"/api/v1/summaries/{summary_id}/patient-audio", headers=patient_headers
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "audio/mpeg"
        assert res.content == b"ID3FAKEMP3"

    def test_tts_outage_is_a_503(
        self, sql_client, sql_db, patient_headers, summary_id, monkeypatch
    ):
        from app.interview import tts
        from app.models.models import Summary

        summary = sql_db.query(Summary).filter(Summary.id == uuid.UUID(summary_id)).one()
        content = dict(summary.structured_content)
        content["patient_summary"] = "काही तरी."
        summary.structured_content = content
        sql_db.commit()

        async def no_audio(text, language):
            return None

        monkeypatch.setattr(tts, "synthesize", no_audio)

        res = sql_client.get(
            f"/api/v1/summaries/{summary_id}/patient-audio", headers=patient_headers
        )
        assert res.status_code == 503
