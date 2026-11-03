# Tasks — Phased Build Plan

Sequential phases, each building on the last. Check items off as you go. Phases 1–5 map
directly onto the five-step patient journey from the problem statement (Identify → Converse →
Scan → Summarize & Route → Consult); Phase 0 is groundwork and Phases 6–7 are hardening/demo prep.

Don't skip ahead — each phase assumes the previous one has a working (even if rough) version.

---

## Phase 0 — Project Setup & Foundations

- [x] Initialize monorepo structure: `backend/`, `frontend/`, `docs/`, `infra/`
- [x] Set up Python virtual env + FastAPI skeleton (`backend/`)
- [x] Set up React (Vite + TS) app skeleton (`frontend/`)
- [x] Docker Compose: Postgres with `pgvector` extension enabled, Redis if using Celery
- [x] Configure env vars / secrets handling (`.env.example` committed, real `.env` gitignored)
- [x] Linting/formatting: `ruff` + `black` (Python), `eslint` + `prettier` (React)
- [x] Git repo conventions: branch naming, PR template, basic CI (lint + test on push)
- [x] Finalize initial DB schema from `03-data-model.md`, write first Alembic migration

## Phase 1 — Identify (Auth, Registration & Consent)

- [x] UI: language selection screen
- [x] UI: ABHA/Aadhaar entry screen + "register as new patient" fallback
- [x] Backend: `POST /auth/register`, `POST /auth/abha/lookup` (mocked initially), `POST /auth/login`
- [x] i18n scaffolding wired up (English + Hindi minimum)
- [x] UI: consent form with per-language audio playback (TTS)
- [x] Backend: `POST /consent`, `DELETE /consent/{id}`, consent scope stored in DB
- [x] Enforce: no further screens accessible without a valid, current consent record
- [x] Basic audit logging wired in from this phase onward (every auth/consent action logged)

## Phase 2 — Converse (Interview Engine, Module A)

- [x] Define the clinical history ontology as a schema/config (CC, HPI/SOCRATES fields, PMH/PSH,
      drug/allergy, family, personal, ROS) + AYUSH Dashavidha Pariksha fields
- [x] Build the dialogue manager (deterministic state machine first) for 3–5 chief-complaint templates
- [x] Integrate ASR (start with Whisper or any working STT API) for voice input
- [x] Integrate TTS for audio question prompts
- [x] UI: dual-mode interview screen (voice capture + touch MCQ options side by side)
- [x] Backend: `/interview/sessions`, `/interview/sessions/{id}/next-question`,
      `/interview/sessions/{id}/answer`, `/interview/asr`, `/interview/sessions/{id}/complete`
- [x] Red-flag rules engine for the same 3–5 chief complaints; `/interview/sessions/{id}/red-flags`
- [x] AYUSH-mode toggle: extended interview branch for Ayurvedic OPDs
- [x] Persist both structured answers and raw transcripts

## Phase 3 — Scan (Document Digitization, Module B)

- [x] UI: document upload/capture screen (camera + file picker)
- [x] Backend: `POST /documents`, blob storage wiring (local disk or MinIO)
- [x] OCR pipeline: Tesseract for printed text (MVP); note handwriting OCR as future work
- [x] Entity extraction: rules/regex pass for common formats + LLM-fallback pass
- [x] Date extraction for chronological ordering
- [x] Reference-range table + abnormal-value flagging
- [x] Embeddings generated per document, stored in `pgvector`
- [x] Backend: `/documents/{id}`, `/documents/{id}/entities`, `/patients/{id}/documents/timeline`
- [x] UI: document timeline view (even a simple version) for sanity-checking output

## Phase 4 — Summarize & Route (Module C + Module D)

- [x] Design the fixed structured-summary schema (mirrors the standard clinical format)
- [x] Build the retrieval step: pull relevant interview answers + document entities per session
- [x] Build the LLM summarizer call, constrained to the fixed schema (prompt template + output validation)
- [x] Implement Main API vs. Local Offline routing logic in one place, with automatic failover
- [x] Wire the Security Layer in front of this call: consent-scope check, audit log
      (encryption at rest still outstanding — see Phase 6)
- [x] Backend: `/summaries/generate`, `/summaries/{id}`, `PATCH /summaries/{id}`, `/summaries/{id}/confirm`
- [ ] Bilingual output: patient audio confirmation + physician EN/HI summary
- [x] FHIR payload generation + mock HIS/ABDM push endpoint: `/summaries/{id}/push-abdm`
      (real FHIR R4 document Bundle; transport is a labelled local mock)
- [x] Session data purge job (clear temp audio/OCR scratch data after submission)

## Phase 5 — Consult (Physician Dashboard)

- [x] Physician login + role-based access
- [x] UI: patient queue, red-flag/priority patients visually distinguished
- [x] UI: structured summary view with edit/accept/reject controls
- [x] UI: document timeline view integrated into the same screen
- [x] Export/print summary as PDF
- [x] Backend: `/dashboard/queue`, `/dashboard/patients/{id}/summary`, `/dashboard/patients/{id}/report.pdf`

## Phase 6 — Security, Privacy & Compliance Hardening

- [x] Run through the DPDP Act 2023 checklist against actual implementation
      (consent-before-processing, purpose limitation via consent scopes, data
      minimisation on Aadhaar, retention/erasure via the purge job, auditability)
- [x] Confirm RBAC is enforced across all endpoints, not just the UI
      (patient and physician tokens are type-separated and not interchangeable)
- [ ] Confirm encryption at rest (DB) and in transit (TLS) end to end
      **NOT DONE.** No column encryption, and local Docker serves plain HTTP.
      This is the one Phase 6 claim the team must not make in the pitch.
- [x] Consent revocation actually halts further processing (test it)
- [x] Audit log covers a complete Identify→Consult trail for a sample patient
- [x] Token/session expiry configured and tested (`JWT_EXPIRE_MINUTES`)

## Phase 7 — Testing, Demo Prep & Deployment

- [x] Backend unit tests (`pytest`) for core services (interview branching, extraction, summarizer routing)
      (207 tests: interview, red flags, extraction, routing failover, consent enforcement,
      audit persistence, security layer, purge, FHIR shape, model types)
- [x] Frontend tests (`vitest`/`jest`) for key screens
      (17 tests: locale parity, visit store, auth store, API client)
- [x] Full end-to-end walkthrough: Identify → Converse → Scan → Summarize & Route → Consult, on seed data
      (`backend/scripts/e2e_journey.py` — runs against Docker, asserts every stage)
- [x] Seed data: 2–3 sample patients, sample documents, sample chief complaints (incl. one red flag)
      (`backend/scripts/seed_demo_data.py` — 3 patients: red-flagged, AYUSH, normal)
- [x] One-command local deployment (`docker compose up`) verified on a clean machine
      (tested: `docker compose up --build -d` + auto-migrate brings up all services healthy)
- [x] Demo script written, timed, and rehearsed
      (`docs/dev/demo-script.md` — 10-minute timed walkthrough with judges' Q&A answers)
- [ ] Pitch deck cross-referenced against `00-problem-statement.md` so every claimed capability
      is actually demoable
