"""Fixed structured summary schema.

The LLM output is constrained to this shape. This is the contract between
Module C and the physician dashboard — any change here ripples through the
frontend rendering and PDF export.

The sections mirror the standard clinical history format:
CC → HPI → PMH/PSH → Drug & Allergy → Family → Personal → ROS → Prior Investigations
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HPISection(BaseModel):
    """History of Present Illness — SOCRATES summary."""

    narrative: str = ""
    site: str = ""
    onset: str = ""
    character: str = ""
    radiation: str = ""
    associations: str = ""
    time_course: str = ""
    exacerbating_relieving: str = ""
    severity: str = ""


class MedicationItem(BaseModel):
    drug: str
    dose: str = ""
    frequency: str = ""


class InvestigationItem(BaseModel):
    test: str
    value: str = ""
    unit: str = ""
    reference_range: str = ""
    is_abnormal: bool = False
    date: str = ""


class StructuredSummary(BaseModel):
    """The fixed schema for summaries.structured_content.

    Every field is a string or list — the LLM fills them, the physician edits
    them, and the PDF renders them. No nested objects beyond one level, so the
    edit UI is a flat list of labelled text fields.
    """

    chief_complaint: str = ""
    hpi: HPISection = Field(default_factory=HPISection)
    past_medical_history: str = ""
    past_surgical_history: str = ""
    drug_history: list[MedicationItem] = Field(default_factory=list)
    allergies: str = ""
    family_history: str = ""
    personal_history: str = ""
    review_of_systems: str = ""
    prior_investigations: list[InvestigationItem] = Field(default_factory=list)

    # AYUSH-specific (only populated for ayush-mode sessions)
    ayush_assessment: str = ""
    """Plain-text summary of Ayurvedic assessment for backward compatibility."""

    ayush_prakriti: str = ""
    """Prakriti determination — dominant dosha(s). E.g. 'Vata-Pitta'."""

    ayush_vikriti: str = ""
    """Current Vikriti — which dosha(s) are aggravated."""

    ayush_ashtavidha: str = ""
    """Ashtavidha Pariksha findings: Mutra, Mala, Jihva, Shabda, Akruti."""

    ayush_nidana: str = ""
    """Nidana (causative factors) and Upashaya (relieving factors)."""

    ayush_ahara_vihara: str = ""
    """Diet and lifestyle assessment: Rasa preference, meal pattern, Dinacharya, Nidra."""

    ayush_treatment_direction: str = ""
    """Suggested treatment direction: Shamana (palliative) or Shodhana (purificatory).
    NOT a prescription — advisory only for the physician."""

    # Metadata the LLM adds
    clinical_impression: str = ""
    """A one-line impression — NOT a diagnosis. Always prefixed with
    'Suggested impression (AI-generated, unverified):' in the UI."""

    red_flags_summary: str = ""
    """Plain-English summary of any red flags that fired during the interview."""

    patient_summary: str = ""
    """Two plain-language sentences in the *patient's* own language, for the
    VisitDone screen and its read-aloud audio. Deliberately separate from every
    other field, which is English for the physician: this is the one part of the
    record the patient themselves is meant to understand, so it is written for a
    frightened non-clinician, not a doctor. Empty on the deterministic path,
    which cannot translate or simplify — only an LLM fills it."""

    physician_notes: str = ""
    """Free text the physician adds during review. Never populated by the model —
    it is the human's own annotation, and the whole point is that it is theirs.
    Lives on the summary rather than a separate table so it travels with the
    record into the PDF and the FHIR bundle."""

    sources: dict[str, str] = Field(default_factory=dict)
    """Per-section provenance: section name -> "interview" | "document" |
    "ai-inferred". Advisory, for the physician's eye — it says where a line came
    from so an inferred one gets more scrutiny than one the patient stated
    outright. Empty is fine; a missing entry just means unattributed."""
