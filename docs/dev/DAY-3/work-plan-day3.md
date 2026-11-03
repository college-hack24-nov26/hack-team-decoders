# Work Plan — Day 3

One person (Aarsh). Prompts organized by execution order.

---

## Quick Reference

| Phase | What | Time | Prompt |
|-------|------|------|--------|
| 1 | Patient Login + Doctor Selection | 3 hr | F2 |
| 2 | Conversation History + Demo Data | 1.5 hr | F1 |
| 3 | Ayurveda Interview Procedure | 2.5 hr | F3 |
| 4 | Doctor Dashboard + VisitDone | 3 hr | B3, B4 |
| 5 | Claim-to-Doc Linking (if time) | 1.5 hr | B6 |
| **Total** | | **~11.5 hr** | |

---

## Already Done (from Day 1 + Day 2 + recent PRs)

These are **NOT** in this plan — they're already merged:

| Task | Status | How |
|------|--------|-----|
| A1 — Azure AI integration | ✅ Done | PR #11 |
| A2 — Conversational interview engine | ✅ Done | PR #11 |
| A3 — Azure Speech STT/TTS | ✅ Done | PR #11 |
| A4 — Document analysis | ✅ Done | Sarvam OCR + entity extraction |
| A5 — Summary quality + real PDF | ✅ Done | ws-a/summary-pdf-embeddings merge |
| A6 — Real embeddings | ✅ Done | ws-a/summary-pdf-embeddings merge |
| B2 — UI cleanup | ✅ Done | Day 2 |
| B5 — Landing page | ✅ Done | frontend/landing/ exists |

---

## Execution Order

### Phase 1 — Patient Login System (3 hr) 🔴

**Prompt: F2**

Foundation for the demo flow. Returning patients, doctor selection, visit tracking.

```
Run prompt F2 from build-prompts-3.md
```

After done:
- [ ] Doctor table and seed data exist
- [ ] Visit table with token numbering works
- [ ] New/returning patient flow works on frontend
- [ ] Doctor selection screen works
- [ ] Past visit history shows for returning patients

---

### Phase 2 — Conversation History + Demo Data (1.5 hr) 🔴

**Prompt: F1**

Demo data that tells a compelling clinical story for the SIH presentation.
Three realistic patient stories with complete conversation histories.

```
Run prompt F1 from build-prompts-3.md
```

After done:
- [ ] 3 patients with complete conversation histories seeded
- [ ] GET /interview/sessions/{id}/messages returns message history
- [ ] GET /interview/sessions/{id}/summary returns structured section data
- [ ] GET /patients/{id}/sessions lists all sessions
- [ ] Red flag patient (Ramesh) has realistic cardiac story
- [ ] AYUSH patient (Priya) has digestive complaint with Prakriti data

---

### Phase 3 — Ayurveda Interview Procedure (2.5 hr) 🔴

**Prompt: F3**

Comprehensive Ayurvedic clinical interview. Critical because the project is for the
Ministry of Ayush and AIIA — the Ayurvedic depth is the key differentiator.

```
Run prompt F3 from build-prompts-3.md
```

After done:
- [ ] ayurveda.py contains complete Ayurvedic examination protocol
- [ ] AYUSH conversation prompt covers Ashtavidha, Prakriti, Ahara-Vihara
- [ ] Ontology extended with all AYUSH fields
- [ ] Prakriti determination (Vata/Pitta/Kapha) works
- [ ] Summary includes Ayurvedic assessment section
- [ ] Demo data includes AYUSH interview with realistic responses

---

### Phase 4 — Dashboard + VisitDone (3 hr) 🟡

**Prompts: B3 → B4** (sequential)

Only do this if Phases 1–3 are done.

```
Run prompt B3 from build-prompts-3.md  (2 hr)
Then run prompt B4                      (1 hr)
```

After done:
- [ ] Doctor can view uploaded documents with entities
- [ ] Inline summary editing works
- [ ] PDF download button works
- [ ] Ayurvedic assessment shows for AYUSH patients
- [ ] Patient sees Hindi summary on completion with TTS

---

### Phase 5 — Claim-to-Doc Linking (1.5 hr) 🟢

**Prompt: B6**

Only if everything else is done.

```
Run prompt B6 from build-prompts-3.md
```

---

## Timing Overview

```
Hour  0    1    2    3    4    5    6    7    8    9    10   11
 │    │    │    │    │    │    │    │    │    │    │    │    │
 ├─────── F2 (Patient Login) ────┤
 │                               ├── F1 (History) ──┤
 │                                                   ├────── F3 (Ayurveda) ───────┤
 │                                                                                │
 │                                                                    ├── B3+B4 (Dashboard) ──┤
 │                                                                                             ├─ B6 ─┤
```

---

## Tips

1. **F2 first** — patient login touches many files; get it stable early
2. **F1 seed data quality matters** — judges are medical professionals, the demo
   conversations must sound clinically realistic
3. **F3 Ayurveda depth** — this project is for AIIA. A shallow AYUSH mode will lose
   points. Make the Prakriti assessment thorough.
4. **B3+B4 are polish** — important but not blockers for the demo
5. **B6 is stretch** — skip it if tight on time
