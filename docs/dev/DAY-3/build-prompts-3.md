# Build Prompts 3 — Day 3

Copy-paste prompts for AI coding agents. Organized by **priority** — do 🔴 first,
then 🟡, then 🟢.

## How to use

- **Run one prompt at a time** in a fresh AI session.
- **Review and test before moving on.**
- Each prompt tells the agent which files to read first for context.
- Each prompt ends by asking the agent to update `docs/dev/DAY-3/tasks-phased-3.md`.

---

## 🔴 Critical — Must Do Today

---

### Prompt F2 — Existing / New Patient Login with Doctor Selection & History

**No dependencies — start here.**

```
You're adding a proper patient login flow to MediKiosk (SIH 2026, PS 26047 — AI-powered
patient case-taking kiosk for AYUSH/allopathic OPDs).

Currently, login is bare-bones: enter patient_id or ABHA number. You're building a real
patient experience where returning patients can log in, see their past visits, select a
doctor/department, and start a new visit — while new patients go through registration.

Read first:
- docs/dev/DAY-3/tasks-phased-3.md (Feature F2 — full spec)
- docs/project/00-problem-statement.md — the clinical context
- backend/app/api/routes/auth.py — current auth endpoints
- backend/app/models/models.py — current DB models
- backend/app/services/auth_provider.py — ABHA mock
- frontend/src/pages/LoginPage.tsx — current login page
- frontend/src/pages/LanguageSelectPage.tsx
- frontend/src/store/ — state management
- frontend/src/App.tsx — routing

Branch: day3/patient-login

Deliverables:

BACKEND:

1. New DB model — `Doctor`:
   - id (uuid, pk), name (text), department (text — "General Medicine", "Ayurveda",
     "Cardiology", "Pediatrics", "Orthopedics", "ENT"), specialization (text),
     available (boolean, default true), queue_count (int, default 0),
     photo_url (text, nullable), created_at (timestamptz)
   - Add Alembic migration

2. New DB model — `Visit`:
   - id (uuid, pk), patient_id (fk → patients), doctor_id (fk → doctors, nullable),
     department (text), interview_session_id (fk → interview_sessions, nullable),
     summary_id (fk → summaries, nullable), status (text — "registered", "in_interview",
     "documents_uploaded", "summary_ready", "in_consultation", "completed"),
     token_number (int), chief_complaint (text, nullable), created_at (timestamptz),
     completed_at (timestamptz, nullable)
   - Token number auto-increments per day (reset daily)
   - Add Alembic migration

3. New endpoint — `POST /auth/login/returning`:
   - Accepts: {phone: str} or {phone: str, name: str}
   - Lookup patient by phone number
   - If found: return patient profile + JWT + list of past visits (last 10) with:
     - visit date, doctor name, department, chief complaint, status
   - If not found: return 404 with message "Patient not found. Please register."
   - This is simple phone-based lookup, no password (kiosk environment, MVP)

4. Update `POST /auth/register`:
   - Ensure phone number is stored and indexed
   - Return JWT as before

5. New endpoint — `GET /patients/{id}/history`:
   - Return complete patient history:
     - patient_info: name, age, gender, phone, abha_id, preferred_language
     - visits: list of past visits with dates, doctors, chief complaints, statuses
     - summaries: list of past structured summaries (brief — CC + HPI narrative only)
     - documents: list of past documents with types and dates
     - red_flags: any past red flags with dates

6. New endpoint — `GET /doctors`:
   - Return list of doctors, optionally filtered by `?department=Ayurveda`
   - Each doctor: name, department, specialization, available, queue_count

7. New endpoint — `POST /visits`:
   - Accepts: {patient_id, doctor_id, department}
   - Creates a visit with auto-incrementing token number (per day)
   - Increments the doctor's queue_count
   - Returns visit with token_number

8. New endpoint — `GET /visits/{id}`:
   - Return visit status and all linked data

9. Seed script `backend/scripts/seed_doctors.py`:
   - Create 6 demo doctors:
     - Dr. Arvind Sharma — General Medicine
     - Dr. Meera Patel — Ayurveda (Kayachikitsa)
     - Dr. Rajesh Reddy — Cardiology
     - Dr. Sunita Gupta — Pediatrics
     - Dr. Vikram Singh — Orthopedics
     - Dr. Anita Joshi — Ayurveda (Panchakarma)

FRONTEND:

10. Redesign LoginPage with a two-path flow:

    SCREEN 1 — Patient Type Selection (after language selection):
    - Two large, touch-friendly cards (at least 200px tall):
      - "New Patient / नया मरीज़" — hospital icon, subtitle "First time here? Register now"
      - "Returning Patient / पुराना मरीज़" — person icon, subtitle "Already registered? Welcome back"
    - Clean layout, centered, large text

    SCREEN 2A — New Patient Registration (existing flow, cleaned up):
    - Name, Age, Gender, Phone Number (required), ABHA ID (optional)
    - Large input fields, touch-friendly
    - "Register / रजिस्टर करें" button
    - After registration → Doctor Selection

    SCREEN 2B — Returning Patient Login:
    - Large phone number input field with +91 prefix
    - "Find My Record / मेरा रिकॉर्ड खोजें" button
    - On success: show patient name with greeting "Welcome back, Ramesh! / वापस स्वागत है, रमेश!"
    - Show last 3-5 visits as cards:
      - Date (formatted nicely), Doctor name, Department, Chief Complaint
      - Status badge (Completed ✅, In Progress 🔄)
    - "Start New Visit / नया दौरा शुरू करें" button
    - On failure: "Not found. Register as new patient?" with link

    SCREEN 3 — Doctor Selection (after login/register, before consent):
    - Header: "Select Department / विभाग चुनें"
    - Grid of department cards (3x2 on tablet, 2x3 on phone):
      - General Medicine 🏥
      - Ayurveda 🌿
      - Cardiology ❤️
      - Pediatrics 👶
      - Orthopedics 🦴
      - ENT 👂
    - After selecting department: show available doctors in that department
    - Each doctor card: name, specialization, "X patients in queue"
    - Select doctor → show token number ("Your Token: #23 / आपका टोकन: #23")
    - Large "Continue / आगे बढ़ें" button → Consent Page

11. Update App.tsx routing:
    - /login → Patient Type Selection
    - /login/new → New Patient Registration
    - /login/returning → Returning Patient Login
    - /select-doctor → Doctor Selection
    - After doctor selection → /consent

12. Update state management:
    - Store selected doctor, department, visit_id, token_number in visit store
    - Persist across the session

13. Add all new UI strings to both en.json and hi.json locale files

Design guidelines:
- KIOSK for elderly patients — text LARGE (text-xl minimum)
- Touch targets minimum 48px, preferably 60px for primary buttons
- Use existing color palette
- Phone number input: numeric keypad hint, auto-format

Constraints:
- Don't break existing auth flow — ABHA lookup should still work
- Phone-based login has no password — it's a kiosk, not banking. Document as demo.
- All new endpoints need consent middleware where appropriate
- Log all auth actions to audit_logs

Verification:
- New patient can register with phone → select doctor → get token → proceed to consent
- Returning patient enters phone → sees past visits → starts new visit → selects doctor
- Doctor list shows correct queue counts
- Token numbers auto-increment correctly
- All existing tests still pass

When done:
- Check off F2 items in docs/dev/DAY-3/tasks-phased-3.md
- Run the seed_doctors.py script and confirm doctors appear
```

---

### Prompt F1 — Conversation History API + Demo Seed Data

**No dependencies.**

```
You're adding conversation history retrieval and creating realistic demo seed data for
MediKiosk. The conversation engine works but there's no public API to fetch past
conversations, and there's no demo data to show during the SIH presentation.

Read first:
- docs/dev/DAY-3/tasks-phased-3.md (Feature F1)
- backend/app/interview/conversation.py — the conversational engine
- backend/app/api/routes/interview.py — existing endpoints (note _load_history is private)
- backend/app/models/models.py — InterviewMessage model, InterviewSession, etc.
- backend/scripts/seed_demo_data.py — existing seed script (Day 1)
- backend/app/interview/ontology.py — field definitions

Branch: day3/conversation-history

Deliverables:

BACKEND:

1. Add `GET /interview/sessions/{id}/messages`:
   - Return all InterviewMessage records for the session, ordered by created_at
   - Response: list of {id, role, content, extracted_data, input_mode, created_at}
   - Requires valid JWT (patient or physician)

2. Add `GET /interview/sessions/{id}/summary`:
   - Compile all extracted_data from the session's messages into a summary view:
     {
       "session_id": "...",
       "status": "in_progress",
       "progress_percent": 65,
       "sections": {
         "chief_complaint": {"status": "completed", "data": {"cc": "Chest pain"}},
         "hpi": {"status": "in_progress", "data": {"site": "Left side", "onset": "2 days"}},
         "pmh": {"status": "pending", "data": {}},
         ...
       },
       "red_flags": []
     }

3. Add `GET /patients/{id}/sessions`:
   - Return all interview sessions for a patient
   - Each: {id, mode, status, chief_complaint, started_at, completed_at, message_count}

4. Create `backend/scripts/seed_conversation_demo.py`:

   Create realistic, clinically believable demo data. This will be shown to SIH judges.

   PATIENT 1 — Ramesh Kumar (chest pain, RED FLAG):
   - Phone: 9876543210
   - Past visit (completed, 1 month ago): Fever interview, summary confirmed
   - Current visit (in_progress): Chest pain since 2 days
     - 8 realistic Hindi/English messages showing SOCRATES exploration
     - Red flag triggered (chest pain + breathlessness = critical)
     - extracted_data: cc="chest pain", hpi.site="left side", hpi.onset="2 days",
       hpi.character="pressure", hpi.radiation="left arm"
     - 2 documents attached: old ECG report, blood test

   PATIENT 2 — Priya Sharma (AYUSH mode, digestive complaints):
   - Phone: 9876543211
   - Current visit (in_progress, AYUSH mode):
     - 10 messages covering HPI + Ayurvedic assessment
     - Prakriti assessment questions and answers (Vata dominant)
     - extracted_data: ayush.prakriti.dominant_dosha="vata", ahara-vihara data

   PATIENT 3 — Sunita Devi (completed visit):
   - Phone: 9876543212
   - Past visit (completed, 2 weeks ago): Abdominal pain
     - Complete 12-message interview, all sections covered
     - Documents with entities, summary confirmed
     - Shows a fully completed journey

   Each patient must have: consent_records, interview_sessions, interview_messages,
   interview_answers, documents with entities where applicable.

Verification:
- Run seed script → 3 patients with complete histories
- GET /interview/sessions/{id}/messages → returns ordered history
- GET /interview/sessions/{id}/summary → returns structured sections
- GET /patients/{id}/sessions → lists sessions

When done:
- Check off F1 items in docs/dev/DAY-3/tasks-phased-3.md
```

---

### Prompt F3 — Ayurveda Interview Procedure

**No dependencies.**

```
You're implementing a comprehensive Ayurvedic clinical interview procedure for MediKiosk.
The kiosk is for the Ministry of Ayush / All India Institute of Ayurveda, so AYUSH mode
needs to be thorough, authentic, and follow traditional examination protocols.

Read first:
- docs/dev/DAY-3/tasks-phased-3.md (Feature F3 — complete Ayurvedic protocol spec)
- docs/project/00-ps-SIH.md — especially the Dashavidha Pariksha requirements
- docs/design/08-glossary.md — Ayurvedic terminology definitions
- docs/design/modules/module-a-interview-engine.md — Module A AYUSH extension spec
- backend/app/interview/conversation.py — current conversational engine
- backend/app/interview/ontology.py — current field definitions (has basic AYUSH fields)
- backend/app/interview/templates.py — question templates (has some AYUSH templates)

Branch: day3/ayurveda-interview

The conversational interview engine already supports an "ayush" mode flag, but the
Ayurvedic content is minimal. You're making it comprehensive.

Deliverables:

BACKEND:

1. Create `backend/app/interview/ayurveda.py`:
   - Define the complete Ayurvedic examination protocol as structured data
   - Include Trividha, Ashtavidha, and Dashavidha Pariksha definitions
   - Prakriti assessment with physical + mental characteristics and Vata/Pitta/Kapha
     scoring logic
   - Ahara-Vihara (diet & lifestyle) questionnaire structure
   - Nidana (causative factors) and Samprapti (pathogenesis) templates
   - Kiosk-appropriate questions for each (not all examinations can be done on kiosk —
     note which are doctor-only like Nadi/pulse palpation)

2. Update the conversational system prompt for AYUSH mode in conversation.py:
   - After standard HPI (SOCRATES), transition to Ayurvedic assessment
   - Ask questions conversationally, NOT like a form:
     GOOD: "Tell me about your body type — are you generally thin and light,
            medium build, or on the heavier side?"
     BAD:  "What is your Prakriti body frame type? Options: Vata, Pitta, Kapha"
   - Include quick_replies for Prakriti assessment
   - AI should explain Ayurvedic concepts in simple Hindi/English
   - Flow: SOCRATES → Ashtavidha → Prakriti Assessment → Ahara-Vihara → rest
   - Determine Prakriti based on answers (count Vata/Pitta/Kapha tendencies)

3. Extend the ontology (`ontology.py`) with comprehensive AYUSH fields:
   - ayush.prakriti.physical_traits, .mental_traits, .dominant_dosha
   - ayush.vikriti.aggravated_dosha, .symptoms
   - ayush.ashtavidha.nadi, .mutra, .mala, .jihva, .sparsha, .drik
   - ayush.ahara_vihara.diet, .routine, .satmya
   - ayush.sattva, ayush.ahara_shakti, ayush.vyayama_shakti
   - ayush.nidana, ayush.samprapti

4. Update the structured summary schema (summary/schemas.py):
   - Add `ayurvedic_assessment` section to StructuredSummary:
     - prakriti_determination, vikriti_assessment, ashtavidha_summary
     - diet_lifestyle_observations, nidana_analysis
     - treatment_direction ("Shamana" or "Shodhana" — NOT prescriptions)

5. Update the LLM summarizer prompt to include Ayurvedic assessment section when
   the interview was in AYUSH mode

6. Seed demo data: one complete AYUSH interview with realistic Prakriti assessment

FRONTEND:

7. In pre-interview screen, make AYUSH mode prominent:
   - Two equal-sized cards: "General / सामान्य 🏥" and "Ayurveda / आयुर्वेद 🌿"
   - AYUSH card subtitle: "Includes Prakriti & Dashavidha Pariksha"

8. In interview page, when in AYUSH mode:
   - Progress sections include Ayurvedic assessment sections
   - Visual Prakriti result display (Vata 💨 / Pitta 🔥 / Kapha 🌊 badges)
     after assessment

9. Summary page shows Ayurvedic assessment section for AYUSH interviews

Constraints:
- Protocol must be clinically authentic — SIH judges from AIIA will evaluate
- AI must NEVER make a specific diagnosis or prescribe medicines
- Prakriti is Vata/Pitta/Kapha or dual — preliminary assessment only
- Treatment direction is only "Shamana" or "Shodhana" — never specific therapies
- All Ayurvedic terms explained in simple language for patients

Verification:
- Start AYUSH interview → standard HPI first, then transitions to Ayurvedic assessment
- Prakriti questions asked conversationally with quick replies
- Dominant dosha determined and shown visually
- Ahara-Vihara covers diet and daily routine
- Summary includes full Ayurvedic assessment section

When done:
- Check off F3 items in docs/dev/DAY-3/tasks-phased-3.md
```

---

## 🟡 Should Do If Time Permits

---

### Prompt B3 — Physician Dashboard Improvements

**No hard dependencies, but better after F2 (patient history) and F3 (AYUSH).**

```
You're improving MediKiosk's physician dashboard. Doctors need to view uploaded documents,
see AI summaries, and download proper PDF reports.

Read first:
- docs/dev/DAY-3/tasks-phased-3.md (task B3)
- frontend/src/pages/SummaryReviewPage.tsx — current summary view
- frontend/src/pages/DashboardQueuePage.tsx — current queue
- Dashboard API: GET /dashboard/queue, GET /dashboard/patients/{id}/summary,
  GET /dashboard/patients/{id}/report (returns PDF from A5)
- GET /patients/{id}/history (from F2)

Branch: day3/doctor-dashboard

Deliverables:

1. Document viewer (modal or dedicated view):
   - Show original document image (full size, zoomable)
   - Extracted entities grouped by type:
     - Medications table (drug, dose, frequency)
     - Investigations table (test, value, unit, range) — abnormal in red
     - Diagnoses, Procedures lists
   - Close button to return

2. Summary review improvements:
   - Inline editing: click any text field to edit
   - "Physician Notes" textarea at bottom
   - "Accept All" one-click button
   - Loading state during generation
   - Ayurvedic Assessment section for AYUSH interviews:
     - Prakriti display with dosha badges
     - Ashtavidha summary

3. PDF download button: "📄 Download Report (PDF)"
   - Triggers GET /dashboard/patients/{id}/report (already returns PDF)

4. Patient detail view:
   - Patient info header (name, age, gender, ABHA, token #, doctor)
   - Visit history section (past visits)
   - Summary card with edit controls
   - Documents section (clickable → viewer)
   - Red flags displayed prominently

When done:
- Check off B3 items in docs/dev/DAY-3/tasks-phased-3.md
```

---

### Prompt B4 — Patient-Facing Summary (VisitDonePage)

```
You're improving MediKiosk's patient-facing completion page.

Read first:
- docs/dev/DAY-3/tasks-phased-3.md (task B4)
- frontend/src/pages/VisitDonePage.tsx — current page
- Backend: GET /summaries/{id}/patient-audio (already exists from A5)

Branch: day3/visit-done

Deliverables:
1. Fetch confirmed summary and show `patient_summary` in large Hindi text
2. Play TTS audio automatically (GET /summaries/{id}/patient-audio)
3. Show assigned doctor name and token number
4. Layout: centered, large text, "धन्यवाद" heading
5. "Start New Visit / नया दौरा शुरू करें" button → clears session → language select

When done:
- Check off B4 items in docs/dev/DAY-3/tasks-phased-3.md
```

---

## 🟢 Nice To Have

---

### Prompt B6 — AI Claim-to-Document Linking

**Depends on: B3 (Dashboard Improvements)**

```
You're adding a feature to the Doctor Dashboard that links AI-generated claims directly
back to their source documents.

Read first:
- frontend/src/pages/SummaryReviewPage.tsx
- docs/dev/DAY-3/tasks-phased-3.md (B6)
- backend/app/services/summary/schemas.py — StructuredSummary with sources mapping

Branch: day3/claim-linking

Deliverables:
1. "View Documents" button: prominent button in doctor UI to open a gallery/list of
   all uploaded documents for the patient.
2. Citation badges: parse the `sources` mapping from StructuredSummary. Next to each
   section (or specific claims if mapped), display a clickable citation badge
   (e.g., `[Doc 1]`, `[Lab Report - 12 Aug]`).
3. Document viewer integration: clicking the citation badge opens the document viewer
   modal (from B3), showing the exact document referenced.
4. If a section comes from "interview" source, show a chat icon instead.
5. If a section is "ai-inferred", show a small ⚡ AI badge.

When done:
- Check off B6 in docs/dev/DAY-3/tasks-phased-3.md
```
