# Compliance Summary — what is real, what is mocked

Written for the judging pitch. Everything here is verifiable against the running
system; the "how to prove it" column is the command or test that demonstrates it.

Two scripts back these claims:

- `pytest` — 217 tests, runs on SQLite, no Docker needed
- `backend/scripts/verify_module_d.py` — drives the real Docker stack (Postgres,
  real HTTP push, real files on the storage volume)

---

## Real

| Claim | How to prove it |
|---|---|
| Consent is captured per-scope, in the patient's language, with an audio-confirmation flag | `POST /consent`; `tests/test_consent.py` |
| No interview, document upload, ASR or summarisation happens without a valid consent record | `tests/test_security.py`, `tests/test_security_layer.py` |
| Consent scope is enforced per operation, not just "some consent exists" | Declining `documents` blocks upload; declining `abdm_push` blocks the FHIR push |
| Revoking consent halts all further processing immediately | `DELETE /consent/{id}` then any endpoint → 403. `TestConsentRevocationBlocks` |
| Every read and write of patient data is audited, and the entry actually persists | `tests/test_audit_persistence.py` reads the trail back after a rollback |
| Audit trail covers a full Identify → Converse → Scan → Summarize → Consult journey | `test_full_journey_leaves_a_complete_committed_trail`, and step 6 of the verify script |
| Patient and physician sessions are separate and non-interchangeable | Token `type` claim is checked on decode; `TestRBAC` |
| Physician-only endpoints reject patient tokens and anonymous callers | `tests/test_summaries.py::test_anonymous_is_refused`, `TestRBAC` |
| Aadhaar is never stored raw, and never leaves the system | Salted SHA-256 + last 4 only; `test_register_never_stores_raw_aadhaar`, `test_aadhaar_is_never_emitted` |
| A valid FHIR R4 document Bundle is generated from a confirmed summary | `app/services/fhir.py`; `TestFhirBundleShape` asserts Bundle/Composition/Patient/Observation structure |
| Abnormal lab values carry a FHIR `interpretation` of Abnormal | `test_abnormal_lab_is_flagged_as_abnormal` |
| Raw scans and voice transcripts are deleted once the summary reaches the HIS; structured data survives | `tests/test_purge.py`, and step 4 of the verify script checks the file is gone from disk |
| Session expiry is enforced | `JWT_EXPIRE_MINUTES`, checked on every decode |

---

## Mocked or sandboxed — say so plainly

| Component | What is real | What is not | Why |
|---|---|---|---|
| **ABHA / Aadhaar identity** (`app/services/auth_provider.py`) | The `AuthProvider` interface, the patient records it creates, the audit entries | No ABDM gateway call, **no OTP challenge**, no UIDAI e-KYC. Any well-formed 14-digit ABHA number is accepted and issued a session | No ABDM sandbox credentials. Swap-in steps are documented in the module docstring; no caller changes needed |
| **FHIR transport** (`app/services/fhir.py`) | Bundle generation is real FHIR R4. The push is a real HTTP POST | The receiver is our own labelled mock (`/api/v1/abdm-mock/fhir`), not ABDM. No consent-artefact exchange, no Health Repository registration | Same reason. Set `ABDM_FHIR_ENDPOINT` to a real gateway to make it real |
| **Terminology coding** | Resource structure and reference wiring | SNOMED/LOINC codes are placeholders carrying display text, not looked-up concepts | Terminology mapping is a project in itself |
| **`POST /auth/login`** | Issues a correctly-typed, expiring JWT | Accepts a bare `patient_id` with no second factor | Demo convenience. Flagged in the route docstring; must not ship |
| **ASR** (`app/interview/asr.py`) | Real Whisper call when configured | Falls back to a `[Mock ASR]` transcript when `WHISPER_API_URL` is unset — the UI shows a warning when it does | Keeps the app runnable without a provider |

The login screen carries a visible **DEMO MODE** banner in English and Hindi
stating that identity verification is simulated, so nobody watching the demo can
mistake the mock for a real ABHA check.

---

## Known gaps — do not claim these

1. **No encryption at rest.** PII and clinical columns (`patients.name`,
   `patients.phone`, `interview_answers.raw_transcript`, `summaries.structured_content`)
   are stored in plaintext. Postgres-level or column-level encryption is not
   implemented.
2. **No TLS in the local deployment.** Docker serves plain HTTP on 3000/8000. A
   real deployment must terminate TLS and set `sslmode=require` on the database
   connection. Nothing in the code prevents this; it is simply not configured.
3. **Secrets are committed defaults.** `JWT_SECRET`, the Postgres password and
   the seeded physician password are demo values in `infra/docker-compose.yml`.
   Redis has no authentication.
4. **The purge is push-triggered, not scheduled.** Data for a patient who never
   reaches a confirmed, pushed summary is retained. `retention_days` is recorded
   on the consent record but nothing enforces it yet.
5. **Audit log is append-only by convention, not by permission.** The
   application never updates or deletes rows, but the DB user could.

---

## DPDP Act 2023 mapping

| Principle | Where it lives | Status |
|---|---|---|
| Consent before processing | `SecurityLayer.authorize()`, `require_consent_scope` | Enforced |
| Purpose limitation | Per-operation consent scopes | Enforced |
| Data minimisation | Aadhaar hashed; Aadhaar excluded from FHIR output | Enforced |
| Right to withdraw | `DELETE /consent/{id}`, blocks processing immediately | Enforced |
| Storage limitation | Purge job after push; `retention_days` recorded | Partial — not scheduled |
| Accountability / auditability | `audit_logs`, committed with the action it describes | Enforced |
| Security safeguards | RBAC and consent gating | Partial — no encryption at rest or TLS |
