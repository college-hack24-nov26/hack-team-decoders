# Tasks — Phased Build Plan 3 (Day 3)

Everything below is **net-new work**. Day 1 built the core platform (Phases 0–5). Day 2
added Azure AI integration (A1), conversational interview engine (A2), Azure Speech
STT/TTS (A3), UI cleanup (B2), and most recently A5 (summary quality + real PDF export)
and A6 (real embeddings). The chat-style interview UI (B1) is deliberately skipped —
the existing dual-mode interview page stays.

## What's new in Day 3

### 1. Existing / New Patient Login with Doctor Selection & History (F2)
Patients can log in as a returning patient, see their past visits, and select which
doctor/department they want to see. Their history (past interviews, documents, summaries)
is persisted and retrievable across visits.

### 2. Conversation History + Demo Data (F1)
The conversation history from the interview is not currently fetchable via API. Add
endpoints to retrieve conversation history, build demo seed data with realistic past
interviews, and show a current interview summary view.

### 3. Ayurveda Interview Procedure (F3)
Dedicated Ayurvedic clinical interview following traditional AYUSH examination protocols
(Dashavidha Pariksha, Ashtavidha Pariksha, Ahara-Vihara, Nidana, Samprapti). Full
procedure documents will be uploaded later — this task sets up the framework and a solid
first-pass implementation based on existing ontology + SIH PS requirements.

### 4. Physician Dashboard Improvements (B3)
Doctor dashboard needs document viewer, inline summary editing, Ayurvedic assessment
display, and PDF download.

### 5. Patient-Facing Summary (B4)
VisitDonePage shows Hindi summary, plays TTS audio, shows doctor name + token number.

### 6. AI Claim-to-Document Linking (B6)
Doctor can view all documents, and clicking any AI claim links to the source document.

---

## Priority & Difficulty Matrix

| # | Task | Priority | Difficulty | Est. Time | Depends On |
|---|------|----------|------------|-----------|------------|
| **P1** | F2 — Existing/New patient login + doctor selection | 🔴 Critical | 🟠 Medium | 3 hr | — |
| **P2** | F1 — Conversation history fetch + demo data | 🔴 Critical | 🟢 Easy | 1.5 hr | — |
| **P3** | F3 — Ayurveda interview procedure | 🔴 Critical | 🟠 Medium | 2.5 hr | — |
| **P4** | B3 — Physician dashboard improvements | 🟡 High | 🟠 Medium | 2 hr | — |
| **P5** | B4 — Patient-facing summary (VisitDonePage) | 🟡 Medium | 🟢 Easy | 1 hr | — |
| **P6** | B6 — AI Claim-to-Document linking (Doctor UI) | 🟢 Low | 🟢 Easy | 1.5 hr | B3 |

**Execution order** (critical path):
```
F2 (patient login) ──→ F1 (history + demo) ──→ F3 (ayurveda)
                                                    ↓
                                    B3 (dashboard) ──→ B4 (visit done) ──→ B6 (claim linking)
```

---

## Feature F2 — Existing / New Patient Login with Doctor Selection & History

### 🔴 Priority: Critical | 🟠 Difficulty: Medium | ⏱ Est: 3 hr

Current login is bare-bones: enter patient_id or ABHA. Need a proper flow where
patients can come back as returning users, select their doctor/department, and have
their complete history available.

**Backend:**

**Status: done.** One design note: `Doctor` (a kiosk-selectable person with a
queue) is kept separate from `Physician` (a login account). Most doctors never
log in, and a queue entry has no business carrying a password column. Token
numbers restart daily, computed per calendar day at booking rather than from a
global sequence.

- [x] New model: `Doctor` table
      - id, name, department, specialization, available, queue_count, photo_url
      - Migration `0005_doctors_and_visits`
- [x] New model: `Visit` table (wraps a single kiosk visit)
      - patient_id, doctor_id (nullable), department, interview_session_id (nullable),
        summary_id (nullable), status, token_number (per-day), chief_complaint,
        created_at, completed_at
      - Same migration `0005`
- [x] `POST /auth/login/returning` — phone lookup, returns profile + JWT + last 10
      visits (no password: kiosk MVP, documented). `patients.phone` is now indexed.
- [x] `GET /patients/{id}/history` — visits, brief past summaries (CC + HPI),
      documents, and red flags. Patient-authenticated, ownership enforced as 404.
- [x] `GET /doctors` — list, filterable by `?department=`, ordered available-then-shortest-queue
- [x] `POST /visits` — books a visit, per-day token, increments the doctor's queue
- [x] `GET /visits/{id}` — visit status and linked records (ownership-checked)
- [x] Seed demo doctors via `app/bootstrap.py` (`MEDIKIOSK_BOOTSTRAP=seed|demo`) —
      7 across 6 departments (2 Ayurveda), one per department for full coverage

**Frontend:**

- [x] Redesigned login flow:
      1. **Landing choice** — `/login`: New Patient vs Returning Patient cards
      2. **New Patient** — `/login/new`: the existing register/ABHA/Aadhaar screen
      3. **Returning Patient** — `/login/returning`: phone lookup, greeting, past-visit cards
      4. **Doctor Selection** — `/select-doctor`: department grid → doctors with queue → token → consent
- [x] Patient history / past visits shown on the returning-patient screen
- [x] Token number captured in the visit store and carried into the visit
- [x] New UI strings added to **all ten** locales (en/hi hand-authored, the other
      eight machine-translated with placeholders preserved, to keep the parity test green)

---

## Super-Admin (added on request — not in the original F2 spec)

A super-admin is a `Physician` with `role="admin"` (the role ladder and
`require_role` already existed; this is the first thing to use the top rung).

**Backend** — `app/api/routes/admin.py`, all admin-only:
- [x] `GET /admin/overview` — system-wide counts (patients, visits, interviews,
      summaries, red flags, doctors, physicians)
- [x] `GET /admin/patients` — every patient with a visit count
- [x] `GET /admin/audit` — recent audit-log entries (the compliance trail)
- [x] `GET/POST /admin/physicians`, `PATCH /admin/physicians/{id}` — create and
      manage login accounts (physician/staff/admin). Self-lockout guarded; created
      logins can actually sign in.
- [x] `POST/PATCH /admin/doctors` — add and edit kiosk-selectable doctors
- [x] Provision an admin with `python -m app.seed_physician --role admin`

**Frontend:**
- [x] `/admin/login` — admin sign-in (rejects non-admin accounts)
- [x] `/admin` — dashboard: overview stats, create-doctor and create-login forms,
      patient and physician tables

---

## Feature F1 — Conversation History Fetch + Demo Data

### 🔴 Priority: Critical | 🟢 Difficulty: Easy | ⏱ Est: 1.5 hr

The conversation messages exist in the `interview_messages` table but there's no public
API to retrieve them and no demo data to show during the SIH presentation.

**Backend:**

- [ ] `GET /interview/sessions/{id}/messages` — return all messages for a session,
      ordered by `created_at`, including role, content, extracted_data, input_mode
- [ ] `GET /interview/sessions/{id}/summary` — return a live interview summary
      compiled from all `extracted_data` collected so far (CC, HPI fields filled, etc.)
- [ ] `GET /patients/{id}/sessions` — list all interview sessions for a patient
      with basic metadata (date, chief complaint, status, mode)
- [x] Curated demo dataset `backend/app/demo_seed.py`, driven by
      `MEDIKIOSK_BOOTSTRAP=demo` (startup env var, not a shell script — Render
      free tier has no shell). Wipes patient data, then builds 7 patients:
      - Ramesh Kumar — RETURNING, two visits weeks apart (fever → chest pain
        red flag), so history syncs across visits
      - Priya Sharma — AYUSH-mode digestive case (prakriti/agni assessment)
      - Sunita Devi — completed General Medicine journey with labs
      - Arjun Nair — Pediatrics (parent-assisted), confirmed summary
      - Fatima Sheikh — breathlessness RED FLAG, draft summary
      - Imran Khan — ENT (otitis media), confirmed summary
      - Mohan Rao — completed interview + docs but NO summary, for LIVE
        generation in front of the judges
      - Each carries interview_messages / interview_answers, documents +
        entities, and (except Mohan) a hand-authored structured summary. One
        doctor per department is seeded so doctor-selection is fully populated.
      - Tests: `backend/tests/test_demo_seed.py` (FK-enforced counts + shape).

**Frontend:**

- [ ] In the interview page: when loading an existing session, fetch and render the
      full message history
- [ ] Interview summary view showing what's been captured so far:
      - Chief Complaint: ✅ Chest pain
      - HPI (Site): ✅ Left side
      - HPI (Onset): ✅ 2 days ago
      - PMH: ⏳ Not yet asked
      - Progress bar showing overall completion
- [ ] Patient history view: when a returning patient logs in, show their past visits
      as cards (date, chief complaint, status) with option to start a new visit

---

## Feature F3 — Ayurveda Interview Procedure

### 🔴 Priority: Critical | 🟠 Difficulty: Medium | ⏱ Est: 2.5 hr

The conversational interview engine supports AYUSH mode but the Ayurvedic clinical
examination procedure needs to be comprehensive and follow traditional protocols.
Documents with the full procedure will be uploaded later — this sets up the framework.

**Backend:**

- [ ] Create `backend/app/interview/ayurveda.py` — Ayurvedic interview protocol:

      **Trividha Pariksha (3-fold examination):**
      - Darshana (Inspection), Sparshana (Palpation), Prashna (Questioning)

      **Ashtavidha Pariksha (8-fold examination):**
      - Nadi (Pulse), Mutra (Urine), Mala (Stool), Jihva (Tongue),
        Shabda (Voice), Sparsha (Skin), Drik (Eyes), Akruti (Body build)

      **Dashavidha Pariksha (10-fold examination):**
      1. Prakriti — constitutional type (Vata/Pitta/Kapha)
      2. Vikriti — current imbalance assessment
      3. Sara — tissue quality assessment
      4. Samhanana — body compactness/physique
      5. Pramana — body proportions
      6. Satmya — habitual tolerances
      7. Sattva — mental strength/resilience
      8. Ahara Shakti — dietary/digestive capacity
      9. Vyayama Shakti — exercise capacity
      10. Vaya — age-related assessment

      **Ahara-Vihara (Diet & Lifestyle):**
      - Ahara: meals, timing, preferences, Rasa preferences
      - Vihara: daily routine, Dinacharya, Ritucharya

      **Nidana (Causative Factors) + Samprapti (Pathogenesis)**

- [ ] Update the conversational system prompt for AYUSH mode:
      - After standard HPI (SOCRATES), transition to Ayurvedic assessment
      - Ask Prakriti assessment questions conversationally
      - Ask digestive pattern, daily routine (Dinacharya) questions
      - Quick-reply options for Prakriti assessment
      - AI should explain Ayurvedic concepts in simple language

- [ ] Extend the ontology (`ontology.py`) with comprehensive AYUSH fields:
      - `ayush.prakriti.physical`, `.mental`, `.dominant_dosha`
      - `ayush.vikriti.aggravated_dosha`, `.symptoms`
      - `ayush.ashtavidha.nadi`, `.mutra`, `.mala`, `.jihva`, `.sparsha`, `.drik`
      - `ayush.ahara_vihara.diet`, `.routine`, `.satmya`
      - `ayush.sattva`, `ayush.ahara_shakti`, `ayush.vyayama_shakti`
      - `ayush.nidana`, `ayush.samprapti`

- [ ] Update the structured summary schema to include a dedicated "Ayurvedic Assessment"
      section with Prakriti determination, current Vikriti, and treatment principle
      suggestions (Shamana/Shodhana direction — NOT prescriptions)

- [ ] Seed demo data: one AYUSH-mode interview with realistic Ayurvedic responses

**Frontend:**

- [ ] In the pre-interview screen, make AYUSH mode more prominent:
      - Two large cards: "General / सामान्य 🏥" and "Ayurveda / आयुर्वेद 🌿"
      - AYUSH card includes subtitle: "Includes Prakriti & Dashavidha Pariksha assessment"
- [ ] In the interview page, when in AYUSH mode:
      - Progress sections include Ayurvedic assessment sections
      - Visual Prakriti result display (Vata/Pitta/Kapha badges) after assessment
- [ ] Summary page shows Ayurvedic assessment section for AYUSH interviews

---

## B3 — Physician Dashboard Improvements

### 🟡 Priority: High | 🟠 Difficulty: Medium | ⏱ Est: 2 hr

**Status: NOT STARTED**

- [ ] Document viewer: original image + AI summary + extracted entities
- [ ] Summary review: inline editing, physician notes, "Accept All" button
- [ ] PDF download button (triggers real PDF endpoint — already built in A5)
- [ ] Patient detail view: info header + summary card + documents + red flags
- [ ] Ayurvedic assessment display for AYUSH interviews
- [ ] Patient visit history visible to physician

---

## B4 — Patient-Facing Summary (VisitDonePage)

### 🟡 Priority: Medium | 🟢 Difficulty: Easy | ⏱ Est: 1 hr

**Status: NOT STARTED**

- [ ] Show patient summary in Hindi, large text, plain language
- [ ] Play TTS audio of the summary (endpoint already exists from A5)
- [ ] "Start New Visit" / "धन्यवाद" button
- [ ] Show assigned doctor name + token number

---

## B6 — AI Claim-to-Document Linking (Doctor UI)

### 🟢 Priority: Low | 🟢 Difficulty: Easy | ⏱ Est: 1.5 hr

**Status: NOT STARTED**

- [ ] "View Documents" button in the doctor dashboard to open a gallery of all uploaded docs
- [ ] Display source citations (e.g. `[Doc 1]`) next to summary sections based on
      the `sources` mapping from `StructuredSummary`
- [ ] Clicking a citation opens the document viewer modal showing the exact source document

---

## Priority Summary — What To Do Today

### 🔴 Must do (demo-critical)

| # | Task | Est. time | Depends on |
|---|------|-----------|------------|
| F2 | Existing/New patient login + doctor selection | 3 hr | — |
| F1 | Conversation history API + demo seed data | 1.5 hr | — |
| F3 | Ayurveda interview procedure | 2.5 hr | — |

### 🟡 Should do if time permits

| # | Task | Est. time | Depends on |
|---|------|-----------|------------|
| B3 | Doctor dashboard improvements | 2 hr | — |
| B4 | Patient-facing summary page | 1 hr | — |

### 🟢 Nice to have

| # | Task | Est. time | Depends on |
|---|------|-----------|------------|
| B6 | AI Claim-to-Document Linking | 1.5 hr | B3 |

---

## Total estimated work: ~11.5 hours

**Critical path (7 hours):** F2 → F1 → F3
**Should-do (3 hours):** B3 → B4
**Nice-to-have (1.5 hours):** B6
