# MediKiosk




AI-powered, multilingual, voice+touch patient history-taking kiosk for AYUSH/allopathic OPDs.
Patients complete a structured health history *before* reaching the doctor — in their own
language, by voice or touch — freeing the consultation window for examination and reasoning.


---

## What's built

| Phase | What | Status |
|---|---|---|
| 0 — Scaffold | Monorepo, FastAPI skeleton, DB migrations, Docker Compose, CI | ✅ Done |
| 1 — Identify | Login, ABHA lookup, language select, consent with audio, JWT auth | ✅ Done |
| 2 — Converse | Interview engine, ontology, dialogue state machine, ASR, TTS, red-flag detection | ✅ Done |
| 3 — Scan | Document upload, OCR, entity extraction, reference ranges, document timeline | ✅ Done |
| 4 - Summarize | Summary generation, editing, confirmation and FHIR workflow | Implemented in code; live integrations require configuration |
| 5 - Consult | Physician dashboard, queue and PDF reporting | Implemented in code; deployment verification pending |

---

## Quick start (Docker — recommended)

The fastest way to run everything:

```bash
cd infra
cp ../backend/.env.example ../backend/.env   # fill in secrets if needed
docker compose up -d --build
```

- Frontend: <http://localhost:3000>
- Backend API + Swagger: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

After any change to `backend/.env`:
```bash
docker compose up -d --no-build backend
```

For active frontend work, keep the static nginx bundle in sync automatically:
```bash
docker compose up --build --watch
```

See [`docs/guides/setup.md`](./docs/guides/setup.md) for the full local dev setup
(without Docker) and platform-specific notes.

---

## AI services

By default the app runs with mock STT and no TTS (works offline, good for development).
To enable real voice features set these in `backend/.env`:

```env
# Text-to-speech
TTS_PROVIDER=sarvam
SARVAM_API_KEY=your_key_here

# Speech-to-text (pick one)
ASR_PROVIDER=sarvam       # recommended — better Hindi/accent support
# ASR_PROVIDER=whisper    # local fallback, needs whisper_server.py running

# OCR (tesseract is default, no key needed)
OCR_ENGINE=tesseract
```

See [`docs/guides/ai-services-setup.md`](./docs/guides/ai-services-setup.md) for
detailed setup including the local Whisper server.

---

## Repo layout

```
Medi-Kiosk/
├── backend/            FastAPI app
│   ├── app/
│   │   ├── api/routes/ Endpoints (auth, consent, interview, documents)
│   │   ├── interview/  Interview engine — ontology, dialogue, ASR, TTS, red-flags
│   │   ├── services/   OCR, embeddings, entity extraction, storage, audit
│   │   ├── models/     SQLAlchemy ORM models
│   │   └── core/       Config (Pydantic Settings)
│   ├── alembic/        DB migrations
│   └── tests/          pytest tests
├── frontend/           React + Vite + TypeScript
│   └── src/
│       ├── pages/      LoginPage, ConsentPage, InterviewPage, DocumentUploadPage, …
│       ├── components/ Header, LanguageSwitcher
│       └── locales/    en/, hi/ translation JSON
├── infra/              docker-compose.yml, pgvector init SQL
├── whisper_server.py   Local Whisper ASR server (optional, port 8765)
└── docs/               All documentation
    ├── project/        Problem statement, architecture, tech stack
    ├── design/         Data model, API spec, module specs, glossary
    ├── guides/         Setup, AI services, deployment
    └── dev/            Task tracking, build notes
```

---

## Useful commands

```bash
# --- Backend ---
cd backend
source .venv/bin/activate

alembic upgrade head                            # run migrations
alembic revision --autogenerate -m "change"    # new migration
uvicorn app.main:app --reload --port 8000       # dev server

ruff check . && black --check .                 # lint + format check
pytest                                          # tests

# --- Frontend ---
cd frontend
npm run dev                                     # dev server (localhost:5173)
npm run lint                                    # eslint
npm test                                        # vitest

# --- Docker ---
cd infra
docker compose up -d                            # start everything
docker compose logs -f backend                  # live backend logs
docker compose exec backend env | grep TTS      # verify env vars
docker compose down                             # stop everything
```

---

## Deployment

See [`docs/guides/deployment.md`](./docs/guides/deployment.md) for full options.

**Quick options:**
- **Free** — Vercel (frontend) + Railway (backend) + Supabase (Postgres + pgvector)
- **Self-hosted** — single EC2 `t3.large` (~$62/month), all services in Docker

