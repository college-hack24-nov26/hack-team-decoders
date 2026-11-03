# Build Prompts 2 — Parallel Workstreams

Copy-paste prompts for AI coding agents. Organized into **parallel workstreams** so
multiple people work on separate branches simultaneously.

## How to use

- **Each workstream runs on its own branch** (`ws-a/`, `ws-b/`, `ws-c/`).
- **Run one prompt at a time** in a fresh AI session.
- **Merge order:** A + B + C can start simultaneously. Some B tasks depend on A
  (noted inline). Workstream D runs last.
- Each prompt ends by asking the agent to update `docs/dev/tasks-phased-2.md`.

---

## Workstream A — Backend

**Who:** Person 1 (backend-focused)
**Branch prefix:** `ws-a/`

---

### Prompt A1 — Azure AI Services Integration Layer

```
You're working on MediKiosk (SIH 2026, PS 26047 — AI-powered patient case-taking platform
for AYUSH/allopathic OPDs). The full app is built and working locally. You're now adding
Azure AI as the primary AI provider.

The team has $4000 in Azure startup credits. Azure provides:
- Azure OpenAI (GPT-4o, GPT-4o-mini) for conversational AI, document analysis, summaries
- Azure Speech Services for STT and TTS with native Hindi support
- Azure Document Intelligence for high-quality OCR

Read first:
- docs/project/00-problem-statement.md
- docs/project/02-tech-stack.md
- docs/dev/tasks-phased-2.md (task A1)
- backend/app/services/ — existing service files (ocr.py, embeddings.py, etc.)
- backend/app/interview/asr.py and tts.py — existing STT/TTS providers
- backend/app/services/summary/llm.py — existing LLM summarizer
- backend/app/core/config.py — settings/config

Branch: ws-a/azure-integration

Scope: Set up the Azure SDK integration layer. Do NOT build the conversational interview
yet (that's the next prompt). This prompt creates the shared infrastructure that all
Azure-powered features will use.

Deliverables:
1. Add to requirements.txt:
   - `openai` (for Azure OpenAI — the official OpenAI Python client supports Azure endpoints)
   - `azure-cognitiveservices-speech`
   - `azure-ai-documentintelligence`

2. Create `backend/app/services/azure_ai.py`:
   - `get_azure_openai_client()` — returns a configured `AzureOpenAI` client using
     AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY from settings
   - `get_speech_config()` — returns an `azure.cognitiveservices.speech.SpeechConfig`
     configured with AZURE_SPEECH_KEY and AZURE_SPEECH_REGION
   - `get_doc_intelligence_client()` — returns a Document Intelligence client
   - Each function should return None if the required env vars aren't set
     (so the app still works without Azure)

3. Update `backend/app/core/config.py` — add Azure settings:
   - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT (default: "gpt-4o")
   - AZURE_SPEECH_KEY, AZURE_SPEECH_REGION (default: "centralindia")
   - AZURE_DOC_INTELLIGENCE_ENDPOINT, AZURE_DOC_INTELLIGENCE_KEY

4. Add all Azure env vars to `backend/.env.example` with comments explaining each

5. Update the existing provider dispatch pattern:
   - In `asr.py`: add `azure` option to provider dispatch (implement stub that
     imports from azure_ai, actual impl in next prompt)
   - In `tts.py`: same
   - In `summary/llm.py`: update `summarize_main_api()` to use Azure OpenAI client
     when AZURE_OPENAI_ENDPOINT is set, keeping the existing OpenAI-compatible path
     as fallback
   - In `ocr.py`: add `azure` option (stub for now)

Constraints:
- All Azure features are OPTIONAL. The app must still work without any Azure config
  (fallback to existing Whisper/Sarvam/Tesseract/mock providers)
- Don't break any existing tests

Verification:
- All existing tests pass
- With no Azure env vars set: app starts and works exactly as before
- With Azure env vars set: `get_azure_openai_client()` returns a valid client
- `summarize_main_api()` uses Azure OpenAI when configured

When done:
- Check off A1 items in docs/dev/tasks-phased-2.md
- Document which Azure resources need to be provisioned and their names
```

---

### Prompt A2 — Conversational Interview Engine

```
You're replacing MediKiosk's fixed Q&A interview with an LLM-driven conversational agent.
The interview should feel like talking to ChatGPT — natural conversation, not a form.

Read first:
- docs/dev/tasks-phased-2.md (task A2 — full spec)
- docs/project/00-ps-SIH.md — the full SIH problem statement (note: "adaptive AI interview",
  "conversational guidance", "asks intelligent follow-up questions")
- backend/app/interview/dialogue.py — the CURRENT deterministic state machine (you're replacing this)
- backend/app/interview/ontology.py — the field definitions (CC, HPI, PMH, etc.) — these stay
- backend/app/interview/templates.py — the SOCRATES question templates — use as reference
- backend/app/api/routes/interview.py — current API endpoints
- backend/app/services/azure_ai.py — Azure OpenAI client (from previous prompt)
- backend/app/models/models.py — DB models

Branch: ws-a/conversational-interview

The patient opens the interview and the AI says something like "Hello! What brings you here
today?" The patient says "I have chest pain since 2 days". The AI responds conversationally:
"I'm sorry to hear about your chest pain. Can you tell me where exactly you feel the pain?"
And so on through SOCRATES, then PMH, drugs, allergies, family, personal, ROS.

The AI still captures structured data behind the scenes — same fields as the ontology.
Red flags are still detected (chest pain + breathlessness = critical).

Deliverables:

1. Create `backend/app/interview/conversation.py`:

   The system prompt is the most important part. It should:
   - Define the AI as a warm, friendly medical interviewer at an Indian hospital
   - Instruct it to speak simply (elderly, low-literacy patients)
   - Start with "What brings you here today?" (open-ended)
   - After identifying chief complaint, ask SOCRATES follow-ups ONE AT A TIME
   - After HPI, move to PMH, drugs, allergies, family, personal, ROS
   - In AYUSH mode: also Dashavidha Pariksha fields
   - After each patient message, return JSON:
     ```json
     {
       "reply": "Conversational response + next question in English",
       "reply_hi": "Same in Hindi",
       "extracted_data": {"field_id": "value"},
       "section": "chief_complaint | hpi | pmh | ...",
       "red_flag": null,
       "interview_complete": false,
       "progress_percent": 15,
       "quick_replies": ["sharp", "dull", "burning", "pressure"]
     }
     ```
   - Include red-flag rules in the prompt (chest pain + breathlessness, stroke
     symptoms, etc.) — the AI checks after every response
   - `quick_replies` are optional suggested answers the patient can tap

2. New DB model — `InterviewMessage`:
   - id, session_id (FK), role ("assistant" | "user"), content (text),
     extracted_data (jsonb, nullable), timestamp
   - Add Alembic migration

3. New API endpoint — `POST /interview/sessions/{id}/message`:
   - Accepts: `{"text": "...", "input_mode": "voice" | "touch"}`
   - Builds conversation history from InterviewMessage rows for this session
   - Calls Azure OpenAI (or fallback LLM) with system prompt + history + new message
   - Parses the JSON response
   - Stores both user message and assistant message in InterviewMessage
   - Stores any extracted_data in interview_answers (same as before)
   - Checks red_flag and creates RedFlag records if triggered
   - Returns the AI response to the frontend

4. Update `POST /interview/sessions`:
   - Accept `engine` param: "conversation" (default) | "legacy"
   - For conversation mode: create session, send the first AI greeting message
     automatically, return it
   - For legacy mode: existing behavior unchanged

5. Keep all existing endpoints working — the old flow is the "legacy" fallback

Constraints:
- The system prompt is where the magic is. Spend time on it. It should produce
  responses that feel like a real conversation, not "What is the onset of your symptom?"
- The AI must NEVER make a diagnosis or prescribe treatment
- The structured data extraction must be reliable — validate the JSON output
- If Azure OpenAI is not configured, fall back to any OpenAI-compatible endpoint
  (MAIN_LLM_ENDPOINT), or if none, return a clear error

Verification:
- Start a conversation session → first message is a warm greeting asking what's wrong
- Send "I have chest pain since 2 days" → AI acknowledges and asks about location
- After several exchanges, the AI has filled chief_complaint, hpi.onset, hpi.site, etc.
  in interview_answers
- Send answers that trigger a red flag → red_flag field is populated, RedFlag record created
- Complete the interview → interview_complete=true, all expected fields extracted
- Legacy mode still works for the old Q&A flow

When done:
- Check off A2 items in docs/dev/tasks-phased-2.md
- Include the full system prompt in your summary so the team can review/tune it
```

---

### Prompt A3 — Azure Speech Services STT + TTS

```
You're adding Azure Speech Services as the primary STT and TTS provider for MediKiosk.
Azure provides native Hindi support with high-quality neural voices.

Read first:
- docs/dev/tasks-phased-2.md (task A3)
- backend/app/interview/asr.py — current STT implementation
- backend/app/interview/tts.py — current TTS implementation
- backend/app/services/azure_ai.py — Azure client setup (from A1)

Branch: ws-a/azure-speech

Deliverables:

1. In `asr.py`, implement `transcribe_audio_azure(audio_bytes, language)`:
   - Use `azure.cognitiveservices.speech` SDK
   - Create a SpeechRecognizer with the audio data
   - Set recognition language: `hi-IN` for Hindi, `en-IN` for English
   - Return the transcript text
   - Handle errors gracefully (return empty string, log warning)

2. In `tts.py`, implement `synthesize_azure(text, language)`:
   - Use Azure neural voices:
     - Hindi: `hi-IN-SwaraNeural` (female) or `hi-IN-MadhurNeural` (male)
     - English: `en-IN-NeerjaNeural` (female) or `en-IN-PrabhatNeural` (male)
   - Return audio bytes (WAV or MP3)
   - Handle errors gracefully (fall back to existing TTS)

3. Update provider dispatch:
   - ASR_PROVIDER options: `azure` | `whisper` | `sarvam` | `mock`
   - TTS_PROVIDER options: `azure` | `sarvam` | `browser` | `mock`
   - When `azure` is selected but Azure keys aren't set, auto-fallback to next provider
   - Default: `azure` if AZURE_SPEECH_KEY is set, else existing default

4. Add `POST /api/v1/consent/audio` endpoint:
   - Accepts `{text: str, language: str}`
   - Calls TTS (whichever provider is configured)
   - Returns audio file
   - This gives the consent screen proper TTS instead of browser SpeechSynthesis

5. All audio endpoints should respect the UI language:
   - Accept `?lang=hi` or read from session/request
   - Pass language to both STT and TTS providers

Verification:
- With Azure configured: STT transcribes Hindi audio correctly
- With Azure configured: TTS produces clear Hindi speech
- Without Azure: falls back to Whisper/Sarvam/mock transparently
- Consent audio endpoint works

When done:
- Check off A3 items in docs/dev/tasks-phased-2.md
- Note the audio quality compared to existing providers
```

---

### Prompt A4 — AI-Powered Document Analysis

```
You're replacing MediKiosk's OCR + regex extraction pipeline with direct AI analysis.
Instead of Tesseract OCR → regex patterns (which break on every layout variation),
feed the document directly to AI and let it extract everything.

Read first:
- docs/dev/tasks-phased-2.md (task A4)
- backend/app/services/ocr.py — current OCR engines
- backend/app/services/entity_extraction.py — current regex extraction (this is what's broken)
- backend/app/api/routes/documents.py — upload endpoint
- backend/app/services/azure_ai.py — Azure clients (from A1)
- backend/app/services/reference_ranges.py — abnormal value detection

Branch: ws-a/document-ai

The current pipeline: upload image → Tesseract OCR → regex extraction → entities.
The regex breaks on any document layout it hasn't seen.

New pipeline: upload image → Azure Document Intelligence (text + tables) → Azure OpenAI
GPT-4o (structured extraction + summary) → entities. Falls back to old pipeline if
Azure isn't configured.

Deliverables:

1. Create `backend/app/services/document_ai.py`:

   `async def analyze_document_ai(image_bytes, patient_language) -> ExtractionResult`:
   - Step 1: Use Azure Document Intelligence `prebuilt-layout` model to extract
     text and table structure from the image
   - Step 2: Send the extracted text to Azure OpenAI GPT-4o with this prompt:
     ```
     You are a medical document analysis AI. Analyze this medical document and
     extract structured information.

     DOCUMENT TEXT:
     {extracted_text}

     Return ONLY valid JSON:
     {
       "doc_type": "lab_report | prescription | discharge_summary | radiology |
                    vaccination | opd_slip | other",
       "summary": "2-3 sentence plain-language summary of what this document says,
                   suitable for a patient who may not understand medical terms",
       "summary_hi": "Same summary in Hindi",
       "diagnoses": [{"diagnosis": "..."}],
       "medications": [{"drug": "...", "dose": "...", "frequency": "..."}],
       "investigations": [{"test": "...", "value": 0.0, "unit": "...",
                           "reference_range": "...", "is_abnormal": true/false}],
       "procedures": [{"procedure": "..."}],
       "document_date": "YYYY-MM-DD or null"
     }
     ```
   - Step 3: Parse the JSON, run `flag_abnormal()` from reference_ranges.py on
     investigation values to verify/correct the AI's abnormal flags
   - Step 4: Return an ExtractionResult (same shape as the existing one, so the
     rest of the codebase works unchanged)

   Alternative fast path: if the document is a clear image, consider sending
   it directly to GPT-4o with vision (skip Document Intelligence). This is
   simpler but more expensive per call. Make it configurable.

2. Update `ExtractionResult` dataclass:
   - Add `summary: str = ""`
   - Add `summary_hi: str = ""`

3. Update `POST /documents` route in `documents.py`:
   - When Azure is configured: use `analyze_document_ai()`
   - When not configured: use existing `ocr.py` + `entity_extraction.py` pipeline
   - Add `AI_DOCUMENT_PROVIDER` env var: `azure` (default if keys present) | `legacy`

4. Update document detail response schema:
   - Add `document_summary` and `document_summary_hi` fields
   - These come from the ExtractionResult

5. Add a new endpoint for the doctor to view document details:
   - `GET /documents/{id}/analysis` — returns the full AI analysis including
     summary, entities, and the original document image URL
   - This is what the doctor's document viewer will call

Constraints:
- The old Tesseract + regex pipeline must still work as a fallback
- Don't change the ExtractionResult shape in a way that breaks existing code
  (add fields, don't remove/rename)
- Document Intelligence + GPT-4o should handle ANY document format — that's the
  whole point of switching from regex

Verification:
- Upload a lab report image → AI extracts test values with correct abnormal flags
- Upload a prescription → AI extracts medications, doses, frequencies
- Upload something the old regex would fail on (a random hospital's report) → AI
  still extracts meaningful entities
- Each document has a plain-language summary in both English and Hindi
- Without Azure: falls back to Tesseract + regex with no errors

When done:
- Check off A4 items in docs/dev/tasks-phased-2.md
- Show example output from a real document to demonstrate quality improvement
```

---

### Prompt A5 — Summary Quality + Real PDF Export

```
You're improving MediKiosk's summary generation quality and replacing the .txt report
with a proper PDF.

Read first:
- docs/dev/tasks-phased-2.md (task A5)
- backend/app/services/summary/llm.py — current LLM summarizer
- backend/app/services/summary/schemas.py — StructuredSummary schema
- backend/app/api/routes/dashboard.py — the report endpoint (currently returns .txt!)

Branch: ws-a/summary-pdf

The current report endpoint (GET /dashboard/patients/{id}/report) returns a plain text
file with a .txt extension. This needs to be a proper PDF that looks like a real
clinical document.

Deliverables:

1. Update the LLM prompt in `llm.py`:
   - When Azure OpenAI is configured, use it (same prompt, Azure client)
   - Improve the prompt: instruct model to write HPI as a 3-4 sentence clinical
     narrative, not bullet points
   - Add `patient_summary` to the output schema: 2 sentences, plain language, in
     Hindi (for the patient-facing VisitDonePage)
   - Add `source` per section: "interview" | "document" | "ai-inferred"

2. Update `StructuredSummary` schema in `schemas.py`:
   - Add `physician_notes: str = ""`
   - Add `patient_summary: str = ""`
   - Add optional `source` field per section

3. Replace the text dump in `dashboard.py` with a REAL PDF:
   - Add `reportlab` to requirements.txt
   - Rewrite `get_report_pdf()` to generate a proper A4 PDF:
     - Header: "MEDIKIOSK — All India Institute of Ayurveda" with a horizontal rule
     - Patient info block: Name, Age, Gender, Date, ABHA ID (if available)
     - Sections with clear headings: Chief Complaint, History of Present Illness,
       Past Medical History, Past Surgical History, Drug History, Allergies,
       Family History, Personal History, Review of Systems, Prior Investigations
     - Abnormal investigation values: text in red
     - Red flags: boxed in a red-bordered rectangle
     - AYUSH assessment section (if applicable)
     - Clinical Impression (clearly marked as "AI-suggested, requires physician verification")
     - Footer: "Report generated by MediKiosk | Physician: [name] | Date: [date]"
     - Signature line: "Physician Signature: _______________"
   - Change the response Content-Disposition to `.pdf`
   - Change media_type to `application/pdf`

4. Add bilingual patient summary endpoint:
   - `GET /summaries/{id}/patient-audio` — generate TTS of `patient_summary` and return audio
   - This is what the VisitDonePage will play for the patient

Verification:
- Generate a summary → HPI reads as a narrative, not a list
- Download the report → it's a real PDF, not .txt
- The PDF looks like a professional clinical document
- `patient_summary` is populated in Hindi
- Patient audio endpoint returns playable audio

When done:
- Check off A5 items in docs/dev/tasks-phased-2.md
- Attach or describe what the PDF looks like
```

---

### Prompt A6 — Real Embeddings

```
You're replacing MediKiosk's fake SHA-256 hash embeddings with real semantic embeddings.

Read first:
- docs/dev/tasks-phased-2.md (task A6)
- docs/dev/tasks-manual.md (P7 — full details)
- backend/app/services/embeddings.py

Branch: ws-a/real-embeddings

Short version: replace `generate_embedding()` with sentence-transformers/all-MiniLM-L6-v2
(384-dim, matches existing vector column). Add EMBEDDING_MODEL env var with `none` fallback
for tests. Also embed interview answers (new migration for interview_answer_embeddings table).

Alternative: if Azure OpenAI is configured, use Azure's text-embedding-3-small model instead
(no local model download needed, lower latency). Add EMBEDDING_PROVIDER env var:
`azure` | `local` (default: azure if configured, else local).

When done:
- Check off A6 in docs/dev/tasks-phased-2.md
- All existing tests pass with EMBEDDING_MODEL=none
```

---

## Workstream B — Frontend

**Who:** Person 2 (frontend-focused)
**Branch prefix:** `ws-b/`

---

### Prompt B1 — Chat-Style Interview UI

```
You're building a ChatGPT-like conversation interface for MediKiosk's patient interview.
This replaces the current form-style Q&A with a natural chat experience.

Read first:
- docs/dev/tasks-phased-2.md (task B1 — full spec)
- docs/project/00-ps-SIH.md — note emphasis on "conversational guidance",
  "zero-training", "elderly, rural, low-literacy"
- frontend/src/pages/InterviewPage.tsx — the CURRENT interview page (you're replacing this)
- frontend/src/api/interview.ts — the API client

Branch: ws-b/chat-interview

PREREQUISITE: ws-a/conversational-interview should ideally be merged first (for the
POST /interview/sessions/{id}/message endpoint). If it's not merged yet, you can
build against a mock API that returns hardcoded responses.

API contract (from Workstream A):
- POST /interview/sessions — returns {session_id, first_message: {reply, reply_hi, ...}}
- POST /interview/sessions/{id}/message — accepts {text, input_mode}, returns:
  {reply, reply_hi, extracted_data, section, red_flag, interview_complete,
   progress_percent, quick_replies}

Deliverables:

1. Create `frontend/src/pages/ChatInterviewPage.tsx`:

   Layout:
   - Full-height page (100vh minus header)
   - Scrollable message area taking up most of the screen
   - Fixed input bar at the bottom

   Message bubbles:
   - AI messages: left-aligned, light gray/blue background, rounded corners,
     small bot/medical icon avatar on the left
   - Patient messages: right-aligned, colored background (blue or teal),
     rounded corners, white text
   - Each AI message fades in with a brief animation

   Input bar (fixed at bottom):
   - Text input field (full width minus buttons)
   - Send button (right side, blue, arrow icon)
   - Mic button (left of send, or as a separate prominent button):
     - Tap once to start recording (shows pulsing red dot)
     - Tap again to stop (easier than hold-to-record for elderly users)
     - After stopping, auto-transcribes and sends as a message
     - Show brief "Transcribing..." state

   Quick replies:
   - When the AI response includes `quick_replies` (e.g., ["sharp", "dull",
     "burning", "pressure"]), show them as tappable chips/buttons below the
     AI message bubble
   - Tapping a chip sends it as a message automatically
   - This gives the patient touch input without it feeling like a form

   Red flag alert:
   - When the AI response includes a `red_flag`, show a full-width red banner
     pinned to the top of the chat (above the messages, below the header)
   - Banner stays visible for the rest of the interview
   - Include the red flag details (symptom, severity)

   Progress:
   - Subtle progress indicator in the header or just below it
   - Shows the current section name and percentage from the AI response

   Typing indicator:
   - While waiting for the AI response, show a "typing..." animation in a
     bubble on the left (like iMessage/WhatsApp typing dots)

   TTS auto-play:
   - When an AI message arrives, auto-play TTS audio of the reply
   - Small speaker icon on each AI bubble to replay
   - Fetch audio from the TTS endpoint with the reply text

   Interview complete:
   - When `interview_complete` is true, show a completion message in the chat
   - Show buttons: "Upload Documents" and "No Documents, Continue"
   - These navigate to /documents/upload or /visit/done

2. Update `frontend/src/api/interview.ts`:
   - Add `sendMessage(sessionId, text, inputMode)` function
   - Add types for the conversation API response

3. Update routing in `App.tsx`:
   - `/interview` → ChatInterviewPage (new)
   - `/interview/legacy` → old InterviewPage (keep as fallback)

4. Keep the General/AYUSH mode selection screen (the pre-interview screen from
   the old InterviewPage) — it starts the session with the right mode, then
   transitions to the chat UI

Design guidelines:
- This is a KIOSK for elderly patients — text should be large (at least text-lg
  for messages, text-xl for AI messages)
- Touch targets minimum 48px
- The chat should feel warm and approachable, not clinical
- The input field should be large and easy to tap
- Colors: use a medical/health-oriented palette (blues, teals, whites)
- DON'T make it look like ChatGPT's exact UI — make it look human-designed
  for a medical context. No dark mode, no sidebar, no markdown rendering in bubbles

Verification:
- Start interview → AI greeting appears as a chat bubble
- Type a message → it appears as a patient bubble, AI responds with a new bubble
- Tap mic → recording starts, tap again → transcribes and sends
- Quick reply chips appear below relevant AI messages
- Red flag triggers → banner appears at top
- Interview completes → navigation buttons appear

When done:
- Check off B1 items in docs/dev/tasks-phased-2.md
- Note any mocked API calls if the backend isn't merged yet
```

---

### Prompt B2 — UI Cleanup

```
You're cleaning up MediKiosk's UI to look professional and human-designed, not
AI-generated. This is NOT a full redesign — just fix the obvious rough edges.

Read first:
- docs/dev/tasks-phased-2.md (task B2)
- frontend/src/pages/ — all page components
- frontend/src/components/ — Header, etc.
- frontend/tailwind.config.js

Branch: ws-b/ui-cleanup

This is about making it look clean, consistent, and intentional. Don't over-invest —
the UI might change later.

Deliverables:
1. Replace "M" placeholder logo with a clean MediKiosk SVG logo (simple medical
   cross or stethoscope icon + "MediKiosk" text)
2. Pick ONE primary color and use it consistently (suggestion: a medical teal/blue
   like #0891B2 or #0284C7). Update tailwind.config.js with a `primary` color
3. Consistent padding: all card-like containers should use p-6, all page containers
   should use px-6 py-8
4. Minimum 48px touch target on ALL buttons, links, interactive elements
5. Consent screen: checkboxes at least 28x28px, speaker buttons clearly styled
6. Document upload: clean drop zone with dashed border, "Take Photo" button using
   <input type="file" accept="image/*" capture="environment">
7. Replace all "Loading…" strings with a simple spinner component
8. No shimmer skeletons, no complex animations — keep it simple

Constraints:
- Don't break existing functionality
- Don't change any i18n strings
- Keep it simple — this takes 1.5 hours, not a day

When done:
- Check off B2 items in docs/dev/tasks-phased-2.md
```

---

### Prompt B3 — Physician Dashboard Improvements

```
You're improving MediKiosk's physician dashboard. Doctors need to view uploaded documents,
see AI summaries, and download proper PDF reports.

Read first:
- docs/dev/tasks-phased-2.md (task B3)
- frontend/src/pages/SummaryReviewPage.tsx — current summary view
- frontend/src/pages/DashboardQueuePage.tsx — current queue
- The dashboard API: GET /dashboard/queue, GET /dashboard/patients/{id}/summary,
  GET /dashboard/patients/{id}/report (now returns PDF, not .txt)
- GET /documents/{id}/analysis (new — returns AI analysis + summary)

Branch: ws-b/doctor-dashboard

PREREQUISITE: ws-a/summary-pdf should ideally be merged (for PDF endpoint + document
analysis endpoint). If not merged, build against the existing API and note what changes.

Deliverables:

1. Document viewer (new component or modal):
   - When doctor clicks on a document in the patient view, open a document detail view
   - Show the original uploaded document image (full size, allow zoom via CSS transform)
   - Below the image: AI-generated summary of the document (large, readable text)
   - Below the summary: list of extracted entities grouped by type:
     - Medications: drug name, dose, frequency in a clean table
     - Investigations: test, value, unit, reference range — abnormal values highlighted
       in red with bold text
     - Diagnoses, Procedures: simple lists
   - Close button to return to patient view

2. Summary review improvements:
   - Each section header (Chief Complaint, HPI, PMH, etc.) should be clickable to
     expand/collapse (or just always visible if it fits)
   - Click any text field to edit it inline (contentEditable or input on click)
   - Add "Physician Notes" section: a textarea at the bottom, bound to the
     physician_notes field
   - "Accept All" button: prominently placed, confirms the summary in one click
   - During summary generation: show a centered spinner with
     "Generating clinical summary..." text

3. PDF download button:
   - Clear button: "📄 Download Report (PDF)"
   - Triggers GET /dashboard/patients/{id}/report
   - The response is now a PDF (application/pdf) — trigger browser download
   - If the backend still returns .txt, show it anyway (backward compatible)

4. Patient detail view layout:
   - Top: patient info card (name, age, gender, language, ABHA if available)
   - Middle: summary card with all sections and edit controls
   - Bottom: "Uploaded Documents" section — list of documents as clickable cards
     showing doc_type, date, and entity count. Click opens the document viewer (item 1)
   - Red flags: if present, show a prominent red banner at the top of the page

Verification:
- Click a document → viewer opens showing image + AI summary + entities
- Abnormal values are clearly highlighted in red
- Summary fields are editable inline
- Download button produces a PDF file
- Physician Notes textarea works

When done:
- Check off B3 items in docs/dev/tasks-phased-2.md
```

---

### Prompt B4+B5 — Patient Summary + Landing Page

```
Two smaller frontend tasks.

Read first:
- docs/dev/tasks-phased-2.md (tasks B4, B5)
- frontend/src/pages/VisitDonePage.tsx
- frontend/src/App.tsx

Branch: ws-b/patient-extras

B4 — VisitDonePage improvements:
1. After physician confirms, fetch the summary and show `patient_summary` in large Hindi text
2. Add a play button that fetches GET /summaries/{id}/patient-audio and plays it
3. Simple layout: centered, large text, "धन्यवाद" (Thank you) heading
4. "Start New Visit" button that clears session and returns to language selection

B5 — Landing page:
5. Simple home page at / — MediKiosk branding, "Start New Visit" button, brief
   instructions in the selected language
6. This is what shows when there's no active session

When done:
- Check off B4, B5 items in docs/dev/tasks-phased-2.md
```

---

## Workstream C — Deployment

**Who:** Person 3 (or shared — most urgent to start)
**Branch prefix:** `ws-c/`

---

### Prompt C1+C2+C3+C5+C6 — Full Cloud Deployment

```
You're deploying MediKiosk to the cloud for the SIH demo. Get it live today.

Read first:
- docs/dev/tasks-phased-2.md (tasks C1, C2, C3, C5, C6)
- docs/guides/deployment.md — existing deployment guide
- infra/docker-compose.yml — current local setup
- backend/.env.example
- backend/app/services/storage.py — storage backend
- backend/app/main.py — CORS config

Branch: ws-c/deploy

Deliverables:

C1 — Supabase:
1. Create Supabase project
2. Enable pgvector extension
3. Create storage bucket `medikiosk-uploads`
4. Implement SupabaseStorageBackend in storage.py if not present (use supabase Python client)
5. Add env vars to .env.example
6. Run alembic upgrade head against Supabase

C2 — Render (Backend):
7. Create Render Web Service
8. Root directory: backend
9. Start command: alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
10. Set env vars: DATABASE_URL (Supabase), JWT_SECRET, SARVAM_API_KEY,
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT,
    AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, AZURE_DOC_INTELLIGENCE_ENDPOINT,
    AZURE_DOC_INTELLIGENCE_KEY, FILE_STORAGE_BACKEND=supabase, SUPABASE_URL,
    SUPABASE_SERVICE_KEY, SUPABASE_BUCKET, ABDM_FHIR_ENDPOINT, PURGE_AFTER_PUSH=true
11. Verify /health and /docs

C3 — Vercel (Frontend):
12. Connect GitHub repo, root dir: frontend
13. Set VITE_API_BASE_URL to Render URL
14. Update CORS in backend
15. Full flow test

C5 — TLS:
16. Render + Vercel auto-HTTPS — verify
17. Set sslmode=require on Supabase connection

C6 — CI/CD:
18. GitHub Actions: on push to main → trigger Render deploy hook
19. Add deploy badge to README

C7 — Azure resources:
20. Create Azure OpenAI resource, deploy gpt-4o model
21. Create Azure Speech Services resource (centralindia region)
22. Create Azure Document Intelligence resource
23. Document all endpoints and keys
24. Rough cost estimate against $4000 budget

When done:
- Check off C1, C2, C3, C5, C6, C7 items in docs/dev/tasks-phased-2.md
- Provide live frontend and backend URLs
- Provide all Azure resource endpoints
```

---

### Prompt C4 — AWS EC2 Alternative

```
Create setup scripts for deploying MediKiosk on a single AWS EC2 instance.

Read first:
- docs/dev/tasks-phased-2.md (task C4)
- docs/guides/deployment.md (Option B)
- infra/docker-compose.yml

Branch: ws-c/ec2

Deliverables:
1. infra/ec2-setup.sh — setup script for Ubuntu 22.04 (Docker, clone, .env, volumes)
2. infra/nginx-ec2.conf — reverse proxy + SSL config
3. infra/certbot-setup.sh — Let's Encrypt setup
4. Document security group rules

When done: check off C4 in docs/dev/tasks-phased-2.md
```

---

## Workstream D — Final Polish

---

### Prompt D1+D2+D3+D4 — Integration & Demo Prep

```
Final integration testing and demo prep on the deployed environment.

Read first:
- docs/dev/tasks-phased-2.md (tasks D1-D4)
- docs/dev/demo-script.md
- docs/project/00-problem-statement.md
- backend/scripts/seed_demo_data.py

Branch: ws-d/final

D1 — E2E test: Full patient journey on deployed stack. Verify conversational interview,
document AI analysis, Azure STT/TTS, summary generation, PDF download.

D2 — Seed data: Run seed_demo_data.py against Supabase. Verify demo login works.

D3 — Pitch alignment: Go through 00-problem-statement.md, mark each capability as
✅ Demoable, ⚠️ Mocked, or ❌ Missing.

D4 — Updated demo script: Rewrite for deployed version. Highlight:
- The conversational interview experience (this is the wow factor)
- Document AI analysis (upload any document and it works)
- Real Hindi STT/TTS via Azure
- Proper PDF clinical report
- Update judges' Q&A section

When done: check off D1-D4, and the Phase 7 pitch deck item in tasks-phased.md
```

---

## Quick Reference — Today's Plan

### Person 1 (Backend) — Start with A1, then A2
1. **A1** — Azure integration layer — 1 hr
2. **A2** — Conversational interview engine — 3-4 hr ⭐ (the biggest task, highest impact)
3. **A3** — Azure Speech STT/TTS — 1.5 hr
4. **A4** — AI document analysis — 2 hr
5. **A5** — Summary + PDF — 2 hr

### Person 2 (Frontend) — Start with B2, then B1
1. **B2** — UI cleanup — 1.5 hr (quick wins first)
2. **B1** — Chat interview UI — 3-4 hr ⭐ (pairs with A2)
3. **B3** — Doctor dashboard — 2 hr

### Person 3 (Deploy) — Start immediately
1. **C1+C2+C3** — Supabase + Render + Vercel — 1.5 hr
2. **C7** — Azure resource provisioning — 30 min
3. **C5+C6** — TLS + CI/CD — 30 min
4. **D2** — Seed data — 15 min

### Everyone (end of day)
1. **D1** — E2E test — 30 min
2. **D3** — Pitch alignment — 30 min
