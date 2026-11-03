# Work Plan — 2 People, Same Day

Two people. No conflicts. This is the order.

---

## Setup (both, 5 min)

```bash
# Both people create their branches off main
git checkout main && git pull

# Person 1 (Aarsh)
git checkout -b ws-a/azure-and-conversation

# Person 2 (Friend)
git checkout -b ws-b/speech-docs-ui
```

---

## Phase 1 — Foundation (sequential, ~1 hr)

**Person 1 does A1 first. Person 2 waits (or starts B2).**

A1 is the Azure SDK setup — both people's work depends on it.

| Time | Person 1  | Person 2  |
|------|-----------------|-------------------|
| 0:00 | **A1** — Azure integration layer | **B2** — UI cleanup (no backend dependency) |
| 1:00 | ✅ Push A1, notify Person 2 | ✅ Push B2 |

```bash
# Person 1: when A1 is done
git add -A && git commit -m "feat: Azure AI integration layer"
git push origin ws-a/azure-and-conversation

# Person 2: pull A1 into their branch
git fetch origin
git merge origin/ws-a/azure-and-conversation
```

---

## Phase 2 — Parallel work (the big chunk, ~5-6 hr)

After A1 is merged, both people work **completely independently** — no conflicts
because they touch different files.

| Person 1  | Person 2  |
|---|---|
| **Files you own:** | **Files you own:** |
| `backend/app/interview/conversation.py` (NEW) | `backend/app/interview/asr.py` |
| `backend/app/api/routes/interview.py` | `backend/app/interview/tts.py` |
| `backend/app/services/summary/llm.py` | `backend/app/services/document_ai.py` (NEW) |
| `backend/app/services/summary/schemas.py` | `backend/app/services/ocr.py` |
| `backend/app/api/routes/dashboard.py` | `backend/app/services/entity_extraction.py` |
| | `backend/app/api/routes/documents.py` |
| | `frontend/src/` (all frontend files) |

### Person 1's sequence

| # | Prompt | What | Time | Key files |
|---|--------|------|------|-----------|
| 1 | **A2 ** | Conversational interview engine | 3-4 hr | `conversation.py` (new), `routes/interview.py`, new migration |
| 2 | **A5** | Summary quality + real PDF export | 2 hr | `summary/llm.py`, `summary/schemas.py`, `routes/dashboard.py` |
| 3 | **A6** | Real embeddings (if time) | 1 hr | `services/embeddings.py` |

### Person 2's sequence

| # | Prompt | What | Time | Key files |
|---|--------|------|------|-----------|
| 2 | **A4** | AI document analysis | 2 hr | `document_ai.py` (new), `routes/documents.py`, `entity_extraction.py` |
| 4 | **B3** | Doctor dashboard + doc viewer | 2 hr | `SummaryReviewPage.tsx`, `DashboardQueuePage.tsx` |

> **Why no conflicts?** Person 1 touches the interview *backend* (conversation engine,
> routes/interview.py) and summary/dashboard *backend*. Person 2 touches STT/TTS
> providers, document pipeline, and ALL frontend files. The only shared file is
> `routes/interview.py` — Person 1 adds the `/message` endpoint, Person 2 doesn't
> touch it.

---

## Phase 3 — Merge & integrate (~30 min)

Both people merge to main.

```bash
# Person 1
git checkout main && git pull
git merge ws-a/azure-and-conversation
git push

# Person 2 (after Person 1's merge)
git checkout main && git pull
git merge ws-b/speech-docs-ui
# Resolve any conflicts (should be minimal — different files)
git push
```

---

## Phase 4 — Deploy (either person, ~1.5 hr)

Now that everything is on main, deploy.

| # | Prompt | What | Time |
|---|--------|------|------|
| 1 | **C1+C2+C3** | Supabase + Render + Vercel | 1 hr |
| 2 | **C7** | Provision Azure resources, set keys | 30 min |
| 3 | **C5+C6** | Verify HTTPS, add CI/CD | 15 min |
| 4 | **D2** | Seed demo data on deployed env | 15 min |

---

## Phase 5 — Final tasks (both, ~1.5 hr)

| Person 1 | Person 2 |
|---|---|
| **D1** — E2E test on deployed env (30 min) | **B4** — Patient VisitDone page (30 min) |
| **D3** — Pitch deck cross-reference (30 min) | **Marathi support** (see below, 1 hr) |
| **D4** — Update demo script (30 min) | |

---

## Marathi Language Support (Person 2, last task)

```
You're adding Marathi (mr) as a third language to MediKiosk, alongside English and Hindi.

Read first:
- frontend/src/i18n.ts — i18n configuration
- frontend/src/locales/ — en.json and hi.json translation files
- backend/app/interview/conversation.py — the conversational AI system prompt
- backend/app/interview/tts.py — TTS language mapping
- backend/app/interview/asr.py — STT language mapping

Branch: ws-b/marathi

Deliverables:

Frontend:
1. Create `frontend/src/locales/mr.json` — copy hi.json and translate all strings
   to Marathi. Key strings to translate:
   - All page titles, button labels, consent text, interview UI text
   - Error messages, loading states
   - Use proper Devanagari script (Marathi uses the same script as Hindi)
2. Update `frontend/src/i18n.ts` — add "mr" to the language list and import mr.json
3. Update the LanguageSelectPage — add a third button: "मराठी" with the Maharashtra
   flag or a suitable icon
4. Ensure the language switcher in the header includes Marathi

Backend:
5. Update the conversational interview system prompt to support Marathi:
   - When patient language is "mr", the AI should respond in Marathi
   - Add reply_mr to the conversation response schema
   - The AI should use medical terms that a Marathi-speaking patient would understand
6. Update TTS mapping: add `mr-IN` locale
   - Azure Speech: use `mr-IN-AarohiNeural` (Marathi neural voice)
   - Sarvam: check if Marathi is supported, fall back to Hindi if not
7. Update STT mapping: add `mr-IN` locale for Azure Speech recognition
8. Update consent audio endpoint to handle language="mr"
9. Update document AI prompt to include Marathi in the summary languages:
   - Add `summary_mr` field to ExtractionResult
   - When patient language is Marathi, generate summary in Marathi too
10. Add "mr" to the GET /languages endpoint response

Verification:
- Select मराठी on the language screen → entire UI switches to Marathi
- Start a conversation → AI greets in Marathi
- TTS plays Marathi audio
- STT transcribes Marathi speech
- Document summary includes Marathi version when patient language is "mr"
- Consent audio plays in Marathi

When done:
- Note that Marathi uses the same Devanagari script as Hindi, so no font changes needed
- Note any strings where you used machine translation and might need human review
```

---

## Timing overview

```
Hour 0     1     2     3     4     5     6     7     8     9     10
 │     │     │     │     │     │     │     │     │     │     │
 ├─A1──┤                                                        Person 1
 │     ├───────A2 (conversation)──────────┼────A5 (PDF)───┤
 │     │                                  │               │
 ├─B2──┤                                                        Person 2
 │     ├──A3──┼────A4 (doc AI)────┼────B1 (chat UI)───────┼─B3─┤
 │     │      │                   │                       │    │
 │                                                             │
 │     ├──────────────────── can work in parallel ─────────────┤
 │                                                             │
 │                                                        ├─Deploy──┼─Test─┼─Marathi─┤
 └─────────────────────────────────────────────────────────────────────────────────────┘
```

## Rules to avoid conflicts

1. **Don't edit each other's files** — file ownership is listed in Phase 2
2. **Person 2: don't touch `routes/interview.py`** — Person 1 owns it
3. **Person 1: don't touch any `frontend/src/` files** — Person 2 owns them
4. **Both: don't edit `models/models.py` at the same time** — Person 1 adds
   `InterviewMessage` model first, Person 2 adds any document-related model
   changes after merging Person 1's work
5. **Alembic migrations**: Person 1 creates the `interview_messages` migration.
   Person 2 avoids creating migrations until after merge (or uses a different
   revision ID)
6. **Deploy only after both branches are merged to main**
