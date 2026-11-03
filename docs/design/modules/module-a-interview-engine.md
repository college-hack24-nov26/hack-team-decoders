# Module A — Conversational Multimodal History Engine

## Purpose
Conduct a structured clinical history interview through voice and/or touch, adapting questions
to the patient's chief complaint the way a physician would.

## Inputs
- Patient's spoken/typed chief complaint
- Ongoing answers (drives adaptive branching)
- Selected language, mode (general / AYUSH)

## Outputs
- `interview_answers` records (structured, per field)
- Raw transcripts (for auditability / re-summarization)
- Red-flag events (if any)

## Key components
1. **Dialogue manager** — decides the next question given the history-so-far. Start as a
   deterministic state machine keyed on chief complaint (much easier to demo reliably than a
   fully free-form LLM agent); layer in LLM-driven follow-ups once the deterministic core works.
2. **Clinical history ontology** — the fixed set of fields you're trying to fill:
   Chief Complaint → HPI (SOCRATES: Site, Onset, Character, Radiation, Associations,
   Time course, Exacerbating/relieving, Severity) → Past medical/surgical → Drug & allergy →
   Family → Personal → Review of systems.
3. **AYUSH extension** — Dashavidha Pariksha fields (Prakriti, Vikriti, Sara, Samhanana,
   Pramana, Satmya, Sattva, Ahara Shakti, Vyayama Shakti, Vaya) + Ahara-Vihara, toggled on for
   AYUSH-mode sessions.
4. **Dual input** — every question must be answerable by voice (ASR) or by tapping a
   touch-friendly option; never force one modality.
5. **Red-flag detector** — a checklist/rules layer (not solely relying on the LLM) watching for
   emergency combinations (e.g., chest pain + dyspnoea, sudden weakness/facial droop) and
   firing a priority-triage event immediately, independent of interview completion.

## MVP scope for the hackathon
- 3–5 chief-complaint templates with real SOCRATES branching (e.g. chest pain, fever, abdominal
  pain, headache, breathlessness)
- Fallback generic template for anything outside those
- English + Hindi
- Red-flag rules for the same 3–5 complaints

## Acceptance criteria
- A patient can complete a full interview for a supported chief complaint using voice only,
  touch only, or a mix, in under ~4–5 minutes.
- A red-flag combination triggers a visible priority alert within the same session.
- All answers are retrievable in structured form (not just as a raw transcript) afterward.
