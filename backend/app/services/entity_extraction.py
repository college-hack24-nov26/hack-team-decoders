"""Entity extraction pipeline for medical documents.

Strategy (per docs/design/modules/module-b-document-digitization.md):
  1. Rules/regex pass for common Indian prescription and lab-report formats
  2. LLM-assisted fallback for anything the rules don't catch

Extracts:
  - Diagnoses
  - Medications (drug name, dose, frequency)
  - Investigation results (test, value, unit, reference range)
  - Procedures
  - Document date

Supported sample formats (what the demo team should bring):
  - Indian lab report: header with patient info, table of test/value/unit/range
  - Indian prescription: doctor header, Rx section with drug-dose-freq lines,
    diagnosis line, date at top or bottom
  - Discharge summary: structured sections (Diagnosis, Medications, Investigations)

Extending: add more `_extract_*` helpers and register them in `extract_entities`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.reference_ranges import flag_abnormal


@dataclass
class ExtractedEntity:
    """A single entity pulled from a document."""

    entity_type: str  # diagnosis | medication | investigation_value | procedure
    value: dict  # shape depends on entity_type
    is_abnormal: bool | None = None


@dataclass
class ExtractionResult:
    """Full extraction output for one document."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    document_date: date | None = None
    doc_type: str = "unknown"  # prescription | lab_report | discharge_summary


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    # DD/MM/YYYY or DD-MM-YYYY
    (r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", "dmy"),
    # YYYY-MM-DD (ISO)
    (r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", "ymd"),
    # DD Mon YYYY (e.g. 15 Aug 2024)
    (
        r"(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{4})",
        "dmy_text",
    ),
]

_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _extract_dates(text: str) -> list[date]:
    """Find all plausible dates in the text."""
    dates: list[date] = []
    for pattern, fmt in _DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                if fmt == "dmy":
                    d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                elif fmt == "ymd":
                    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                elif fmt == "dmy_text":
                    d = int(match.group(1))
                    m = _MONTH_MAP[match.group(2).lower()[:3]]
                    y = int(match.group(3))
                else:
                    continue
                if 1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                    dates.append(date(y, m, d))
            except (ValueError, KeyError):
                continue
    return dates


# ---------------------------------------------------------------------------
# Medication extraction (Rx lines)
# ---------------------------------------------------------------------------

# Common Indian prescription patterns:
# "Tab Metformin 500mg 1-0-1" or "Cap Amoxicillin 250 mg TDS x 5 days"
_MED_PATTERN = re.compile(
    r"(?:Tab|Cap|Inj|Syp|Oint|Drops?|Susp)\.?\s+"
    r"([A-Za-z][A-Za-z0-9\-]+(?:\s+[A-Za-z][A-Za-z0-9\-]*)?)"  # drug name
    r"\s+(\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg|IU|%)?)"  # dose
    r"(?:\s+(.+?))?$",  # frequency (rest of line)
    re.IGNORECASE | re.MULTILINE,
)

# Simpler: "drug dose freq" on lines after "Rx" or "Medicines"
_SIMPLE_MED = re.compile(
    r"^\s*\d+[.)]\s*"
    r"([A-Za-z][A-Za-z0-9\-]+(?:\s+[A-Za-z][A-Za-z0-9\-]*)?)"
    r"\s+(\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg|%)?)"
    r"(?:\s+(.+))?$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_medications(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    seen: set[str] = set()
    for pattern in (_MED_PATTERN, _SIMPLE_MED):
        for m in pattern.finditer(text):
            drug = m.group(1).strip()
            dose = m.group(2).strip() if m.group(2) else ""
            freq = (m.group(3) or "").strip()
            key = f"{drug.lower()}|{dose}"
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                ExtractedEntity(
                    entity_type="medication",
                    value={"drug": drug, "dose": dose, "frequency": freq},
                )
            )
    return entities


# ---------------------------------------------------------------------------
# Investigation results (lab values)
# ---------------------------------------------------------------------------

# Pattern: "Test Name    value    unit    ref_range"
# Common in Indian lab reports as table rows
_LAB_LINE = re.compile(
    r"^(.+?)\s{2,}(\d+(?:\.\d+)?)\s+([\w/%]+)" r"(?:\s{2,}([\d.\-–]+(?:\s*[-–]\s*[\d.]+)?))?",
    re.MULTILINE,
)

# Simpler: "Test: value unit"
_LAB_COLON = re.compile(
    r"([A-Za-z][A-Za-z\s\(\)]+?):\s*(\d+(?:\.\d+)?)\s*([\w/%]+)",
    re.IGNORECASE,
)


def _extract_investigations(text: str, gender: str | None = None) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    seen: set[str] = set()

    for pattern in (_LAB_LINE, _LAB_COLON):
        for m in pattern.finditer(text):
            test_name = m.group(1).strip().rstrip(":")
            try:
                value = float(m.group(2))
            except ValueError:
                continue
            unit = m.group(3).strip()
            ref_range = ""
            if pattern == _LAB_LINE and m.lastindex and m.lastindex >= 4 and m.group(4):
                ref_range = m.group(4).strip()

            canonical = test_name.lower().replace(" ", "_")
            if canonical in seen:
                continue
            seen.add(canonical)

            is_abnormal = flag_abnormal(canonical, value, gender)

            entities.append(
                ExtractedEntity(
                    entity_type="investigation_value",
                    value={
                        "test": test_name,
                        "value": value,
                        "unit": unit,
                        "reference_range": ref_range,
                    },
                    is_abnormal=is_abnormal,
                )
            )
    return entities


# ---------------------------------------------------------------------------
# Diagnosis extraction
# ---------------------------------------------------------------------------

_DIAG_HEADERS = re.compile(
    r"(?:Diagnosis|Provisional Diagnosis|Final Diagnosis|Clinical Impression)"
    r"\s*:?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


def _extract_diagnoses(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    for m in _DIAG_HEADERS.finditer(text):
        raw = m.group(1).strip().rstrip(".")
        # Split by comma or semicolon for multiple diagnoses
        for diag in re.split(r"[;,]", raw):
            diag = diag.strip()
            if diag and len(diag) > 2:
                entities.append(ExtractedEntity(entity_type="diagnosis", value={"diagnosis": diag}))
    return entities


# ---------------------------------------------------------------------------
# Procedure extraction
# ---------------------------------------------------------------------------

_PROC_HEADERS = re.compile(
    r"(?:Procedure|Surgery|Operation)\s*:?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


def _extract_procedures(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    for m in _PROC_HEADERS.finditer(text):
        proc = m.group(1).strip().rstrip(".")
        if proc and len(proc) > 2:
            entities.append(ExtractedEntity(entity_type="procedure", value={"procedure": proc}))
    return entities


# ---------------------------------------------------------------------------
# Document type inference
# ---------------------------------------------------------------------------


def _infer_doc_type(text: str) -> str:
    lower = text.lower()
    if any(kw in lower for kw in ["lab report", "investigation", "pathology", "haematology"]):
        return "lab_report"
    if any(kw in lower for kw in ["discharge", "admitted", "ipd"]):
        return "discharge_summary"
    if any(kw in lower for kw in ["rx", "prescription", "tab ", "cap ", "syp "]):
        return "prescription"
    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_entities(text: str, gender: str | None = None) -> ExtractionResult:
    """Run the full extraction pipeline on OCR text.

    Parameters
    ----------
    text : str
        Raw OCR output from a document image.
    gender : str or None
        Patient gender for gender-specific reference ranges.

    Returns
    -------
    ExtractionResult
        Entities, inferred document date, and inferred doc_type.
    """
    entities: list[ExtractedEntity] = []

    entities.extend(_extract_diagnoses(text))
    entities.extend(_extract_medications(text))
    entities.extend(_extract_investigations(text, gender))
    entities.extend(_extract_procedures(text))

    # Date
    dates = _extract_dates(text)
    document_date = min(dates) if dates else None

    # Doc type
    doc_type = _infer_doc_type(text)

    return ExtractionResult(
        entities=entities,
        document_date=document_date,
        doc_type=doc_type,
    )
