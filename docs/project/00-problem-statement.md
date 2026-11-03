# Problem Statement (Condensed)

**ID:** 26047 · **Title:** Patient Case-Taking Software
**Organization:** Ministry of Ayush · **Department:** All India Institute of Ayurveda

> Full original PS text should be kept in `docs/reference/original-ps-26047.txt` (not duplicated
> here verbatim) — this file is our working paraphrase/summary for quick reference.

## The core problem

Indian OPDs (especially tertiary government hospitals) see 4,000–10,000 patients/day with
doctor consultation windows as short as 2–5 minutes. In that window the physician has to take
a history, examine, diagnose, counsel, and prescribe — so history-taking (arguably the single
highest-yield diagnostic step) gets systematically compressed or skipped.

AYUSH/Ayurvedic intake is even heavier: proper Ashtavidha/Dashavidha Pariksha (constitution,
current imbalance, digestive capacity, bowel nature, diet/lifestyle, causative factors,
pathogenesis) is essentially impossible to do justice to in a 2–5 minute slot.

On top of that, patients arrive with fragmented paper records (prescriptions, lab reports,
discharge summaries — handwritten, multiple languages, no chronological order), which eats
further into consult time just to *read*.

ABDM (ABHA IDs, Health Information Exchange, FHIR) solves the *back-end* interoperability
problem, but there's no "first-mile" tool that captures structured history and digitizes
documents *before* the patient reaches the doctor.

## Why existing approaches fall short

- **Hospital registration kiosks** — demographics + token number only, no clinical content.
- **Health apps / tele-triage chatbots** — assume smartphone literacy, connectivity, and
  pre-visit enrolment; excludes elderly/rural/low-literacy/first-visit patients who are the
  bulk of OPD load.
- **Nurse-led triage desks** — human-resource bound, doesn't scale to thousands/day.
- **Generic scanners** — digitize images but don't extract/structure/link clinical content.

## What has to be solved technically

1. Multilingual, multi-accent voice capture in noisy environments (Hindi/English + regional).
2. Zero-training accessibility for elderly/low-literacy first-time users.
3. Turning free-form narration into a standardized clinical history (CC, HPI, PMH/PSH,
   drug/allergy, family, personal, ROS) — plus AYUSH Dashavidha Pariksha where relevant.
4. Reliable OCR + structured extraction from handwritten/printed multilingual documents.
5. DPDP Act 2023 + ABDM consent-framework-compliant handling of sensitive health data.

## Expected solution — "MediKiosk"

An AI kiosk/software platform, usable via voice or touch, that runs the patient through:

| Step | Name | What happens |
|---|---|---|
| 1 | **Identify** | Patient logs in via ABHA/Aadhaar or registers as new; picks language; gives audio-guided consent |
| 2 | **Converse** | Adaptive AI interview (voice + touch) captures chief complaint, HPI, full history; red flags trigger priority triage |
| 3 | **Scan** | Patient uploads prior prescriptions/labs/discharge summaries; system OCRs, structures, and timelines them |
| 4 | **Summarize & Route** | AI generates a structured summary, links it to ABHA, pushes to the hospital HIS, updates the digital record |
| 5 | **Consult** | Physician sees the full structured history in seconds, edits/confirms it, and spends the actual consult on exam + reasoning + counselling |

### The four modules

- **Module A — Conversational Multimodal History Engine**: adaptive voice+touch interview,
  SOCRATES-style follow-ups, AYUSH history mode, red-flag detection.
- **Module B — Medical Document Digitization & Intelligence**: OCR (printed + handwritten,
  multilingual), entity extraction, chronological organization, abnormal-value flagging.
- **Module C — Structured History Summary Generator**: merges conversation + documents into
  one physician-ready summary; always editable/rejectable by the physician; bilingual output.
- **Module D — Consent, Privacy & ABDM Integration**: ABHA auth, DPDP-compliant consent,
  FHIR push to HIS/PHR, secure processing, session data purge.

See [`05-modules/`](./05-modules) for build-level specs on each, and
[`06-tasks.md`](./06-tasks.md) for how this becomes a sequenced build plan.
