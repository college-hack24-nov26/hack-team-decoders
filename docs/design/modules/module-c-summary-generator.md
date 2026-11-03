# Module C — Structured History Summary Generator

## Purpose
Synthesize the interview answers + digitized document entities into a single, standard-format,
physician-ready clinical summary — available the moment the patient enters the consultation room.

## Inputs
- Completed `interview_answers` for a session
- `document_entities` for the patient (via retrieval over `embeddings`)

## Outputs
- A `summaries` record with `structured_content` in the standard format:
  Chief complaint → HPI → Past medical/surgical → Drug & allergy → Family → Personal → ROS →
  Prior investigations summary
- Bilingual output: patient-facing audio confirmation (their language) + physician-facing
  summary (English/Hindi)

## Design principles (non-negotiable, per the PS)
- **The summary is always a draft.** The physician can accept, amend, or reject it — this is
  never presented as an autonomous diagnosis.
- **Traceable.** Every field in the summary should be traceable back to either an interview
  answer or a document entity, so a physician can spot-check.

## Pipeline
1. Retrieve relevant interview answers + document entities for the session (via LangChain /
   pgvector retrieval described in `01-architecture.md`).
2. Pass through the **Security Layer** (consent scope check, PII handling — see Module D).
3. Call the LLM — routed to **Main API** or **Local Offline** model depending on availability
   (this branching lives in one place, see `04-api-spec.md` notes).
4. Format the model output into the fixed structured schema (don't let the LLM freeform the
   structure — constrain it with a schema/prompt template and validate the output).
5. Store, and surface on the physician dashboard.

## MVP scope for the hackathon
- Main API path only is fine for the live demo; implement the local-model failover as a
  working code path even if you don't rely on it during the actual demo, since it's part of
  the stated requirement and worth showing judges.
- English + Hindi output only.

## Acceptance criteria
- Given a completed interview + 1–2 uploaded documents, produces a structured summary matching
  the fixed schema within a few seconds.
- Physician can edit any field and re-confirm; the edit is persisted and distinguishable from
  the original AI-generated version (`physician_edited` flag).
