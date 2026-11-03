# Build Prompts — Wave-by-Wave

Copy-paste prompts for driving an AI coding agent (e.g. Claude Code, or a chat session with the
repo's `docs/` folder in context) through the build in sequenced waves, instead of asking for
the whole app at once.

## How to use these

- **Run one wave at a time, in a fresh session/context each time.** Each prompt tells the agent
  which docs to read first — that's how it gets context instead of you re-explaining the project.
- **Review before moving on.** After each wave, actually run the acceptance criteria the prompt
  asks the agent to verify, not just skim the diff. Don't start wave N+1 on a broken wave N.
- **Order:** Wave 0 → Wave 1 are strictly sequential (everything depends on them). After that,
  Module A and Module B (waves 2–3) don't depend on each other and can run in parallel if you
  have two people — both feed into Module C (wave 4). Module D (wave 5) touches code from every
  earlier wave, so do it last, before the final testing wave.
- **If the agent doesn't have direct filesystem/repo access**, paste the referenced docs' content
  into the same session before giving it the prompt, since "read docs/X" only works if it can
  actually open the file.
- Each prompt ends by asking the agent to check off `docs/dev/tasks-phased.md` items and flag deviations
  — read that output, it's your changelog.

---

## Wave 0 — Phase 0: Setup & Foundations

```
You are setting up the MediKiosk project from scratch (SIH 2026, Problem Statement 26047 —
an AI-powered patient case-taking software platform for AYUSH/allopathic OPDs, for the
Ministry of Ayush / All India Institute of Ayurveda).

Read these docs first, in order, before writing any code:
- docs/README.md
- docs/project/00-problem-statement.md
- docs/project/01-architecture.md
- docs/project/02-tech-stack.md
- docs/design/03-data-model.md
- docs/guides/setup.md

Your job is Phase 0 only — project scaffolding and foundations. Do NOT build any feature logic
yet (no interview engine, no OCR, no summarizer). This wave produces a clean project skeleton
that later waves will build features into.

Deliverables:
1. Monorepo structure: backend/ (FastAPI), frontend/ (React+Vite+TS), infra/, matching
   docs/guides/setup.md.
2. Backend: FastAPI app skeleton with a working `/health` endpoint, SQLAlchemy 2.x + Alembic
   configured against Postgres, Pydantic settings loaded from .env, ruff + black configured.
3. Frontend: Vite+React+TS skeleton, Tailwind configured, react-i18next scaffolded with
   English + Hindi locale files, a basic app shell with a placeholder home screen, eslint +
   prettier configured.
4. infra/docker-compose.yml: Postgres 15+ with the pgvector extension enabled on startup, plus
   Redis if you judge it useful for a later phase — otherwise skip it and note that as deferred.
5. Initial Alembic migration implementing the schema in docs/design/03-data-model.md as closely as
   practical. It's fine to defer tables that only matter for later phases (e.g. embeddings) —
   note which ones you deferred and why in a comment at the top of the migration.
6. .env.example files for backend and frontend listing the variables from docs/guides/setup.md
   (leave real values blank).
7. Root README pointing to docs/ and explaining how to run docker compose, backend, and frontend.
8. Basic GitHub Actions CI: lint + test on push for both backend and frontend (a single trivial
   passing test each is fine for now).

Constraints:
- Follow docs/project/02-tech-stack.md exactly — don't substitute frameworks or add new ones without
  flagging it.
- Verify yourself that everything runs via `docker compose up` plus the commands in
  docs/guides/setup.md before finishing — don't just assume it works.
- Keep the app shell intentionally minimal. The point of this wave is a clean, working
  foundation, not features.

When done:
- Update docs/dev/tasks-phased.md, checking off every completed Phase 0 item.
- Summarize what you built and flag any deviations from the docs, and why.
```

---

## Wave 1 — Phase 1: Identify (Auth, Registration & Consent)

```
You're building Phase 1 ("Identify") of MediKiosk on top of the Phase 0 scaffold already in
this repo.

Read first:
- docs/project/00-problem-statement.md (Step 1 — Identify)
- docs/project/01-architecture.md
- docs/design/03-data-model.md (patients, consent_records tables)
- docs/design/04-api-spec.md (Auth / Onboarding section)
- docs/design/modules/module-d-consent-privacy-abdm.md (consent capture requirements)
- docs/dev/tasks-phased.md (Phase 1 checklist)

Scope: build the full "Identify" step end to end — language selection, ABHA/Aadhaar login or
new-patient registration, and audio-guided consent capture. Do NOT build the interview engine,
document upload, or summarizer yet — this wave stops once a patient can log in/register and
give consent, landing on a placeholder "interview starts here" screen.

Backend deliverables:
1. `patients` and `consent_records` tables/models (extend the Phase 0 migration or add a new one).
2. `POST /auth/register`, `POST /auth/abha/lookup`, `POST /auth/login` — implement ABHA lookup
   behind an `AuthProvider` interface with a clearly-labeled MOCK implementation (return
   believable fake data), structured so a real ABDM sandbox client can be swapped in later
   without touching any callers.
3. `GET /languages`.
4. `POST /consent`, `DELETE /consent/{id}` — consent must store scope (jsonb), language,
   audio_confirmed boolean, timestamps.
5. JWT session issuance on login/registration.
6. Audit log entries for every register/login/consent action (simple audit_logs table + a
   small logging helper other modules can reuse later).
7. A dependency/middleware that later endpoints can use to require "valid current consent" —
   build it now even though nothing else calls it yet.

Frontend deliverables:
1. Language selection screen (large touch targets, per docs/project/02-tech-stack.md accessibility notes).
2. Login/registration screen: ABHA ID entry, Aadhaar fallback, "register as new patient" form
   (name/age/gender/phone).
3. Consent screen: readable text plus an audio playback control per section, explicit accept
   per scope, usable by a patient who cannot read.
4. Wire these three screens together into a working flow ending on a placeholder "Interview
   starts here" screen.
5. Use react-i18next for all copy; populate real English + Hindi strings, not just keys.

Constraints:
- Be explicit in code comments and in your summary about what's mocked (ABHA lookup) vs. real.
- No screen past the consent step should be reachable without a valid consent record — verify
  this yourself.
- Match docs/design/04-api-spec.md's contracts; if you deviate, update that doc to match and say so.

When done:
- Check off completed Phase 1 items in docs/dev/tasks-phased.md.
- Update docs/design/04-api-spec.md and docs/design/03-data-model.md if the real implementation drifted.
- Summarize what's mocked, what's real, and what Module A (next wave) can assume exists.
```

---

## Wave 2 — Module A: Conversational History Engine (Converse)

```
You're building Module A ("Converse") of MediKiosk — the conversational multimodal history
engine — on top of the Phase 0+1 foundation already in this repo (patient auth + consent work).

Read first:
- docs/project/00-problem-statement.md (Step 2 — Converse; Module A section)
- docs/design/modules/module-a-interview-engine.md — this is your primary spec, follow its MVP
  scope and acceptance criteria exactly
- docs/project/01-architecture.md
- docs/design/03-data-model.md (interview_sessions, interview_answers, red_flags)
- docs/design/04-api-spec.md (Interview section)
- docs/dev/tasks-phased.md (Phase 2 checklist)

Scope: build the full interview flow for 3–5 chief-complaint templates (pick: chest pain,
fever, abdominal pain, headache, breathlessness) plus a generic fallback, in English and Hindi,
with both voice and touch input, and red-flag detection. Do NOT build document upload or the
summarizer — this wave ends with a completed, structured interview session persisted to the
DB, reachable only for a patient with valid consent (reuse the Phase 1 middleware).

Backend deliverables:
1. `interview_sessions`, `interview_answers`, `red_flags` tables/models.
2. A clinical history ontology defined as a config/schema file (not scattered hardcoded
   strings), covering CC, HPI/SOCRATES fields, PMH/PSH, drug/allergy, family, personal, ROS,
   plus an AYUSH Dashavidha Pariksha field set behind a `mode=ayush` flag.
3. Dialogue manager: deterministic state machine per chief-complaint template driving
   SOCRATES-style branching. Structure it so adding a 6th template later is a config change,
   not a code rewrite.
4. Red-flag rules engine: explicit rule definitions (not LLM-dependent) for at least chest
   pain + dyspnoea and one stroke-symptom combination. A red flag firing must be independent of
   interview completion and immediately queryable.
5. ASR integration: `POST /interview/asr` — pick a concretely working provider/library from
   docs/project/02-tech-stack.md's MVP column (e.g. Whisper) and actually wire it, not a stub.
6. TTS integration for question audio prompts, same standard.
7. `POST /interview/sessions`, `GET /interview/sessions/{id}/next-question`,
   `POST /interview/sessions/{id}/answer`, `POST /interview/sessions/{id}/complete`,
   `GET /interview/sessions/{id}/red-flags`.
8. Require valid consent (Phase 1 middleware) on every one of these endpoints.

Frontend deliverables:
1. Interview screen: shows the current question with both a "tap an option" UI and a
   "hold to speak" voice control, auto-plays the TTS prompt audio.
2. Visible, obvious red-flag alert UI if triggered mid-interview.
3. Progress indicator so the patient knows roughly how far through they are.
4. AYUSH mode toggle path — a flag passed at session start is fine (the OPD/kiosk selects mode).

Acceptance criteria — verify these yourself before finishing, per
docs/design/modules/module-a-interview-engine.md:
- A full interview for a supported chief complaint completes via voice only, touch only, and
  mixed input, in a reasonable time.
- The red-flag combination triggers a visible alert within the same session.
- All answers are retrievable in structured form, not just as a raw transcript blob.

When done:
- Check off completed Phase 2 items in docs/dev/tasks-phased.md.
- Note any provider API keys/config the user needs to supply to run ASR/TTS locally.
- Summarize what's built and what Module C (next-next wave) can assume it can query.
```

---

## Wave 3 — Module B: Document Digitization (Scan)

```
You're building Module B ("Scan") of MediKiosk — document digitization — on top of the
existing foundation (auth/consent from Phase 1). Module A does not need to be finished first;
these can run in parallel, but assume both exist somewhere in this repo.

Read first:
- docs/project/00-problem-statement.md (Step 3 — Scan; Module B section)
- docs/design/modules/module-b-document-digitization.md — primary spec, follow its MVP scope and
  acceptance criteria
- docs/design/03-data-model.md (documents, document_entities, embeddings)
- docs/design/04-api-spec.md (Documents section)
- docs/dev/tasks-phased.md (Phase 3 checklist)

Scope: build the full upload → OCR → entity extraction → chronological timeline →
abnormal-value flagging pipeline for printed-text documents. Handwriting OCR is explicitly out
of scope for this wave — stub the interface so it can be swapped in later, and say so clearly
rather than attempting it.

Backend deliverables:
1. `documents`, `document_entities` tables/models; blob storage wiring (local disk is fine for
   the demo — implement it behind a storage interface so swapping to S3/MinIO later is a
   config change, not a rewrite).
2. OCR pipeline using Tesseract (or the equivalent MVP choice from docs/project/02-tech-stack.md) for
   printed text.
3. Entity extraction: a rules/regex pass for at least 2 realistic Indian prescription/lab-report
   layouts, with an LLM-assisted fallback pass for anything the rules don't match. Extract
   diagnoses, medications (dose/frequency), investigation results (test/value/unit/reference
   range), procedures.
4. Date extraction/inference per document for chronological ordering.
5. A reference-range table (CBC, glucose, lipid panel at minimum) and abnormal-value flagging.
6. Embedding generation for document text, stored via pgvector, keyed to the patient — build
   this so Module C's retrieval step can query it directly.
7. `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/entities`,
   `GET /patients/{id}/documents/timeline`, all behind the consent-required middleware.

Frontend deliverables:
1. Upload screen: camera capture + file picker, multi-document upload in one session.
2. A simple document timeline view showing extracted entities per document and any
   abnormal-value flags, so extraction quality can be sanity-checked visually.

Acceptance criteria, per docs/design/modules/module-b-document-digitization.md:
- Uploading 2–3 clean sample documents (create or find realistic sample prescription and lab
  report images/text to test with) produces a visible ordered timeline with correctly
  extracted diagnosis and medication entities.
- At least one abnormal value in a sample lab report is flagged.

When done:
- Check off completed Phase 3 items in docs/dev/tasks-phased.md.
- Document exactly which sample document formats your extractor handles, so Module C and the
  demo team know what to bring on the day.
- Summarize what Module C (next wave) can assume/query from this module.
```

---

## Wave 4 — Module C: Summary Generator + Dashboard (Summarize & Route, Consult)

```
You're building Module C ("Summarize & Route") of MediKiosk, plus the physician dashboard
(Step 5, "Consult") that consumes its output, on top of the interview engine (Module A) and
document pipeline (Module B), both assumed complete in this repo.

Read first:
- docs/project/00-problem-statement.md (Steps 4–5; Module C section)
- docs/design/modules/module-c-summary-generator.md — primary spec
- docs/project/01-architecture.md (Main API vs. Local Offline routing)
- docs/design/03-data-model.md (summaries table)
- docs/design/04-api-spec.md (Summary + Dashboard sections)
- docs/dev/tasks-phased.md (Phase 4–5 checklists)

Scope: build the AI summarizer that merges a completed interview session with the patient's
document entities into a fixed-schema structured summary, plus the physician dashboard to
view/edit/confirm it. Full ABDM/FHIR push and hardened security enforcement is Module D's job
(next wave) — for this wave, a mock/stub push endpoint that produces a plausible FHIR-shaped
payload is enough. Don't build the real ABDM integration here.

Backend deliverables:
1. `summaries` table/model with the fixed structured_content schema (Chief complaint → HPI →
   PMH/PSH → drug/allergy → family → personal → ROS → prior investigations).
2. Retrieval step: given a session_id, pull the relevant interview_answers and
   document_entities/embeddings for that patient (use the pgvector querying set up in Module B).
3. LLM summarizer call: constrain output to the fixed schema via prompt template + response
   validation — don't let the model freeform the structure. Use the "Main API" path from
   docs/project/02-tech-stack.md.
4. Implement the Main-API-vs-Local-Offline routing described in docs/project/01-architecture.md as a
   single, clearly isolated service function/module — even if the local path is a
   smaller/cheaper model or a clearly-labeled stub for now, the branching logic itself must be
   real and tested (e.g. via a config flag or a simulated API failure).
5. `POST /summaries/generate`, `GET /summaries/{id}`, `PATCH /summaries/{id}`,
   `POST /summaries/{id}/confirm`.
6. Bilingual output: physician-facing EN/Hindi summary; patient-facing audio confirmation
   using the TTS integration from Module A.
7. `GET /dashboard/queue`, `GET /dashboard/patients/{id}/summary`,
   `GET /dashboard/patients/{id}/report.pdf`.

Frontend deliverables:
1. Physician login — basic role-based auth is fine here; full RBAC hardening is Module D's job.
2. Patient queue screen with red-flag/priority patients visually distinguished (pull from
   Module A's red_flags data).
3. Summary view: clearly sectioned per the fixed schema, editable fields, Accept/Amend/Reject
   controls, and the document timeline from Module B visible alongside it.
4. PDF export/print of the confirmed summary.

Acceptance criteria, per docs/design/modules/module-c-summary-generator.md:
- Given a completed interview + 1-2 uploaded documents for the same patient, a structured
  summary is generated within a few seconds and matches the fixed schema.
- A physician can edit any field, confirm it, and the physician_edited flag correctly reflects
  whether it was touched.
- Never present the summary as anything other than an editable draft in the UI copy/design.

When done:
- Check off completed Phase 4–5 items in docs/dev/tasks-phased.md.
- Clearly flag in your summary that the ABDM/FHIR push here is a stub, and hand off exactly
  what Module D needs to replace to make it real.
```

---

## Wave 5 — Module D: Consent, Privacy & ABDM Integration (full hardening)

```
You're completing Module D ("Consent, Privacy & ABDM Integration") of MediKiosk — the
security/compliance backbone — on top of everything built in previous waves (Phase 1 gave you
a basic consent flow and mocked ABHA; Module C left a stub FHIR push).

Read first:
- docs/project/00-problem-statement.md (Module D section; DPDP/ABDM notes under "why existing
  solutions fall short")
- docs/design/modules/module-d-consent-privacy-abdm.md — primary spec
- docs/project/01-architecture.md (the Security Layer's role)
- docs/dev/tasks-phased.md (Phase 4 ABDM items + Phase 6 hardening checklist)

Scope: this wave is about making the whole system's privacy/security/compliance story real,
not adding new patient-facing features. Go through the existing codebase (auth, interview,
documents, summaries) and retrofit/verify the following rather than building net-new screens.

Deliverables:
1. A single, real Security Layer component that every AI call and every patient-data write
   passes through — audit the current code and refactor call sites so they actually route
   through it, rather than checking consent ad hoc in each endpoint.
2. Verify and complete: no AI call (ASR, summarizer, entity extraction) or DB write of patient
   data can happen without a corresponding valid, unrevoked consent record covering that
   operation — write a test proving a revoked-consent request is rejected end to end.
3. audit_logs completeness: every read/write of patient data across all modules logs actor,
   action, resource, timestamp. Fill any gaps left by earlier waves.
4. Encryption: confirm TLS is enforced end-to-end in the deployed config, and add DB-level
   encryption at rest for the relevant columns/tables (per docs/design/03-data-model.md's PII/health
   data note).
5. Replace the mock AuthProvider from Phase 1 with a real ABDM sandbox client if sandbox access
   is available; otherwise harden the mock so it's obviously and clearly labeled everywhere
   it's used (docs, code comments, and — importantly — any demo-facing UI text), and document
   the exact swap-in steps for the real sandbox.
6. Replace the stub FHIR push from Module C with properly-shaped FHIR resource generation
   matching the summaries.structured_content schema, pushed to either the real ABDM sandbox or
   a clearly-labeled local mock endpoint that behaves like one.
7. Session data purge job: confirm raw audio, OCR scratch files, and other temporary session
   artifacts are actually deleted after a summary is confirmed and pushed — write a test.
8. RBAC pass: confirm patient/physician/admin roles are enforced at the API layer for every
   endpoint (not only hidden in the UI) — write a test per role boundary that matters.
9. Consent revocation: confirm DELETE /consent/{id} actually blocks all further processing for
   that patient/session — write a test.

Do not skip the tests — this wave exists specifically to prove the compliance claims from the
problem statement are real, not just documented.

When done:
- Check off completed Phase 4 (ABDM) and Phase 6 items in docs/dev/tasks-phased.md.
- Produce a short compliance summary (what's real, what's sandboxed/mocked and why) the team
  can read straight into the judging pitch.
```

---

## Wave 6 — Testing & Demo Prep (Phase 7)

```
You're closing out the MediKiosk build for the SIH demo — Phase 7 in docs/dev/tasks-phased.md. All of
Phase 0–1 and Modules A–D from previous waves are assumed complete.

Read first:
- docs/dev/tasks-phased.md (Phase 7 checklist)
- docs/project/00-problem-statement.md (Steps 1–5, to check nothing promised is missing)
- docs/guides/setup.md

Scope: no new features. This wave is testing, seed data, one-command deployment, and demo
readiness.

Deliverables:
1. Backend unit tests (pytest) for core logic not already covered: interview branching,
   red-flag rules, entity extraction, summarizer routing (Main API vs Local Offline), consent
   enforcement.
2. Frontend tests (vitest/jest) for the key screens: consent flow, interview screen, document
   upload, summary review.
3. One full end-to-end script/test walking Identify → Converse → Scan → Summarize & Route →
   Consult for a single seeded patient, asserting each stage's expected output exists.
4. Seed-data script: 2–3 sample patients covering at least one AYUSH-mode patient and one
   red-flag patient, with realistic sample documents.
5. Verify docker compose up brings up the full stack from a clean checkout with no manual
   steps beyond filling in .env — test this on a genuinely clean clone, not just your dev
   machine.
6. Write docs/dev/demo-script.md: a timed, step-by-step walkthrough for the live demo,
   referencing the seed data, explicitly noting anywhere the demo uses a mocked component
   (ABHA sandbox, FHIR endpoint, local LLM fallback) so the team can answer judges' questions
   honestly and confidently.

When done:
- Check off every remaining item in docs/dev/tasks-phased.md.
- Flag anything still rough/fragile that the team should avoid touching live during the demo.
```
