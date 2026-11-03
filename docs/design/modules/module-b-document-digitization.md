# Module B — Medical Document Digitization & Intelligence

## Purpose
Turn a patient's stack of physical prescriptions/labs/discharge summaries into structured,
chronologically ordered, physician-usable data.

## Inputs
- Uploaded/scanned document images (camera capture or file upload)

## Outputs
- `documents` + `document_entities` records
- A chronologically ordered timeline per patient
- Flags on abnormal lab values

## Pipeline
1. **Capture** — camera or file upload from the kiosk UI.
2. **OCR** — printed text first (reliable), handwriting as a stretch goal (much harder; be
   upfront in the demo about this being the biggest technical risk area).
3. **Entity extraction** — pull out diagnoses, medications (+dose/frequency), investigation
   results (test, value, unit, reference range), procedures/surgeries. Start rules/regex-based
   for common formats, layer an LLM extraction pass for anything the rules miss.
4. **Date extraction** — find/infer the document date to enable chronological sorting.
5. **Abnormal-value flagging** — compare extracted lab values against a reference-range table.
6. **Storage** — original image → blob storage; structured entities → Postgres;
   embeddings of document text → pgvector, for the summarizer's retrieval step.

## MVP scope for the hackathon
- Printed-text OCR only (Tesseract) for the demo; call out handwriting OCR as a documented
  post-hackathon upgrade (AI4Bharat OCR) rather than attempting it live.
- A small reference-range table covering common tests (CBC, glucose, lipid panel, etc.)
- Rules-based extraction for a few common Indian prescription/lab report formats, with LLM
  fallback for anything else

## Acceptance criteria
- Uploading 2–3 sample documents produces a visible, ordered timeline with at least diagnosis
  and medication entities correctly extracted for clean, printed sample docs.
- At least one abnormal value in a sample lab report gets flagged.
