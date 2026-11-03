# Module D — Consent, Privacy & ABDM Integration

## Purpose
The compliance and security backbone: consent-first data capture, DPDP Act 2023 alignment, and
ABDM (ABHA / FHIR / HIS) integration so the structured summary actually reaches the hospital's
systems and the patient's health record.

## Responsibilities
1. **ABHA authentication** — patient identifies via ABHA ID (or Aadhaar/new registration as
   fallback for patients without one).
2. **Consent capture** — granular, revocable, explained via audio for low-literacy patients;
   recorded with scope (what data, shared with whom, for how long).
3. **Security layer** — sits in front of every AI call and every data write:
   - Enforces that consent scope actually covers the requested operation
   - Encrypts data in transit (TLS) and at rest (DB-level encryption)
   - Writes to the audit log
4. **FHIR/HIS push** — once a physician confirms a summary, format it as a FHIR resource and
   push to the hospital HIS + link to the ABHA Personal Health Record.
5. **Session data purge** — clear temporary session data (raw audio, intermediate OCR scratch
   files) immediately after submission; only the structured, consented data persists.

## MVP scope for the hackathon
- Real consent-capture UI/flow and real consent records in the DB — this is cheap to build
  properly and is a differentiator judges will look for given the PS explicitly calls it out.
- ABHA integration: use the **ABDM sandbox** if you can get access in time; otherwise build
  against a clearly-labeled mock `AuthProvider` and document the swap-in path for the real
  sandbox (don't fake a "real" ABHA lookup in the demo — say plainly it's mocked).
- FHIR push: generate a valid-shaped FHIR payload and hit a mock/local endpoint rather than a
  real HIS — again, label it clearly in the demo.
- Audit log table populated for every read/write of patient data, even in the mocked version.

## Acceptance criteria
- No AI call or data write happens without a corresponding valid consent record.
- Revoking consent actually blocks further processing for that patient/session.
- A FHIR-shaped payload is generated for at least one confirmed summary, viewable in the demo.
- Audit log shows a complete trail for a full patient journey (Identify → Consult).

## Reference
See `08-glossary.md` for ABDM/ABHA/FHIR/DPDP definitions if anyone on the team needs a primer.
