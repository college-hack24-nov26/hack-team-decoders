# Local Dev Setup

## Prerequisites
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose
- `git`

## Repo layout (target)

```
medikiosk/
├── backend/          # FastAPI app
│   ├── app/
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── frontend/         # React (Vite) app
│   ├── src/
│   └── package.json
├── infra/
│   └── docker-compose.yml
└── docs/             # this folder
```

## First-time setup

```bash
# 1. Clone & enter repo
git clone <repo-url> medikiosk && cd medikiosk

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # fill in secrets/keys
alembic upgrade head              # run migrations once DB is up

# 3. Frontend
cd ../frontend
npm install
cp .env.example .env

# 4. Infra (Postgres + pgvector, Redis if used)
cd ../infra
docker compose up -d
```

## Running it

```bash
# Backend (from backend/, venv active)
uvicorn app.main:app --reload --port 8000

# Frontend (from frontend/)
npm run dev
```

- Backend API docs: `http://localhost:8000/docs` (FastAPI auto Swagger UI)
- Frontend: `http://localhost:5173`

## Environment variables (fill in `.env.example` as these get added)

| Variable | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | backend | Postgres connection string |
| `JWT_SECRET` | backend | session token signing |
| `MAIN_LLM_API_KEY` | backend | Module C "Main API" path |
| `LOCAL_LLM_ENDPOINT` | backend | Module C "Local Offline" path (e.g. Ollama URL) |
| `ASR_API_KEY` / `ASR_ENDPOINT` | backend | Module A voice input |
| `TTS_API_KEY` / `TTS_ENDPOINT` | backend | Module A audio prompts |
| `ABHA_SANDBOX_BASE_URL` | backend | Module D — leave unset to use mock `AuthProvider` |
| `FILE_STORAGE_BUCKET` | backend | document blob storage |

## Common tasks

```bash
# New DB migration after editing models
alembic revision --autogenerate -m "describe change"
alembic upgrade head

# Run backend tests
pytest

# Run frontend tests
npm test

# Lint everything
ruff check backend/ && black --check backend/
npm run lint --prefix frontend
```

## Current environment configuration

The authoritative environment-variable lists are maintained in:
- backend/.env.example
- frontend/.env.example

Use these templates for the current version instead of relying on older
variable names in historical setup notes. Never commit actual .env files.

