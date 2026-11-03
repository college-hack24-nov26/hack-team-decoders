"""Reference-range table for common lab investigations.

Used by the abnormal-value flagging step in the document extraction pipeline.
Covers at minimum: CBC, glucose, lipid panel (per docs/design/modules/module-b-document-digitization.md).

Format:
    Each entry maps a canonical test name to its reference range(s) and unit.
    We store separate ranges for male/female where medically relevant.

Extending:
    Add entries to REFERENCE_RANGES below.  No code changes needed — the
    flag_abnormal() function matches extracted entities against this table.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReferenceRange:
    """A single reference range for a lab test."""

    test: str  # canonical name used for matching
    unit: str
    low: float | None  # None means no lower bound
    high: float | None  # None means no upper bound
    gender: str | None = None  # None means applies to all genders
    note: str = ""


# ---------------------------------------------------------------------------
# Reference range table — CBC, glucose, lipid panel, liver, kidney, thyroid
# ---------------------------------------------------------------------------

REFERENCE_RANGES: list[ReferenceRange] = [
    # ── CBC ────────────────────────────────────────────────────────────────
    ReferenceRange(test="hemoglobin", unit="g/dL", low=13.0, high=17.0, gender="male"),
    ReferenceRange(test="hemoglobin", unit="g/dL", low=12.0, high=15.5, gender="female"),
    ReferenceRange(test="rbc", unit="million/uL", low=4.5, high=5.5, gender="male"),
    ReferenceRange(test="rbc", unit="million/uL", low=4.0, high=5.0, gender="female"),
    ReferenceRange(test="wbc", unit="cells/uL", low=4000, high=11000),
    ReferenceRange(test="platelet", unit="lakh/uL", low=1.5, high=4.0),
    ReferenceRange(test="platelet_count", unit="cells/uL", low=150000, high=400000),
    ReferenceRange(test="hematocrit", unit="%", low=38.3, high=48.6, gender="male"),
    ReferenceRange(test="hematocrit", unit="%", low=35.5, high=44.9, gender="female"),
    ReferenceRange(test="mcv", unit="fL", low=80, high=100),
    ReferenceRange(test="mch", unit="pg", low=27, high=33),
    ReferenceRange(test="mchc", unit="g/dL", low=32, high=36),
    ReferenceRange(test="esr", unit="mm/hr", low=0, high=20, gender="male"),
    ReferenceRange(test="esr", unit="mm/hr", low=0, high=30, gender="female"),
    # ── Glucose ────────────────────────────────────────────────────────────
    ReferenceRange(test="fasting_glucose", unit="mg/dL", low=70, high=100),
    ReferenceRange(test="pp_glucose", unit="mg/dL", low=70, high=140, note="2hr post-prandial"),
    ReferenceRange(test="random_glucose", unit="mg/dL", low=70, high=140),
    ReferenceRange(test="hba1c", unit="%", low=4.0, high=5.6),
    # ── Lipid panel ────────────────────────────────────────────────────────
    ReferenceRange(test="total_cholesterol", unit="mg/dL", low=None, high=200),
    ReferenceRange(test="ldl", unit="mg/dL", low=None, high=100),
    ReferenceRange(test="hdl", unit="mg/dL", low=40, high=None, gender="male"),
    ReferenceRange(test="hdl", unit="mg/dL", low=50, high=None, gender="female"),
    ReferenceRange(test="triglycerides", unit="mg/dL", low=None, high=150),
    ReferenceRange(test="vldl", unit="mg/dL", low=None, high=30),
    # ── Liver ──────────────────────────────────────────────────────────────
    ReferenceRange(test="sgot", unit="U/L", low=0, high=40),
    ReferenceRange(test="sgpt", unit="U/L", low=0, high=40),
    ReferenceRange(test="alkaline_phosphatase", unit="U/L", low=44, high=147),
    ReferenceRange(test="bilirubin_total", unit="mg/dL", low=0.1, high=1.2),
    ReferenceRange(test="bilirubin_direct", unit="mg/dL", low=0, high=0.3),
    ReferenceRange(test="albumin", unit="g/dL", low=3.5, high=5.5),
    ReferenceRange(test="total_protein", unit="g/dL", low=6.0, high=8.3),
    # ── Kidney ─────────────────────────────────────────────────────────────
    ReferenceRange(test="creatinine", unit="mg/dL", low=0.7, high=1.3, gender="male"),
    ReferenceRange(test="creatinine", unit="mg/dL", low=0.6, high=1.1, gender="female"),
    ReferenceRange(test="urea", unit="mg/dL", low=15, high=40),
    ReferenceRange(test="bun", unit="mg/dL", low=7, high=20),
    ReferenceRange(test="uric_acid", unit="mg/dL", low=3.5, high=7.2, gender="male"),
    ReferenceRange(test="uric_acid", unit="mg/dL", low=2.6, high=6.0, gender="female"),
    # ── Thyroid ────────────────────────────────────────────────────────────
    ReferenceRange(test="tsh", unit="mIU/L", low=0.4, high=4.0),
    ReferenceRange(test="t3", unit="ng/dL", low=80, high=200),
    ReferenceRange(test="t4", unit="ug/dL", low=5.1, high=14.1),
    ReferenceRange(test="free_t4", unit="ng/dL", low=0.9, high=1.7),
]

# Index by canonical test name for fast lookup
_RANGES_BY_TEST: dict[str, list[ReferenceRange]] = {}
for _rr in REFERENCE_RANGES:
    _RANGES_BY_TEST.setdefault(_rr.test, []).append(_rr)


def flag_abnormal(
    test_name: str,
    value: float,
    gender: str | None = None,
) -> bool | None:
    """Return True if the value is outside the reference range, False if normal,
    None if we don't have a reference range for this test.

    Gender-specific ranges are preferred when gender is provided.
    """
    canonical = test_name.lower().strip().replace(" ", "_")
    candidates = _RANGES_BY_TEST.get(canonical)
    if not candidates:
        return None  # unknown test

    # Prefer gender-specific range
    matched: ReferenceRange | None = None
    for rr in candidates:
        if rr.gender is None:
            matched = rr  # fallback
        elif gender and rr.gender.lower() == gender.lower():
            matched = rr
            break

    if matched is None and candidates:
        matched = candidates[0]

    if matched is None:
        return None

    outside = (matched.low is not None and value < matched.low) or (
        matched.high is not None and value > matched.high
    )
    return outside
