# Tech Stack

Concrete choices for the hackathon build. Anywhere marked "MVP" is what to actually build now;
"Post-hackathon" is the real-world upgrade path worth mentioning in the pitch/demo narrative.

## Backend

- **Language/framework:** Python, **FastAPI** (async, fast to build REST + websocket endpoints,
  auto OpenAPI docs which is handy for judges)
- **ORM:** SQLAlchemy 2.x + Alembic for migrations
- **Task queue (for OCR/AI jobs that shouldn't block requests):** Celery + Redis, or
  FastAPI `BackgroundTasks` for MVP if queueing feels like overkill for the demo
- **Validation:** Pydantic v2 (comes with FastAPI)
- **Auth:** JWT sessions; ABHA OAuth2 flow abstracted behind an `AuthProvider` interface so it
  can be mocked/sandboxed for the demo and swapped for the real ABDM sandbox later

## Frontend

- **Framework:** React (Vite + TypeScript)
- **Styling:** Tailwind CSS (fast to build accessible, large-touch-target kiosk UI)
- **State:** React Query for server state, lightweight context/Zustand for UI state
- **i18n:** `react-i18next` — start with English + Hindi, structure so more languages are just
  new translation files
- **Voice UI:** Web Audio API / `MediaRecorder` for capture; playback via `<audio>` for TTS prompts
- **Accessibility:** large icon-driven components, high contrast mode, minimum-training UX —
  this is a stated hard requirement in the PS, not a nice-to-have

## Database & retrieval

- **Primary DB:** PostgreSQL 15+ with the **pgvector** extension
- **Retrieval/orchestration:** LangChain, with Chroma as the vector store if kept separate from
  pgvector (see open decision in `01-architecture.md`)
- **File storage:** local disk / MinIO (S3-compatible) for uploaded document images — don't put
  binary blobs in Postgres

## AI / ML components

| Need | MVP (demo-ready) | Post-hackathon (production) |
|---|---|---|
| ASR (speech-to-text) | Whisper (open-source) via API, or hosted STT | AI4Bharat / Bhashini models for Indian languages/accents |
| TTS (audio prompts) | Any open TTS (e.g., Coqui) or cloud TTS | Bhashini TTS for regional-language parity |
| OCR | Tesseract (printed text) | AI4Bharat OCR / cloud OCR with handwriting support |
| Summarizer / dialogue LLM | Hosted LLM API (the "Main API" path) | Same, + a fine-tuned or smaller **local model via Ollama** as the offline fallback |
| Entity extraction (meds, diagnoses, lab values) | Rules/regex + LLM-assisted extraction | Fine-tuned medical NER model |

## Infra / DevOps

- **Local dev:** Docker Compose (Postgres+pgvector, Redis if used, backend, frontend)
- **CI:** GitHub Actions — lint + test on push
- **Env/secrets:** `.env` files locally (never committed), documented in `07-setup.md`

## Linting/formatting

- Python: `ruff` (lint) + `black` (format)
- TypeScript/React: `eslint` + `prettier`

## Why these choices

FastAPI + React is a stack the whole team can move fast in during a hackathon, has huge
community support for anything unusual you hit at 2am, and both have first-class Docker
support so the judges can run it with one command. pgvector avoids standing up a whole separate
vector DB unless volume actually demands it.
