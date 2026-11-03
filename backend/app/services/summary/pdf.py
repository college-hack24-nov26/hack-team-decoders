"""Render a confirmed clinical summary as an A4 PDF.

Replaces the plain-text dump the dashboard used to serve. A physician prints this
and puts it in a file, so it has to read as a clinical document, not a debug dump:
a proper header, the standard history sections in order, abnormal values called
out in red, red flags impossible to miss, and a signature line.

reportlab's Platypus is used rather than hand-placed text, so the document
reflows across pages on its own — a long HPI or a dozen investigations must not
run off the bottom of the page.

One rule runs through the whole layout: the clinical impression is AI-generated
and is labelled as such every place it appears. The physician signs the document;
the machine only drafts it.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Devanagari font — so Hindi / Marathi text renders as letters, not black dots
# ---------------------------------------------------------------------------
#
# reportlab's built-in fonts (Helvetica et al.) are WinAnsi-encoded: they have a
# glyph for Latin-1 and nothing else, and render every other code point as the
# .notdef box — the "black dots" a physician sees when an OCR'd Hindi
# prescription puts Devanagari in a drug/frequency cell, or the summariser writes
# a Hindi sentence. The base font stays Helvetica (English is the bulk of the
# document and Helvetica reads better for it); Devanagari runs are switched to
# Noto Sans Devanagari per-run in ``_rich`` below.
#
# NOTE: reportlab does not do complex-script shaping (no HarfBuzz), so Devanagari
# matra reordering and conjuncts are only approximate. Readable Hindi/Marathi
# beats black dots for the demo; true shaping would need a heavier dependency.
_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts")
_DEVA = "NotoDeva"
_deva_available = False


def _register_fonts() -> None:
    """Register the bundled Devanagari font once, tolerating a missing file.

    A missing font must not break PDF generation — it just means Devanagari
    falls back to the old behaviour — so this never raises into import.
    """
    global _deva_available
    regular = os.path.join(_FONT_DIR, "NotoSansDevanagari-Regular.ttf")
    if not os.path.exists(regular):
        logger.warning("pdf: Devanagari font not found at %s; Hindi text will not render", regular)
        return
    try:
        pdfmetrics.registerFont(TTFont(_DEVA, regular))
        _deva_available = True
    except Exception:  # noqa: BLE001 - font registration must not break the app
        logger.exception("pdf: failed to register Devanagari font")


_register_fonts()


def _is_devanagari(cp: int) -> bool:
    return (
        0x0900 <= cp <= 0x097F  # Devanagari
        or 0x1CD0 <= cp <= 0x1CFF  # Vedic Extensions
        or 0xA8E0 <= cp <= 0xA8FF  # Devanagari Extended
    )


def _helvetica_safe(ch: str) -> bool:
    """True if Helvetica (WinAnsi ~ cp1252) has a glyph for this character."""
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


# A few common symbols Helvetica lacks, mapped to ASCII so they read as intended
# rather than being dropped to a placeholder.
_SYMBOL_MAP = {
    "\u2192": "->",
    "\u2190": "<-",
    "\u2194": "<->",
    "\u21d2": "=>",
    "\u2265": ">=",
    "\u2264": "<=",
    "\u2260": "!=",
    "\u00d7": "x",  # multiplication sign, e.g. dosing "x2"
}

# Government-of-India palette, matching the frontend's saffron/green trim.
_PRIMARY = colors.HexColor("#0b5394")
_SAFFRON = colors.HexColor("#ff9933")
_GREEN = colors.HexColor("#138808")
_ABNORMAL = colors.HexColor("#c0392b")
_MUTED = colors.HexColor("#666666")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "MkTitle",
            parent=base["Title"],
            fontSize=16,
            textColor=_PRIMARY,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "MkSubtitle",
            parent=base["Normal"],
            fontSize=9,
            textColor=_MUTED,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            "MkSection",
            parent=base["Heading2"],
            fontSize=11,
            textColor=_PRIMARY,
            spaceBefore=10,
            spaceAfter=3,
        ),
        "body": ParagraphStyle("MkBody", parent=base["Normal"], fontSize=10, leading=14),
        "abnormal": ParagraphStyle(
            "MkAbnormal", parent=base["Normal"], fontSize=10, textColor=_ABNORMAL
        ),
        "disclaimer": ParagraphStyle(
            "MkDisclaimer",
            parent=base["Normal"],
            fontSize=9,
            textColor=_MUTED,
            leading=12,
        ),
        "footer": ParagraphStyle("MkFooter", parent=base["Normal"], fontSize=8, textColor=_MUTED),
        # Table-cell styles. Cells are Paragraphs, never bare strings: a bare
        # string in a reportlab Table does not wrap, so a long drug name or
        # reference range would run straight off the page edge. A Paragraph wraps
        # to the column width and splits over-long words, which is the whole fix
        # for the overflow.
        "cell": ParagraphStyle("MkCell", parent=base["Normal"], fontSize=9, leading=11),
        "cell_head": ParagraphStyle(
            "MkCellHead",
            parent=base["Normal"],
            fontSize=9,
            leading=11,
            textColor=_PRIMARY,
            fontName="Helvetica-Bold",
        ),
        "cell_red": ParagraphStyle(
            "MkCellRed", parent=base["Normal"], fontSize=9, leading=11, textColor=_ABNORMAL
        ),
        "cell_label": ParagraphStyle(
            "MkCellLabel", parent=base["Normal"], fontSize=9, leading=11, textColor=_MUTED
        ),
    }


def _esc(value: Any) -> str:
    """Escape text for a reportlab Paragraph, which parses a mini-HTML.

    An unescaped ``&`` or ``<`` in a drug name or a patient's own words would
    otherwise abort rendering of that paragraph.
    """
    from xml.sax.saxutils import escape

    return escape("" if value is None else str(value))


def _rich(value: Any) -> str:
    """Escape text AND make every character renderable, returning Paragraph markup.

    This is the fix for the "black dots" (``.notdef`` boxes). Each character is
    routed to a font that actually has a glyph for it:

    - Latin-1 / WinAnsi characters stay in the base font (Helvetica).
    - Devanagari runs are wrapped in ``<font name="NotoDeva">`` so Hindi/Marathi
      renders as letters.
    - Anything neither font can draw (arrows, ``⚠``, other scripts) is mapped to
      an ASCII equivalent where one is obvious, otherwise replaced with ``?`` —
      never left to render as a black box.

    Consecutive characters in the same font are grouped so the markup stays small.
    """
    text = "" if value is None else str(value)

    runs: list[tuple[str, str]] = []  # (font, chars) where font is "" for base
    for ch in text:
        if _helvetica_safe(ch):
            font = ""
        elif _is_devanagari(ord(ch)) and _deva_available:
            font = _DEVA
        else:
            mapped = _SYMBOL_MAP.get(ch)
            if mapped is not None:
                ch, font = mapped, ""
            else:
                ch, font = "?", ""
        if runs and runs[-1][0] == font:
            runs[-1] = (font, runs[-1][1] + ch)
        else:
            runs.append((font, ch))

    from xml.sax.saxutils import escape

    out = []
    for font, chars in runs:
        piece = escape(chars)
        out.append(f'<font name="{font}">{piece}</font>' if font else piece)
    return "".join(out)


def _hpi_narrative(hpi: dict[str, Any]) -> str:
    """Prefer the prose narrative; fall back to assembling the SOCRATES fields.

    The deterministic summariser fills the structured fields but not the
    narrative, so a rule-assembled summary still reads as a sentence rather than
    leaving the HPI blank.
    """
    narrative = (hpi.get("narrative") or "").strip()
    if narrative:
        return narrative

    order = [
        ("site", "Site"),
        ("onset", "Onset"),
        ("character", "Character"),
        ("radiation", "Radiation"),
        ("associations", "Associations"),
        ("time_course", "Time course"),
        ("exacerbating_relieving", "Exacerbating/relieving"),
        ("severity", "Severity"),
    ]
    parts = [f"{label}: {hpi[key]}" for key, label in order if hpi.get(key)]
    return "; ".join(parts)


def render_summary_pdf(
    *,
    patient: Any,
    summary: Any,
    content: dict[str, Any],
    physician_name: str,
) -> bytes:
    """Return the summary as PDF bytes.

    Args:
        patient: the Patient ORM row (name, age, gender, abha_id).
        summary: the Summary ORM row (generated_by, status, physician_edited...).
        content: summary.structured_content, the StructuredSummary dict.
        physician_name: who is signing, for the footer and signature block.
    """
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title="MediKiosk Clinical Summary",
    )

    flow: list[Any] = []

    # -- Header --------------------------------------------------------------
    flow.append(Paragraph("MediKiosk — Clinical Summary", st["title"]))
    flow.append(
        Paragraph(
            "All India Institute of Ayurveda · Ministry of Ayush, Government of India",
            st["subtitle"],
        )
    )
    flow.append(HRFlowable(width="100%", thickness=2, color=_SAFFRON, spaceAfter=1))
    flow.append(HRFlowable(width="100%", thickness=2, color=_GREEN, spaceAfter=8))

    # -- Patient block -------------------------------------------------------
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    age = _esc(patient.age) if patient.age is not None else "—"
    gender = _esc(patient.gender) if patient.gender else "—"
    abha = _esc(getattr(patient, "abha_id", None)) if getattr(patient, "abha_id", None) else "—"

    def _lab(text: str) -> Paragraph:
        return Paragraph(text, st["cell_label"])

    def _val(text: str) -> Paragraph:
        return Paragraph(text, st["cell"])

    demo = [
        [_lab("Patient"), _val(_rich(patient.name)), _lab("Date"), _val(now)],
        [_lab("Age / Gender"), _val(f"{age} / {gender}"), _lab("ABHA ID"), _val(abha)],
    ]
    demo_table = Table(demo, colWidths=[26 * mm, 62 * mm, 26 * mm, 60 * mm])
    demo_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    flow.append(demo_table)
    flow.append(Spacer(1, 4))

    # -- Red flags (boxed, first thing after the patient block) --------------
    red_flags = (content.get("red_flags_summary") or "").strip()
    if red_flags:
        rf = Table(
            [[Paragraph(f"<b>! RED FLAGS</b><br/>{_rich(red_flags)}", st["body"])]],
            colWidths=[172 * mm],
        )
        rf.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 1.5, _ABNORMAL),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdecea")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        flow.append(rf)
        flow.append(Spacer(1, 4))

    def section(title: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        flow.append(Paragraph(title, st["section"]))
        flow.append(Paragraph(_rich(text), st["body"]))

    # -- Narrative sections --------------------------------------------------
    section("Chief Complaint", content.get("chief_complaint", ""))
    section("History of Present Illness", _hpi_narrative(content.get("hpi") or {}))
    section("Past Medical History", content.get("past_medical_history", ""))
    section("Past Surgical History", content.get("past_surgical_history", ""))

    # -- Drug history (table) ------------------------------------------------
    drugs = [
        m for m in (content.get("drug_history") or []) if isinstance(m, dict) and m.get("drug")
    ]
    if drugs:
        flow.append(Paragraph("Drug History", st["section"]))
        head = [Paragraph(h, st["cell_head"]) for h in ("Drug", "Dose", "Frequency")]
        rows = [head]
        rows += [
            [
                Paragraph(_rich(m.get("drug")), st["cell"]),
                Paragraph(_rich(m.get("dose")), st["cell"]),
                Paragraph(_rich(m.get("frequency")), st["cell"]),
            ]
            for m in drugs
        ]
        t = Table(rows, colWidths=[80 * mm, 46 * mm, 46 * mm], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f8")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, _MUTED),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f7f9fb")],
                    ),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        flow.append(t)

    section("Allergies", content.get("allergies", ""))
    section("Family History", content.get("family_history", ""))
    section("Personal History", content.get("personal_history", ""))
    section("Review of Systems", content.get("review_of_systems", ""))

    # -- Investigations (table, abnormal rows in red) ------------------------
    invs = [
        i
        for i in (content.get("prior_investigations") or [])
        if isinstance(i, dict) and i.get("test")
    ]
    if invs:
        flow.append(Paragraph("Prior Investigations", st["section"]))
        head = [
            Paragraph(h, st["cell_head"]) for h in ("Test", "Value", "Unit", "Reference", "Date")
        ]
        rows = [head]
        style_cmds = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f8")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, _MUTED),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]
        for i in invs:
            abnormal = bool(i.get("is_abnormal"))
            # Colour lives on the Paragraph style, not a TableStyle TEXTCOLOR
            # command — TableStyle text colour is ignored for Paragraph cells.
            cs = st["cell_red"] if abnormal else st["cell"]
            label = _rich(i.get("test")) + (" (abnormal)" if abnormal else "")
            rows.append(
                [
                    Paragraph(label, cs),
                    Paragraph(_rich(i.get("value")), cs),
                    Paragraph(_rich(i.get("unit")), cs),
                    Paragraph(_rich(i.get("reference_range")), cs),
                    Paragraph(_rich(i.get("date")), cs),
                ]
            )
        t = Table(rows, colWidths=[54 * mm, 26 * mm, 24 * mm, 44 * mm, 24 * mm], repeatRows=1)
        t.setStyle(TableStyle(style_cmds))
        flow.append(t)

    section("AYUSH Assessment", content.get("ayush_assessment", ""))

    # -- Clinical impression (disclaimed) ------------------------------------
    impression = (content.get("clinical_impression") or "").strip()
    if impression:
        flow.append(Paragraph("Clinical Impression", st["section"]))
        flow.append(
            Paragraph(
                "<i>AI-suggested, requires physician verification before use.</i>",
                st["disclaimer"],
            )
        )
        flow.append(Paragraph(_rich(impression), st["body"]))

    # -- Physician notes -----------------------------------------------------
    section("Physician Notes", content.get("physician_notes", ""))

    # -- Signature + footer --------------------------------------------------
    flow.append(Spacer(1, 16))
    flow.append(HRFlowable(width="60%", thickness=0.5, color=_MUTED, spaceAfter=3))
    flow.append(Paragraph(f"Physician: {_rich(physician_name)}", st["body"]))
    flow.append(Paragraph("Signature: ______________________________", st["body"]))

    generated_by = _esc(summary.generated_by)
    edited = "edited by physician" if summary.physician_edited else "not yet edited"
    flow.append(Spacer(1, 10))
    flow.append(
        Paragraph(
            f"Generated by MediKiosk ({generated_by}, {edited}). "
            "This is a clinical decision-support draft, not a substitute for physician judgement.",
            st["footer"],
        )
    )

    doc.build(flow)
    return buf.getvalue()
