# Tasks — Phased Build Plan 2 (Remaining + New Work)

Everything below is **net-new or incomplete** work. The original Phases 0–7 are almost
fully done — only three items were left unchecked. This plan rolls those forward alongside
the `tasks-manual.md` backlog, deployment, and new work identified from the SIH PS.

## Big architectural changes from Phase 1

Two major rethinks compared to the original build:

### 1. Interview is now a conversation, not a form
The deterministic state-machine Q&A is replaced with an **LLM-driven conversational agent**.
The interview feels like talking to ChatGPT — a chat-bubble UI where the AI asks
"What brings you here today?", listens, then generates SOCRATES-guided follow-ups
naturally. The AI still captures structured data behind the scenes (CC, HPI fields,
PMH, etc.) but the patient never sees a form.

### 2. Documents go straight to AI
Instead of OCR → regex extraction (which breaks on every layout variation), the new
approach feeds the document image/text **directly to the AI** (Azure OpenAI GPT-4o with
vision). The AI reads the document, extracts all entities, and produces a human-readable
summary in one shot. Simpler, more reliable, and works on any document format.

### 3. Azure AI Services ($4000 startup credits available)
A team member has $4000 in Azure credits. We switch to Azure for:
- **Azure OpenAI** (GPT-4o / GPT-4o-mini) — conversational interview, document analysis,
  summary generation
- **Azure Speech Services** — STT and TTS with native Hindi support (hi-IN locale)
- **Azure Document Intelligence** — high-quality OCR for printed + structured documents

Existing Sarvam/Whisper/Tesseract remain as fallback providers (multi-provider architecture).

---

## How to parallelise

```
Workstream A  (Backend)        ─── can run in parallel ───  Workstream B  (Frontend)
       │                                                            │
       └──────────────── merge both into main ──────────────────────┘
                                    │
                         Workstream C  (Deployment)
                                    │
                         Workstream D  (Final Polish & Demo)
```

**Branch naming:** `ws-a/<task>`, `ws-b/<task>`, `ws-c/<task>`, `ws-d/<task>`

---

## Workstream A — Backend (Person 1)

### A1 — 🔴 Azure AI Services integration layer

Set up the Azure SDK and provider abstraction so all AI features can use Azure.

- [x] Add Azure Python SDKs to `requirements.txt`:
      `openai` (for Azure OpenAI), `azure-cognitiveservices-speech`,
      `azure-ai-documentintelligence`
- [x] Create `backend/app/services/azure_ai.py` — unified Azure client initialization:
      - `get_azure_openai_client()` — returns configured `AzureOpenAI` client
      - `get_speech_config()` — returns `azure.cognitiveservices.speech.SpeechConfig`
      - `get_doc_intelligence_client()` — returns Document Intelligence client
- [x] Add env vars to `.env.example`:
      ```
      # Azure AI (all optional — existing providers remain as fallbacks)
      AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
      AZURE_OPENAI_API_KEY=
      AZURE_OPENAI_DEPLOYMENT=gpt-4o       # deployment name
      AZURE_SPEECH_KEY=
      AZURE_SPEECH_REGION=centralindia
      AZURE_DOC_INTELLIGENCE_ENDPOINT=
      AZURE_DOC_INTELLIGENCE_KEY=
      ```
- [x] Update provider dispatch in `asr.py`, `tts.py`, `ocr.py`, and `summary/llm.py`
      to check for Azure config and prefer it when available

---

### A2 — 🔴 Conversational interview engine (replaces dialogue state machine)

Replace the fixed Q&A state machine with an LLM-driven conversational agent.
The patient talks naturally; the AI guides them through SOCRATES and full history.

**Status: done.** One deliberate departure from the plan below — red flags are
*not* taken from the model's JSON. The deterministic `red_flags.evaluate_red_flags`
rules stay authoritative and run over the validated fields, exactly as they do for
the legacy engine; the model's own `concern` is recorded as advisory only. A model
that forgets to populate a `red_flag` key must not be able to turn triage off.

Extraction is validated against the ontology before it reaches the database. This
matters more than it sounds: the rules match exact option keys, so a model writing
the plausible `"shortness of breath"` instead of `"breathlessness"` would produce a
transcript that reads perfectly and fires no rule at all.

- [x] Create `backend/app/interview/conversation.py` — the new conversational engine:
      - System prompt defines the AI as a friendly, patient medical interviewer
      - First message: open-ended "Hello! What brings you here today? / नमस्ते! आज
        आपको क्या तकलीफ़ है?" (in patient's language)
      - AI listens to patient's response, identifies chief complaint
      - AI then asks SOCRATES-guided follow-ups conversationally, one at a time:
        e.g. "I see, you're having chest pain. When did this start?"
      - Behind the scenes, the AI fills a structured JSON schema (same fields as
        the current ontology: CC, HPI.site, HPI.onset, HPI.character, etc.)
      - After covering HPI, moves to PMH, drugs, allergies, family, personal, ROS
      - In AYUSH mode: also covers Dashavidha Pariksha fields
      - Red-flag detection: system prompt includes red-flag rules; AI checks after
        each response and returns a `red_flag` field if triggered
- [x] System prompt template (key parts):
      ```
      You are a warm, friendly medical interviewer at an Indian hospital kiosk.
      You are speaking to a patient who may be elderly, low-literacy, or
      unfamiliar with technology. Speak simply and reassuringly.

      Your job: collect a complete clinical history through natural conversation.
      Start by asking what brings them here today. Then ask follow-up questions
      ONE AT A TIME based on the SOCRATES framework and their responses.

      After each patient message, respond with JSON:
      {
        "reply": "Your conversational response + next question",
        "reply_hi": "Same in Hindi",
        "extracted_data": {"field_id": "value", ...},
        "section": "chief_complaint | hpi | pmh | drugs | ...",
        "red_flag": null | {"symptom": "...", "severity": "critical"},
        "interview_complete": false,
        "progress_percent": 15
      }

      RED FLAG RULES (fire immediately):
      - Chest pain + breathlessness → critical
      - Sudden weakness one side of body → critical
      - Severe headache + vision changes → high
      ...
      ```
- [x] New API endpoints (keep old ones for backward compatibility):
      - `POST /interview/sessions` — now also accepts `engine: "conversation" | "legacy"`
        (default: **`"legacy"`**, not `"conversation"` — the existing InterviewPage
        would break against a chat session, so the default flips when B1 ships.
        Requesting `conversation` with no hosted model configured is downgraded to
        legacy and reported in the response, rather than refused: a missing API key
        should not look like a broken kiosk.)
      - `POST /interview/sessions/{id}/message` — send a message (text from voice or
        typed), get back AI response + extracted data + red flags
      - The old `next-question`/`answer` endpoints still work for legacy mode
- [x] Conversation history stored in DB: new `interview_messages` table
      (session_id, role, content, extracted_data, input_mode, created_at)
- [x] At end of conversation, compile all `extracted_data` into structured
      `interview_answers` (same format as before) so the summarizer works unchanged
      — done **per turn** rather than at the end, so an interview abandoned halfway
      still leaves a usable partial record and red flags fire as soon as the fields
      that trigger them are captured

**Key files to modify:**
- `backend/app/interview/conversation.py` (NEW)
- `backend/app/api/routes/interview.py` (add `/message` endpoint)
- `backend/app/models/models.py` (add `InterviewMessage` model)
- `backend/alembic/versions/` (new migration for `interview_messages`)

---

### A3 — 🔴 Azure Speech Services STT + TTS

Replace/augment Whisper and Sarvam with Azure Speech Services.

**Status: done, and verified against the live service** — synthesised and then
transcribed back real consent copy in en, hi, ta, kn, bn and od, all round-tripping
essentially verbatim.

Three departures from the plan below, each deliberate:

1. **REST, not the SDKs.** `SpeechSynthesizer` and `SpeechRecognizer` are
   synchronous, and `synthesize`/`transcribe_audio` are `async` — calling them
   would block the event loop and stall the red-flag path. Both Azure SDKs are
   also still commented out in `requirements.txt`, so an SDK-based fallback would
   have been a silent no-op. REST over the existing httpx needs no new dependency.
2. **Sarvam stays primary; Azure is the fallback.** `TTS_PROVIDER` and
   `ASR_PROVIDER` now accept a chain (`sarvam,azure`) tried left to right. The
   original wording had Azure "preferred when configured", which is backwards for
   this team: Sarvam is better at code-mixed Indian speech, and Azure exists to
   catch a spent Sarvam account rather than to displace it.
3. **No key needed for Speech.** A multi-service Azure AI Services resource
   issues one key for everything, so `AZURE_SPEECH_KEY` falls back to
   `AZURE_OPENAI_API_KEY`. Only `AZURE_SPEECH_REGION` has to be set — and it
   genuinely has to be, because a key is region-scoped and the wrong region 401s.

- [x] Implement `transcribe_audio_azure()` in `asr.py`
      (Fast Transcription REST; language identification from a candidate list
      when the patient's language is unknown)
- [x] Implement `synthesize_azure()` in `tts.py`
      (SSML over REST; voices for all ten interface languages **plus Odia**,
      which Bulbul cannot voice at all, making Azure the only provider that can
      serve the full set)
- [x] Update provider dispatch — now an ordered chain rather than an exclusive
      choice, with `mock` permanently the last ASR rung so a failed
      transcription can never end an interview
- [x] Add `POST /api/v1/consent/audio` endpoint
- [x] Ensure language follows UI switcher: accept `?lang=hi` on all audio endpoints

Two bugs fixed along the way that the plan did not anticipate:

- The old Azure TTS stub wrote **44 bytes of silence into the cache**, where it
  passed the `st_size > 0` check forever. Any deployment that ever ran
  `TTS_PROVIDER=azure` has poisoned cache entries — delete `backend/tts_cache`.
- The cache filename hashed the *configured* provider and took its suffix from it
  too, so a clip served by an Azure fallback while `TTS_PROVIDER=sarvam` would be
  saved as `.wav` and served as `audio/wav`. The browser refuses that file and
  nothing in the logs explains why. Naming is now keyed on the serving provider.

One vendor quirk worth knowing: the language registry follows Sarvam and spells
Odia `od-IN`; Azure wants ISO `or-IN` and rejects `od-IN`. Translated in both
directions in `azure_ai.azure_locale` / `app_locale`.

---

### A4 — 🔴 AI-powered document analysis (replaces regex extraction)

Feed documents directly to AI instead of OCR → regex.

- [ ] Create `backend/app/services/document_ai.py`:
      - **Primary path (Azure Document Intelligence)**: use `prebuilt-read` or
        `prebuilt-layout` model to extract text + tables from document images
      - **AI analysis path (Azure OpenAI GPT-4o)**: send the extracted text (or
        the image directly via GPT-4o vision) with a structured prompt:
        ```
        Analyze this medical document and extract:
        {
          "doc_type": "lab_report | prescription | discharge_summary | ...",
          "summary": "2-3 sentence plain-language summary of what this document says",
          "summary_hi": "Same summary in Hindi",
          "diagnoses": [{"diagnosis": "..."}],
          "medications": [{"drug": "...", "dose": "...", "frequency": "..."}],
          "investigations": [{"test": "...", "value": ..., "unit": "...",
                              "reference_range": "...", "is_abnormal": true/false}],
          "procedures": [{"procedure": "..."}],
          "document_date": "YYYY-MM-DD or null"
        }
        ```
      - **Fallback path**: existing Tesseract + regex (unchanged, for when Azure is
        not configured)
- [ ] Update `POST /documents` route to use the new pipeline when Azure is configured
- [ ] Add `document_summary` and `document_summary_hi` fields to `DocumentDetailResponse`
- [ ] Add `AI_DOCUMENT_PROVIDER` env var: `azure` | `tesseract_regex` (default:
      `azure` if Azure keys present, else `tesseract_regex`)
- [ ] The doctor should be able to view the AI summary + all extracted entities for
      any uploaded document

**This replaces tasks A2, A7, P6, P8 from the previous plan** — feeding the document to
AI handles OCR, multi-language, entity extraction, and summarization all at once.

---

### A5 — 🔴 Improve summary quality + real PDF export

**Status: done.** Notes on choices that differ from the spec:

- `patient_summary` is written in the *patient's* language, not hardcoded Hindi —
  the app now serves ten languages, so the summariser is told the patient's
  language by name (which steers a model far better than a code) and writes those
  two sentences in it. The deterministic tier leaves it blank; only an LLM can
  translate and simplify, and the patient-audio route 404s cleanly when it is empty.
- `reportlab` over `weasyprint`: pure-Python, no Cairo/Pango system libraries, so
  it builds identically on Render and on a laptop. weasyprint's native deps are a
  deploy hazard we don't need.
- The PDF renderer (`summary/pdf.py`) never raises on a summary — a physician
  clicking Download mid-consult must not hit a 500 — and escapes all text, since
  an unescaped `&` in a drug name would otherwise abort a paragraph.

- [x] Rewrite LLM prompt in `llm.py`:
      - Reuses `post_chat_completion`, so Azure/OpenAI/Gemini selection is unchanged
      - HPI narrative is now a 3–4 sentence clinical prose story, not fragments
      - `patient_summary` field (2 plain sentences, in the patient's own language)
      - `sources` map: per-section provenance (interview | document | ai-inferred)
- [x] Add `physician_notes: str = ""` to `StructuredSummary` schema
      (plus `patient_summary` and `sources`; all default-empty so older stored
      summaries still validate)
- [x] **Real PDF export** — `dashboard.py` now serves `application/pdf` via
      `render_summary_pdf()`:
      - AIIA / Ministry of Ayush header with the tricolour rule
      - Patient demographics block (name, age/gender, ABHA, date)
      - Sections CC → HPI → PMH/PSH → drugs → allergies → family → personal → ROS
        → investigations → AYUSH
      - Abnormal investigation rows in red
      - Red flags boxed in a red-bordered panel near the top
      - Clinical impression labelled "AI-suggested, requires physician verification"
      - Physician name + signature line; filename `medikiosk_report_{id}.pdf`
- [x] Bilingual output: `GET /summaries/{id}/patient-audio` speaks `patient_summary`
      via the existing provider chain (patient-authenticated, ownership-checked)

---

### A6 — 🟡 Real embeddings (was P7)

**Status: done.** Provider selection with a hash fallback that keeps document
upload resilient — a real embedding provider that fails degrades to the hash and
logs, rather than failing the upload (a worse vector is recoverable, a lost
document is not). Verified live: the Azure path correctly fell back to hash on a
`DeploymentNotFound` when the resource had no embeddings deployment.

- [x] Real embeddings in `embeddings.py`:
      - `azure` — Azure OpenAI embeddings over REST (httpx, no extra dep), with
        `dimensions=384` pinned so the vector fits the existing `vector(384)` column
      - `local` — `sentence-transformers/all-MiniLM-L6-v2`, lazy-imported and
        module-cached; never auto-selected because it drags in torch (~2 GB)
      - `hash` — the deterministic pseudo-embedding, always-available fallback and
        the hermetic test default
- [x] Add `EMBEDDING_PROVIDER` (azure | local | hash; unset = Azure if configured
      else hash) and `EMBEDDING_MODEL` env vars. Tests stay offline because the
      fixtures blank the Azure vars, so resolution lands on hash.
- [ ] Embed interview answers too (new migration for `interview_answer_embeddings`)
      — deferred; the document-embedding contract is unchanged, so this can be
      added later without touching what exists.
- [x] Alternative: use Azure OpenAI embeddings (`text-embedding-3-small`) if configured

---

### A7 — 🟡 Encryption at rest (Phase 6 leftover)

- [ ] Add `pgcrypto` extension, implement column-level encryption for PII
- [ ] Update `compliance-summary.md`

---

### A8 — 🟢 Scheduled retention enforcement

- [ ] Background job enforcing `retention_days` from consent records
- [ ] Auto-delete expired patient data, log to `audit_logs`

---

### A9 — 🟢 Analytics endpoints

- [ ] `GET /analytics/daily-stats` — patients, interviews, documents, summaries per day
- [ ] `GET /analytics/avg-interview-time`
- [ ] `GET /analytics/red-flag-summary`

---

## Workstream B — Frontend (Person 2)

### B1 — 🔴 Chat-style interview UI (the big one)

Replace the form-style Q&A with a ChatGPT-like chat bubble interface.

- [ ] Create `frontend/src/pages/ChatInterviewPage.tsx` — new chat interface:
      - Full-height chat area with scrolling message history
      - **AI messages**: left-aligned bubbles with a bot avatar, light background
      - **Patient messages**: right-aligned bubbles, colored background
      - Text input bar at the bottom with a send button + mic button
      - Auto-plays TTS audio for each AI message
      - Shows a typing indicator ("..." animation) while waiting for AI response
      - Red flag: when fired, a full-width banner slides in from the top and stays
        pinned (like a notification bar)
      - Progress: subtle progress indicator in the header showing what section the
        AI is currently covering
- [ ] Mic button in the input bar:
      - Tap to start recording, tap again to stop (not hold-to-record — easier for
        elderly users)
      - Shows recording state with a pulsing red indicator
      - After recording stops, auto-transcribes and sends as a message
- [ ] Quick-reply buttons: when the AI offers choices (e.g., "Is the pain: sharp,
      dull, burning, or pressure?"), show them as tappable chips below the AI message.
      The patient can tap a chip OR type/speak their answer
- [ ] Keep the General/AYUSH mode selection on the pre-interview screen
- [ ] Mobile-friendly: the chat should feel native on a tablet/kiosk touchscreen
- [ ] Route: replace `/interview` with the new chat page; keep the old page accessible
      at `/interview/legacy` for fallback

---

### B2 — 🔴 UI cleanup (not a redesign, just make it look human-made)

Don't overhaul the design — just fix the obvious "AI-generated" tells.

- [x] Replace the "M" placeholder logo with a simple MediKiosk logo (SVG, clean)
- [x] Consistent spacing and padding across all pages (no cramped cards)
- [x] Consistent color palette — pick one primary color and use it everywhere
- [x] Minimum touch target 48px on all interactive elements
- [x] Replace "Loading…" text with simple spinners (not shimmer skeletons —
      keep it simple)
- [x] Consent screen: bigger checkboxes, more padding, speaker buttons more obvious
- [x] Document upload: cleaner drop zone, "Take Photo" button for mobile
- [x] Add shared design tokens to `tailwind.config.js`

**Not doing:** full design system, high-contrast mode, timeline redesign, complex
animations. UI might change later — keep it clean but don't over-invest.

---

### B3 — 🔴 Physician dashboard improvements

The doctor dashboard needs to actually be useful, not just functional.

- [ ] **Document viewer**: when the doctor clicks on an uploaded document, show:
      - The original document image (full-size, zoomable)
      - AI-generated summary of the document
      - Extracted entities listed below
      - If abnormal values: highlighted in red with the reference range
- [ ] **Summary review**: 
      - Click any field to edit inline
      - "Physician Notes" free-text section at the bottom
      - "Accept All" one-click button
      - Loading state with "Generating summary…" message during generation
- [ ] **PDF download** button that actually downloads a PDF (not .txt)
      - Button text: "Download Report (PDF)"
      - Triggers `GET /dashboard/patients/{id}/report` which now returns PDF
- [ ] **Patient detail view**: clean layout showing:
      - Patient info header (name, age, gender, ABHA ID)
      - Summary card (with edit controls)
      - Documents section (clickable list → opens document viewer)
      - Red flags prominently displayed

---

### B4 — 🟡 VisitDonePage: patient-facing summary

- [ ] After physician confirms, show patient a simple Hindi summary
- [ ] Large text, plain language: "आपको बुखार है, डॉक्टर ने 3 दिन की दवाई दी है"
- [ ] Play TTS audio of the summary
- [ ] "Start New Visit" / "धन्यवाद" button

---

### B5 — 🟢 Landing page

- [ ] Simple home page with MediKiosk branding and "Start New Visit" button
- [ ] Display in selected language

---

### B6 — 🟢 PWA / offline shell

- [ ] `manifest.json` + basic service worker for offline-capable app shell
- [ ] "Offline" banner when connectivity lost

---

## Workstream C — Deployment (Person 3 or shared)

### C1 — 🔴 Supabase setup (Postgres + pgvector + Storage)

- [ ] Create Supabase project, enable pgvector
- [ ] Create storage bucket `medikiosk-uploads`
- [ ] Implement/verify `SupabaseStorageBackend` in `storage.py`
- [ ] Add env vars to `.env.example`
- [ ] Run Alembic migrations against Supabase

---

### C2 — 🔴 Backend deployment on Render

- [ ] Create Render Web Service, root directory: `backend`
- [ ] Start command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- [ ] Set all env vars (DATABASE_URL from Supabase, Azure keys, JWT_SECRET, etc.)
- [ ] Verify `/health` and `/docs` respond
- [ ] Consider paid tier ($7/mo) for demo day (avoid cold starts)

---

### C3 — 🔴 Frontend deployment on Vercel

- [ ] Connect GitHub repo, root directory: `frontend`
- [ ] Set `VITE_API_BASE_URL` to Render backend URL
- [ ] Update backend CORS to include Vercel URL
- [ ] Verify full flow end-to-end

---

### C4 — 🟡 AWS EC2 alternative

- [ ] Create `infra/ec2-setup.sh` for Ubuntu 22.04
- [ ] Create `infra/nginx-ec2.conf` with Nginx reverse proxy + SSL
- [ ] Document security group rules

---

### C5 — 🔴 TLS / HTTPS

- [ ] Render + Vercel provide HTTPS by default — verify
- [ ] Set `sslmode=require` on Supabase connection
- [ ] Update `compliance-summary.md`

---

### C6 — 🔴 CI/CD pipeline

- [ ] GitHub Actions: on push to `main`, deploy to Render via deploy hook
- [ ] Add deployment status badge to README

---

### C7 — 🟢 Azure resource provisioning

- [ ] Create Azure OpenAI resource, deploy GPT-4o and GPT-4o-mini models
- [ ] Create Azure Speech Services resource (Central India region for low latency)
- [ ] Create Azure Document Intelligence resource
- [ ] Document all endpoint URLs and keys
- [ ] Estimate monthly cost against the $4000 credit budget

---

## Workstream D — Final Polish & Demo (Everyone, after merge)

### D1 — 🔴 E2E test on deployed environment

- [ ] Full patient journey on Render+Vercel+Supabase
- [ ] Verify Azure AI services work end-to-end (conversation, STT, TTS, doc analysis)
- [ ] Test fallback when Azure is unavailable (should use legacy providers)

---

### D2 — 🔴 Seed data on deployed environment

- [ ] Run `seed_demo_data.py` against deployed Supabase DB
- [ ] Verify demo physician login works

---

### D3 — 🔴 Pitch deck cross-reference (Phase 7 leftover)

- [ ] Cross-reference pitch deck against `00-problem-statement.md`
- [ ] Every claimed capability must be demoable
- [ ] Update `demo-script.md` with deployed URLs

---

### D4 — 🟡 Demo script for deployed version

- [ ] Rewrite demo script for cloud deployment
- [ ] Highlight the conversational interview experience
- [ ] Show document AI analysis vs old regex approach

---

### D5 — 🟢 Video demo recording

- [ ] Record 5-minute walkthrough as backup for live demo

---

## Priority Summary — What To Do Today

### 🔴 Must do (demo-critical)

| # | Task | Person | Est. time |
|---|------|--------|-----------|
| C1+C2+C3 | Deploy to Supabase + Render + Vercel | Person 3 | 1.5 hr |
| C7 | Provision Azure resources | Person 3 | 30 min |
| A1 | Azure AI integration layer | Person 1 | 1 hr |
| A2 | Conversational interview engine | Person 1 | 3–4 hr |
| A3 | Azure Speech STT + TTS | Person 1 | 1.5 hr |
| A4 | AI document analysis | Person 1 | 2 hr |
| A5 | Summary quality + PDF export | Person 1 | 2 hr |
| B1 | Chat-style interview UI | Person 2 | 3–4 hr |
| B2 | UI cleanup | Person 2 | 1.5 hr |
| B3 | Doctor dashboard improvements | Person 2 | 2 hr |
| C5+C6 | TLS + CI/CD | Person 3 | 30 min |
| D1+D2 | E2E test + seed data | Everyone | 30 min |

### 🟡 Should do if time permits

| # | Task | Est. time |
|---|------|-----------|
| A6 | Real embeddings | 1.5 hr |
| B4 | Patient-facing summary | 1 hr |
| C4 | EC2 alternative | 1 hr |
| D3+D4 | Pitch alignment + demo script | 1 hr |

### 🟢 Nice to have (post-demo)

| # | Task | Est. time |
|---|------|-----------|
| A7 | Encryption at rest | 2 hr |
| A8 | Retention enforcement | 1.5 hr |
| A9 | Analytics endpoints | 1.5 hr |
| B5 | Landing page | 30 min |
| B6 | PWA support | 1.5 hr |
| D5 | Video recording | 30 min |
