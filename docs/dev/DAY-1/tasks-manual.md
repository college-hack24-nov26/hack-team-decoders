# Manual Task Backlog

Tasks added outside the main phased build plan.
Sorted by priority — work top to bottom.
Update status as you go.

Priority key: 🔴 High — directly affects demo quality or patient usability
              🟡 Medium — improves experience, not blocking
              🟢 Low — nice to have, post-demo

---

## Pending

---

### 🔴 P1 — Sarvam TTS for the Consent Screen

**Priority reasoning:** Consent is the first thing a patient interacts with after
logging in. It is also the screen where audio matters most — a patient who cannot
read Hindi needs to *hear* what they are agreeing to. The current browser
`SpeechSynthesis` API sounds robotic, fails silently on many Android/kiosk
browsers, and is inconsistent across devices. This is a demo-visible gap.

**What:** Replace `window.speechSynthesis` on the consent screen with the same
Sarvam TTS already wired up for the interview.

**Where to look:**
- `frontend/src/pages/ConsentPage.tsx` — the `speak()` function
- `backend/app/api/routes/interview.py` — the `/interview/audio/{filename}` endpoint
  (reuse this pattern for consent)

**Rough steps:**
1. Add `POST /api/v1/consent/audio` — accepts `{text, language}`, calls `tts.synthesize()`,
   returns the audio file (same pattern as the interview audio endpoint)
2. In `ConsentPage.tsx`, replace `speak()`: call the new endpoint, play the returned
   blob via `<audio>` instead of `SpeechSynthesis`
3. Show a spinner on the play button while the clip is being fetched
4. Test in English and Hindi

---

### 🔴 P2 — Better UI

**Priority reasoning:** This is a kiosk for elderly, low-literacy patients.
The current UI is functional but looks and feels like a developer prototype —
small touch targets, cramped cards, no visual warmth. Judges will notice this
immediately. A polished UI signals that the team understood the problem.

**What:** UI polish pass across all screens.

**Checklist:**
- [ ] Replace the "M" placeholder logo with a real logo/icon
- [ ] Interview: larger question text (at least `text-2xl`), more padding between
      answer option buttons, minimum touch target 60×60px
- [ ] Progress bar: show the current section name ("Chief Complaint", "Family History")
      not just a percentage number
- [ ] Red flag alert: full-width banner pinned to the top of the screen, not a small card
- [ ] Consent: more padding inside section cards, larger checkbox (at least 32×32px)
- [ ] Document upload: full-width drop zone, add a "Take Photo" button for
      mobile/tablet (`<input type="file" accept="image/*" capture="environment">`)
- [ ] Document timeline: vertical timeline rail (line + circular nodes) instead of
      flat card list
- [ ] Replace all "Loading…" text with a shimmer skeleton
- [ ] High-contrast mode toggle in the header
- [ ] Audit every button/link: minimum `min-h-[3rem]` touch target

**Where to look:**
- `frontend/src/pages/` — all page components
- `frontend/src/components/` — Header, LanguageSwitcher
- `frontend/tailwind.config.js` — add shared design tokens here

---

### 🔴 P3 — Conversational Interview Questions

**Priority reasoning:** The fixed-form Q&A style is the biggest gap between
what the problem statement asks for ("adaptive AI interview") and what is built.
Judges will go through the interview themselves. Questions like
"What is the onset of your symptom?" feel clinical and alienating —
the opposite of what an elderly rural patient needs.

**What:** Make questions feel like a conversation. Each question should
acknowledge the previous answer before asking the next one.
e.g. "I see, your chest pain started 2 days ago. Does it spread to your arm or jaw?"

**Where to look:**
- `backend/app/interview/templates.py` — fixed question templates
- `backend/app/interview/dialogue.py` — dialogue state machine
- `backend/app/interview/ontology.py` — question field definitions

**Rough steps:**
1. Add a `context_line` field to the question response schema — a one-sentence
   acknowledgement of the previous answer
2. Option A (do this first — no LLM needed): write acknowledgement templates in
   `templates.py` that reference `{previous_answer}`:
   `"I see, {previous_answer}. Now — {next_question}"`
3. Option B (better, do after A works): replace the template with a single LLM call
   that generates the bridge sentence. Gate behind `CONVERSATIONAL_MODE=true` env var
   so it degrades gracefully if the LLM is unavailable
4. In `InterviewPage.tsx`, render `context_line` in muted text above the question prompt

---

### 🟡 P4 — Sarvam AI STT (Speech-to-Text)

**Priority reasoning:** Voice input works today via local Whisper, which is good
enough for the demo. Sarvam STT would give better Hindi/regional-accent accuracy,
but the improvement is incremental and the integration is non-trivial (new provider,
new auth, testing with real Hindi audio). Do this after the higher-priority items are
stable.

**What:** Add Sarvam as an ASR provider option alongside Whisper.

**Where to look:**
- `backend/app/interview/asr.py` — add `transcribe_audio_sarvam()` here
- Sarvam STT API docs: https://docs.sarvam.ai/api-reference-docs/endpoints/speech-to-text

**Rough steps:**
1. Add `ASR_PROVIDER` env var: `whisper` (default) | `sarvam` | `mock`
2. Implement `transcribe_audio_sarvam()` — POST audio to Sarvam's `/speech-to-text`
   using the `SARVAM_API_KEY` already set for TTS
3. Update `transcribe_audio()` to dispatch on `ASR_PROVIDER`
4. Test with a Hindi voice clip — compare output to Whisper on the same clip

---

### 🔴 P5 — TTS and STT language must follow the UI language switcher

**Priority reasoning:** A patient switches to Hindi in the header — but the voice
prompts keep speaking in English and the mic transcribes as English. This breaks
the entire point of the language switcher and is immediately visible during a demo.
It also directly violates the problem statement requirement for multilingual support.

**What:** Both TTS (spoken question prompts) and STT (mic transcription) must use
whichever language the patient has selected in the UI, not a hardcoded default.

**Current behaviour:**
- TTS: `tts.synthesize(text, language)` is called with the language, but it needs
  to be verified that the language code passed is actually the live `i18n.language`
  value at the time of the request, not a stale default
- STT: `transcribeAudio(audioBlob, lang)` in `InterviewPage.tsx` passes `lang` —
  check whether Sarvam's `/speech-to-text` endpoint uses this hint correctly, and
  whether the Whisper path passes it through too

**Where to look:**
- `frontend/src/pages/InterviewPage.tsx` — `lang` is derived from `i18n.language`,
  passed to `transcribeAudio()` and used when fetching audio clips. Verify it updates
  when the language switcher is toggled mid-session
- `backend/app/interview/asr.py` — confirm `language` param is forwarded to both
  the Whisper API call and (once implemented) the Sarvam STT call
- `backend/app/interview/tts.py` — confirm `_bcp47(language)` is called with the
  patient's actual language, not a hardcoded `"en"`
- `backend/app/api/routes/interview.py` — the `/next-question` endpoint synthesises
  TTS when returning a question; confirm it reads language from the session or the
  request header, not a default

**Rough steps:**
1. In `InterviewPage.tsx`, confirm `lang` is read from `i18n.language` reactively
   (it already uses `const lang = i18n.language as "en" | "hi"` — verify this
   re-renders when the switcher changes)
2. In the backend `next-question` endpoint, accept a `?lang=hi` query param or
   read `Accept-Language` header, pass it to `tts.synthesize()`
3. In `asr.py`, ensure the `language` param is forwarded in both Whisper and
   Sarvam paths (Sarvam uses `target_language_code` in TTS but `language` in STT —
   check their STT API docs for the exact field name)
4. Test: switch to Hindi mid-interview, ask the next question — prompt should be
   in Hindi, mic should transcribe Hindi

---

### 🟡 P6 — OCR should support multiple languages

**Priority reasoning:** Indian OPD documents are frequently bilingual
(English drug names + Hindi instructions, or fully Hindi prescriptions).
Tesseract already supports Hindi (`lang="eng+hin"`) but the current code
does not expose this to the user and Google Vision may not be sending the
correct language hints for all document types.

**What:** OCR should detect and extract text in both English and Hindi
(and ideally other regional scripts) regardless of which language the patient
has set in the UI — documents can be in any language.

**Current behaviour:**
- Tesseract: already uses `lang="eng+hin"` — this is correct but untested with
  fully Hindi documents
- Google Vision: sends `languageHints: ["en", "hi"]` — also correct, but only
  two languages are hinted; other regional scripts (Tamil, Telugu, Bengali etc.)
  are not included

**Where to look:**
- `backend/app/services/ocr.py`
  - `TesseractOcrEngine.extract_text()` — the `lang=` param
  - `GoogleVisionOcrEngine._extract_via_api_key()` — the `languageHints` list

**Rough steps:**
1. Tesseract: install additional language packs in the Dockerfile and expand the
   `lang` string. Add `tesseract-ocr-tam`, `tesseract-ocr-tel`, `tesseract-ocr-ben`
   to the `apt-get install` line. Change `lang="eng+hin"` to
   `lang="eng+hin+tam+tel+ben"` (Tesseract ignores packs it doesn't recognise,
   so adding extras is safe)
2. Google Vision: expand `languageHints` to include common Indian script codes:
   `["en", "hi", "ta", "te", "bn", "mr", "gu", "kn", "ml", "pa"]`
3. Add an optional `TESSERACT_LANGS` env var so the language list can be
   configured without rebuilding the image
4. Test with a Hindi prescription and a bilingual lab report

---

### 🟡 P7 — Replace fake embeddings with a real model + embed interview answers

**Priority reasoning:** The vector DB plumbing is complete but the embeddings are
SHA-256 hashes, not semantic vectors. This means cosine similarity queries return
garbage — two documents about the same condition would not rank as similar.
Not blocking for the demo, but must be done before Phase 4 (LLM summarizer)
because the summarizer's context retrieval depends on these vectors being real.

**Current state:**
- `backend/app/services/embeddings.py` → `generate_embedding()` is a fake
  deterministic hash. The file has a comment saying exactly this.
- Document OCR text is embedded and stored in `document_embeddings` (pgvector
  `vector(384)`) — but with the fake vectors
- Interview answers are stored in `interview_answers` as plain JSON — **not
  embedded at all**, so there is no way to retrieve relevant Q&A by similarity

**What:**
1. Swap `generate_embedding()` for a real local model (no API needed)
2. Embed interview answers into pgvector too, so the Phase 4 summarizer can
   retrieve relevant Q&A context alongside document context

**Recommended model:** `sentence-transformers/all-MiniLM-L6-v2`
- Dim: 384 — matches the existing `vector(384)` column, **no migration needed** for documents
- Size: ~90 MB, runs on CPU in ~5 ms per sentence
- License: Apache 2.0, no usage restrictions

**Where to look:**
- `backend/app/services/embeddings.py` — replace `generate_embedding()` here
- `backend/app/api/routes/documents.py` — calls `generate_embedding(ocr_text)` on upload
- `backend/app/api/routes/interview.py` — submit_answer endpoint, after saving the answer
- `backend/alembic/versions/` — new migration for `interview_answer_embeddings` table

**Rough steps:**
1. Add `sentence-transformers` to `backend/requirements.txt`
2. In `embeddings.py`, load the model once at module level:
   `_model = SentenceTransformer("all-MiniLM-L6-v2")`
   Replace `generate_embedding(text)` with `_model.encode(text).tolist()`
3. Add `EMBEDDING_MODEL` env var (default `all-MiniLM-L6-v2`). When set to
   `none`, fall back to the hash — useful in unit tests that don't want to load
   a 90 MB model
4. Create migration `0003_interview_answer_embeddings` — same shape as
   `document_embeddings` but keyed by `session_id + field_id` instead of
   `document_id`
5. In `routes/interview.py` submit_answer, after `db.commit()`, call
   `generate_embedding(str(answer.value))` and insert a row into the new table
6. Test: upload a CBC report and a prescription, run a cosine similarity query
   in psql — the CBC should rank closer to another CBC than to the prescription:
   ```sql
   SELECT document_id, embedding <-> (SELECT embedding FROM document_embeddings LIMIT 1) AS dist
   FROM document_embeddings ORDER BY dist LIMIT 5;
   ```

---

### 🔴 P8 — Fix OCR document scanning + AI-generated report summaries

**Priority reasoning:** Document scanning is a core demo feature and it's
currently unreliable. The entity extraction is rules/regex only — it breaks on
any document layout it hasn't seen before. Judges will upload real documents.
This needs to work.

**What's broken right now:**

1. **Tesseract OCR quality** — `--psm 6` (single uniform block) is wrong for
   most real documents which have headers, tables, and columns. Lab reports
   especially are multi-column tables that Tesseract mangles with this setting.

2. **Entity extraction is regex-only** — `_extract_medications()`,
   `_extract_investigations()`, `_extract_diagnoses()` are pure regex. They work
   on the exact formats they were written for (and only those). Any variation in
   layout — different hospital header, handwritten additions, Tamil/Telugu labels,
   different column spacing — and extraction silently returns nothing.

3. **No AI summary of the document** — after OCR, the patient and physician get
   a raw list of extracted entities. There's no human-readable "what does this
   report say" summary. This is a big gap for the patient-facing experience.

4. **Document type detection is too narrow** — only detects `lab_report`,
   `prescription`, `discharge_summary`. Radiology reports, ECGs, vaccination
   records, insurance documents all fall through to `"unknown"`.

**What to build:**

**Fix 1 — Better Tesseract config per document type**
- Use `--psm 3` (fully automatic page segmentation) instead of `--psm 6`
  as the default — handles mixed layouts much better
- For lab reports specifically, use `--psm 6` on each table cell after
  detecting table structure, not on the whole image
- Pre-process images before OCR: convert to greyscale, increase contrast,
  deskew — use `Pillow` (already available) for this
- File: `backend/app/services/ocr.py` → add `_preprocess_image()` helper

**Fix 2 — LLM-assisted entity extraction fallback**
The code has a comment "LLM-assisted fallback" but it's not implemented.
Build it now:
- After the regex pass, if fewer than 2 entities were found, call the LLM
  with the OCR text and a structured prompt asking it to extract entities
  in a fixed JSON schema
- Prompt schema:
  ```json
  {
    "doc_type": "lab_report | prescription | discharge_summary | radiology | vaccination | other",
    "diagnoses": [{"diagnosis": "..."}],
    "medications": [{"drug": "...", "dose": "...", "frequency": "..."}],
    "investigations": [{"test": "...", "value": 0.0, "unit": "...", "reference_range": "..."}],
    "procedures": [{"procedure": "..."}],
    "document_date": "YYYY-MM-DD or null"
  }
  ```
- Gate behind `DOCUMENT_AI_EXTRACTION=true` env var — off by default so it
  doesn't make unexpected LLM calls
- File: `backend/app/services/entity_extraction.py` → add
  `_llm_extraction_fallback(text)` and call it from `extract_entities()`

**Fix 3 — AI document summary**
After extraction, generate a 2–3 sentence plain-language summary of what the
document says, in the patient's language (English or Hindi):
- Example: *"This is a blood test report from 15 Aug 2024. Your haemoglobin
  is slightly low at 10.2 g/dL (normal: 12–16). Everything else is within
  normal range."*
- Add a `summary` field to `ExtractionResult` and populate it via LLM call
- Add `document_summary` to the `DocumentDetailResponse` API schema so the
  frontend can display it
- Gate behind the same `DOCUMENT_AI_EXTRACTION=true` flag
- File: `backend/app/services/entity_extraction.py` + `backend/app/api/routes/documents.py`

**Fix 4 — Expand document type detection**
Add to `_infer_doc_type()`:
- `radiology` — X-ray, MRI, CT, ultrasound reports
- `ecg` — ECG/EKG reports
- `vaccination` — vaccination cards/records
- `insurance` — insurance documents
- `opd_slip` — OPD registration / referral slips

**Frontend:**
- Show the AI summary prominently at the top of the document detail view,
  above the entity list
- Show a "Processing…" state while extraction runs (it can take a few seconds
  with LLM fallback)
- For each extracted entity, show a confidence indicator if the LLM provided
  it (high/medium/low)

**Where to look:**
- `backend/app/services/ocr.py` — Tesseract config, add image preprocessing
- `backend/app/services/entity_extraction.py` — LLM fallback, AI summary,
  expanded doc type detection
- `backend/app/api/routes/documents.py` — add `summary` to response schema
- `frontend/src/pages/DocumentUploadPage.tsx` — show processing state
- `frontend/src/pages/DocumentTimelinePage.tsx` — show AI summary per document

**Env vars to add to `.env.example`:**
```env
DOCUMENT_AI_EXTRACTION=false   # set true to enable LLM entity extraction + summaries
```

---

### 🔴 P9 — Improve physician report generation and summary quality

**Priority reasoning:** The physician summary is the final output of the entire
kiosk — everything the patient does feeds into it. Right now the summary review
page shows a basic structured dump. For a demo to judges and for real clinical
use, it needs to look and feel like a proper medical document that a physician
would actually use.

**What's missing:**

1. **Summary quality** — The deterministic fallback (which runs when no LLM is
   configured) just reformats interview answers as key-value pairs. Even with
   an LLM, the prompt doesn't produce a proper clinical narrative. The HPI
   should read like a doctor wrote it, not like a form was flattened.

2. **PDF export is basic** — `GET /dashboard/patients/{id}/report` exists but
   the PDF output needs to look like a real clinical document:
   - Hospital header (AIIA logo/name)
   - Patient demographics block
   - Clearly sectioned: Chief Complaint → HPI → PMH → Medications → Investigations
   - Abnormal values highlighted in red
   - Red flag alerts prominently boxed
   - Doctor's name, designation, date, and signature line at the bottom

3. **Summary review UI needs work** — `SummaryReviewPage.tsx` shows the summary
   but the edit experience is poor. Physicians need to be able to:
   - Edit any field inline with a single click (not a separate edit mode)
   - See which fields came from the interview vs. from documents vs. were
     LLM-inferred — so they know what to trust
   - See the source document/answer that each entity came from (traceability)
   - Add free-text clinical notes in a dedicated "Physician Notes" section
   - One-click "Accept all" for when the summary looks correct

4. **Bilingual summary** — The physician gets English. The patient should get a
   simple Hindi summary of their visit ("आपको बुखार है, डॉक्टर ने 3 दिन की दवाई
   दी है") — not the full clinical summary, just a plain-language takeaway.
   Display this on the `VisitDonePage.tsx` after the physician confirms.

5. **Summary generation is slow** — LLM call is synchronous on the Generate
   button click. If it takes 10–15 seconds, the UI just shows nothing. Add a
   proper loading state with a progress indicator and estimated wait time.

**Where to look:**
- `backend/app/services/summary/llm.py` — improve the prompt, add source
  attribution to each field in the structured output
- `backend/app/services/summary/schemas.py` — add `source` field per section,
  add `physician_notes` field, add `patient_summary_hi` field
- `backend/app/api/routes/dashboard.py` — the PDF generation endpoint
- `frontend/src/pages/SummaryReviewPage.tsx` — inline editing, source hints,
  loading state
- `frontend/src/pages/VisitDonePage.tsx` — show patient-facing Hindi summary

**Rough steps:**
1. Improve the LLM prompt in `llm.py` — add explicit instruction to write the
   HPI as a 3–4 sentence clinical narrative, not bullet points. Add a
   `patient_summary` field to the output schema (2 sentences, plain language,
   in Hindi)
2. Add `physician_notes: str = ""` to `StructuredSummary` schema — editable
   free-text field for the physician
3. In `SummaryReviewPage.tsx`, make every field click-to-edit inline. Add a
   "Source: Interview / Document / AI-inferred" badge per section
4. Improve PDF: use `reportlab` or `weasyprint` in the backend to produce a
   properly formatted A4 document with the AIIA header
5. In `VisitDonePage.tsx`, fetch the confirmed summary and show the
   `patient_summary` field in Hindi
6. Add a loading skeleton with "Generating summary… (~10 seconds)" on the
   Generate button click

---

## Done

_(move items here as they are completed)_
