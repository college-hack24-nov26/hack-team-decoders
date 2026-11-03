# API Spec (Draft)

REST endpoints grouped by module/patient-journey step. All routes prefixed `/api/v1`.
Auth: JWT bearer token issued at login, except where noted public.

## Auth / Onboarding (Step 1 — Identify)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register` | Public | New patient registration (no ABHA). Returns JWT. |
| POST | `/auth/abha/lookup` | Public | Look up / verify patient via ABHA ID (MOCKED — see `app/services/auth_provider.py`). Returns JWT if found. |
| POST | `/auth/login` | Public | Re-issue session token for existing patient. |
| GET | `/languages` | Public | List supported languages for the UI. |
| POST | `/consent` | Bearer JWT | Record consent (scope JSONB, language, audio_confirmed). |
| DELETE | `/consent/{id}` | Bearer JWT | Revoke consent. Sets `revoked_at` timestamp. |

## Interview (Step 2 — Converse)

| Method | Path | Purpose |
|---|---|---|
| POST | `/interview/sessions` | Start a new interview session (patient_id, mode) |
| GET | `/interview/sessions/{id}/next-question` | Get next adaptive question given answers so far |
| POST | `/interview/sessions/{id}/answer` | Submit an answer (voice transcript or touch selection) |
| POST | `/interview/asr` | Upload audio, get back transcript (proxy to ASR provider) |
| POST | `/interview/sessions/{id}/complete` | Mark session complete, trigger summarization pipeline |
| GET | `/interview/sessions/{id}/red-flags` | List any red flags triggered this session |

## Documents (Step 3 — Scan)

| Method | Path | Purpose |
|---|---|---|
| POST | `/documents` | Upload a document (multipart), returns `document_id` |
| GET | `/documents/{id}` | Get document metadata + extraction status |
| GET | `/documents/{id}/entities` | Get extracted entities for a document |
| GET | `/patients/{id}/documents/timeline` | Get chronologically ordered documents for a patient |

## Summary (Step 4 — Summarize & Route)

| Method | Path | Purpose |
|---|---|---|
| POST | `/summaries/generate` | Trigger summarizer for a session (interview + documents → structured summary) |
| GET | `/summaries/{id}` | Fetch a structured summary |
| PATCH | `/summaries/{id}` | Physician edits/amends the summary |
| POST | `/summaries/{id}/confirm` | Physician confirms/accepts the summary |
| POST | `/summaries/{id}/push-abdm` | Push confirmed summary to ABDM/HIS (FHIR payload) |

## Dashboard (Step 5 — Consult)

| Method | Path | Purpose |
|---|---|---|
| GET | `/dashboard/queue` | List patients ready for consult, red-flags first |
| GET | `/dashboard/patients/{id}/summary` | Full summary + document timeline for the physician view |
| GET | `/dashboard/patients/{id}/report.pdf` | Download/print the finalized summary |

## Cross-cutting

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness/readiness probe |
| GET | `/audit-logs` (admin only) | Query the audit trail |

## Notes

- Every endpoint touching patient data must pass through the Security/Consent middleware
  described in `05-modules/module-d-consent-privacy-abdm.md` before hitting the DB.
- `POST /summaries/generate` is where the Main API vs. Local Offline decision from
  `01-architecture.md` gets made — keep that branching logic in one place (a single service
  function), not scattered across the codebase.
