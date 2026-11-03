"""FHIR R4 resource generation for ABDM / HIS push — Module D.

Turns a confirmed `summaries.structured_content` document into a FHIR R4 Bundle
of type `document`, which is the shape ABDM's Health Information Provider flow
expects for a clinical record.

What is real here
-----------------
The Bundle structure, resource types, references and coding systems are real
FHIR R4 and validate against the spec's shape: a Composition acts as the
document header and indexes sections, with Patient, Condition, MedicationStatement
and Observation resources as supporting entries. This is what deliverable 6 asks
for — "properly-shaped FHIR resource generation matching the
summaries.structured_content schema".

What is NOT real
----------------
Where the Bundle is *sent*. With `ABDM_FHIR_ENDPOINT` unset the Bundle is
generated and returned but posted nowhere; the caller reports
`pushed=False, transport="none"`. Set it to a local mock endpoint to exercise
the transport. Neither path is a real ABDM gateway: that additionally requires
consent-artefact exchange and a Health Repository registration we do not have.
Codes are placeholders rather than looked-up SNOMED/ICD-10 concepts — a real
deployment must map terminology before submission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.models import Patient, Summary

FHIR_VERSION = "4.0.1"

# Placeholder coding systems. A production build maps to real terminology.
_SYS_SNOMED = "http://snomed.info/sct"
_SYS_LOINC = "http://loinc.org"
_SYS_ABHA = "https://healthid.abdm.gov.in"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _urn() -> str:
    """A Bundle-local reference. FHIR requires fullUrl for contained entries."""
    return f"urn:uuid:{uuid.uuid4()}"


def _patient_resource(patient: Patient, ref: str) -> dict[str, Any]:
    identifiers: list[dict[str, Any]] = []
    if patient.abha_id:
        identifiers.append(
            {
                "system": _SYS_ABHA,
                "value": patient.abha_id,
                "type": {"text": "ABHA Number"},
            }
        )

    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": ref.removeprefix("urn:uuid:"),
        "name": [{"text": patient.name}],
    }
    if identifiers:
        resource["identifier"] = identifiers
    if patient.gender in ("male", "female", "other"):
        resource["gender"] = patient.gender
    # Aadhaar is never emitted, in raw or hashed form. It is not clinical data
    # and ABDM does not need it once an ABHA number is present.
    return resource


def _condition_resources(content: dict[str, Any], patient_ref: str) -> list[dict[str, Any]]:
    """Chief complaint + clinical impression become Condition resources."""
    out: list[dict[str, Any]] = []

    chief = (content.get("chief_complaint") or "").strip()
    if chief:
        out.append(
            {
                "resourceType": "Condition",
                "id": str(uuid.uuid4()),
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "category": [
                    {
                        "coding": [
                            {
                                "system": (
                                    "http://terminology.hl7.org/CodeSystem/condition-category"
                                ),
                                "code": "problem-list-item",
                            }
                        ]
                    }
                ],
                "code": {"text": chief, "coding": [{"system": _SYS_SNOMED, "display": chief}]},
                "subject": {"reference": patient_ref},
            }
        )

    return out


def _medication_resources(content: dict[str, Any], patient_ref: str) -> list[dict[str, Any]]:
    """drug_history entries become MedicationStatement resources."""
    out: list[dict[str, Any]] = []

    for med in content.get("drug_history") or []:
        if not isinstance(med, dict):
            continue
        name = (med.get("drug") or "").strip()
        if not name:
            continue

        dosage: dict[str, Any] = {}
        text_parts = [p for p in (med.get("dose"), med.get("frequency")) if p]
        if text_parts:
            dosage["text"] = " ".join(str(p) for p in text_parts)

        entry: dict[str, Any] = {
            "resourceType": "MedicationStatement",
            "id": str(uuid.uuid4()),
            "status": "active",
            "medicationCodeableConcept": {"text": name},
            "subject": {"reference": patient_ref},
        }
        if dosage:
            entry["dosage"] = [dosage]
        out.append(entry)

    return out


def _observation_resources(content: dict[str, Any], patient_ref: str) -> list[dict[str, Any]]:
    """prior_investigations become Observation resources with interpretation."""
    out: list[dict[str, Any]] = []

    for inv in content.get("prior_investigations") or []:
        if not isinstance(inv, dict):
            continue
        test = (inv.get("test") or "").strip()
        if not test:
            continue

        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                        }
                    ]
                }
            ],
            "code": {"text": test, "coding": [{"system": _SYS_LOINC, "display": test}]},
            "subject": {"reference": patient_ref},
        }

        value = inv.get("value")
        unit = inv.get("unit")
        # Only emit valueQuantity for genuinely numeric results; a string value
        # in a Quantity would make the resource invalid.
        try:
            obs["valueQuantity"] = {"value": float(value), "unit": str(unit or "")}
        except (TypeError, ValueError):
            if value is not None:
                obs["valueString"] = str(value)

        ref_range = inv.get("reference_range")
        if ref_range:
            obs["referenceRange"] = [{"text": str(ref_range)}]

        if inv.get("is_abnormal"):
            obs["interpretation"] = [
                {
                    "coding": [
                        {
                            "system": (
                                "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
                            ),
                            "code": "A",
                            "display": "Abnormal",
                        }
                    ]
                }
            ]

        out.append(obs)

    return out


def _narrative_sections(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Free-text history sections become Composition sections with narrative."""
    fields = [
        ("hpi", "History of Present Illness"),
        ("past_medical_history", "Past Medical History"),
        ("past_surgical_history", "Past Surgical History"),
        ("allergies", "Allergies"),
        ("family_history", "Family History"),
        ("personal_history", "Personal History"),
        ("review_of_systems", "Review of Systems"),
        ("ayush_assessment", "AYUSH Assessment"),
        ("red_flags_summary", "Red Flags"),
    ]

    sections: list[dict[str, Any]] = []
    for key, title in fields:
        raw = content.get(key)
        if not raw:
            continue
        if isinstance(raw, dict):
            text = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in raw.items() if v)
        elif isinstance(raw, list):
            text = "; ".join(str(v) for v in raw if v)
        else:
            text = str(raw)
        if not text.strip():
            continue
        sections.append(
            {
                "title": title,
                "text": {
                    "status": "generated",
                    "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{text}</div>",
                },
            }
        )
    return sections


def build_fhir_bundle(summary: Summary, patient: Patient) -> dict[str, Any]:
    """Build a FHIR R4 document Bundle for a confirmed summary.

    The Composition is the first entry, as the `document` Bundle type requires.
    """
    content: dict[str, Any] = summary.structured_content or {}

    patient_ref = _urn()
    patient_res = _patient_resource(patient, patient_ref)

    conditions = _condition_resources(content, patient_ref)
    medications = _medication_resources(content, patient_ref)
    observations = _observation_resources(content, patient_ref)

    def _entry_refs(resources: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [{"reference": f"urn:uuid:{r['id']}"} for r in resources]

    sections: list[dict[str, Any]] = _narrative_sections(content)
    if conditions:
        sections.insert(
            0, {"title": "Chief Complaint / Diagnoses", "entry": _entry_refs(conditions)}
        )
    if medications:
        sections.append({"title": "Medications", "entry": _entry_refs(medications)})
    if observations:
        sections.append({"title": "Prior Investigations", "entry": _entry_refs(observations)})

    composition = {
        "resourceType": "Composition",
        "id": str(uuid.uuid4()),
        "status": "final",
        "type": {
            "coding": [{"system": _SYS_LOINC, "code": "11488-4", "display": "Consult note"}],
            "text": "Clinical summary generated at OPD kiosk",
        },
        "subject": {"reference": patient_ref},
        "date": (summary.confirmed_at or datetime.now(tz=UTC)).isoformat(),
        "title": "MediKiosk Structured History Summary",
        "section": sections,
    }

    entries: list[dict[str, Any]] = [
        {"fullUrl": f"urn:uuid:{composition['id']}", "resource": composition},
        {"fullUrl": patient_ref, "resource": patient_res},
    ]
    for res in (*conditions, *medications, *observations):
        entries.append({"fullUrl": f"urn:uuid:{res['id']}", "resource": res})

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "document",
        "timestamp": _now_iso(),
        "meta": {"versionId": "1", "lastUpdated": _now_iso(), "profile": []},
        "identifier": {"system": "urn:medikiosk:summary", "value": str(summary.id)},
        "entry": entries,
    }


async def push_bundle(bundle: dict[str, Any], endpoint: str) -> tuple[bool, str]:
    """POST a Bundle to a FHIR endpoint. Returns (ok, message).

    The endpoint is expected to be a local mock unless a real ABDM Health
    Repository has been configured. Network failures are returned, not raised:
    a failed push must not lose the confirmed summary.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                endpoint,
                json=bundle,
                headers={"Content-Type": "application/fhir+json"},
            )
        if 200 <= response.status_code < 300:
            return True, f"Accepted by {endpoint} ({response.status_code})"
        return False, f"Rejected by {endpoint} ({response.status_code})"
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a message
        return False, f"Push to {endpoint} failed: {exc}"
