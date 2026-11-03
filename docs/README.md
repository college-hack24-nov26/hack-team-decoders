# MediKiosk — Docs

```
docs/
├── project/       What the product is and why
├── design/        How it is built (data model, API, modules)
├── guides/        How to run, deploy, and configure AI services
└── dev/           Task tracking and build notes
```

---

## Project

| File | Description |
|---|---|
| [project/00-problem-statement.md](project/00-problem-statement.md) | Problem statement summary |
| [project/00-ps-SIH.md](project/00-ps-SIH.md) | Full SIH 2026 PS-26047 problem statement |
| [project/01-architecture.md](project/01-architecture.md) | System architecture overview |
| [project/02-tech-stack.md](project/02-tech-stack.md) | Tech stack decisions and rationale |

## Design

| File | Description |
|---|---|
| [design/03-data-model.md](design/03-data-model.md) | Database schema and ORM models |
| [design/04-api-spec.md](design/04-api-spec.md) | API endpoint reference |
| [design/08-glossary.md](design/08-glossary.md) | Domain terminology |
| [design/modules/module-a-interview-engine.md](design/modules/module-a-interview-engine.md) | Module A — Interview engine |
| [design/modules/module-b-document-digitization.md](design/modules/module-b-document-digitization.md) | Module B — Document digitization |
| [design/modules/module-c-summary-generator.md](design/modules/module-c-summary-generator.md) | Module C — Summary generator |
| [design/modules/module-d-consent-privacy-abdm.md](design/modules/module-d-consent-privacy-abdm.md) | Module D — Consent, privacy, ABDM |

## Guides

| File | Description |
|---|---|
| [guides/setup.md](guides/setup.md) | Local development setup (macOS / Linux / Windows) |
| [guides/ai-services-setup.md](guides/ai-services-setup.md) | STT, TTS, and OCR configuration |
| [guides/deployment.md](guides/deployment.md) | Deployment options and costs (Vercel + Railway + Supabase, or EC2) |

## Dev

| File | Description |
|---|---|
| [dev/tasks-phased.md](dev/tasks-phased.md) | Phased build plan (Phase 0–5) with completion status |
| [dev/tasks-manual.md](dev/tasks-manual.md) | Manual backlog — tasks outside the phased plan, sorted by priority |
| [dev/build-prompts.md](dev/build-prompts.md) | Prompts used to build each phase (internal reference) |
