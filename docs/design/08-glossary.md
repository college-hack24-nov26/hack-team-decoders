# Glossary

**ABDM** — Ayushman Bharat Digital Mission. India's national digital health infrastructure
initiative (identity, data exchange, interoperability standards).

**ABHA** — Ayushman Bharat Health Account. A patient's unique digital health ID under ABDM,
used to link records across providers.

**FHIR** — Fast Healthcare Interoperability Resources. The data-exchange standard ABDM uses so
different hospital systems can share structured health records.

**HIS** — Hospital Information System. The hospital's internal system of record for patient
data, appointments, etc. — where MediKiosk's output ultimately needs to land.

**PHR** — Personal Health Record. The patient-owned record linked to their ABHA ID.

**OPD** — Out-Patient Department. The walk-in consultation department (as opposed to inpatient/admitted care).

**HPI** — History of Present Illness. The detailed account of the current complaint.

**SOCRATES** — A mnemonic for structured symptom history-taking: Site, Onset, Character,
Radiation, Associations, Time course, Exacerbating/relieving factors, Severity.

**PMH / PSH** — Past Medical History / Past Surgical History.

**ROS** — Review of Systems. A systematic check across body systems for any additional symptoms.

**AYUSH** — Ayurveda, Yoga & Naturopathy, Unani, Siddha, Homoeopathy — India's traditional
medicine systems, overseen by the Ministry of Ayush.

**AIIA** — All India Institute of Ayurveda, the department behind this problem statement.

**Trividha / Ashtavidha / Dashavidha Pariksha** — Ayurvedic diagnostic examination frameworks
(three-fold / eight-fold / ten-fold examination), used to assess a patient's constitution and
condition beyond conventional history-taking.

**Prakriti / Vikriti** — Ayurvedic concepts: Prakriti is a person's inherent constitution;
Vikriti is their current state of imbalance relative to that constitution.

**Agni** — Digestive/metabolic capacity, a core Ayurvedic assessment parameter.

**Koshtha** — Bowel nature/type, another Ayurvedic assessment parameter.

**Ahara-Vihara** — Diet and lifestyle assessment.

**DPDP Act 2023** — India's Digital Personal Data Protection Act — the governing law for
consent, storage, and processing of personal (including health) data that MediKiosk must comply with.

**ASR** — Automatic Speech Recognition (speech-to-text).

**TTS** — Text-to-Speech.

**OCR** — Optical Character Recognition (image/handwriting → text).

**Bhashini / AI4Bharat** — Government-backed and open Indian-language AI initiatives providing
ASR/TTS/translation models tuned for Indian languages and accents.

**RAG** — Retrieval-Augmented Generation. Feeding an LLM relevant retrieved data (here: past
interview answers / document entities) alongside the prompt, rather than relying on the model's
own memory.

**pgvector** — A PostgreSQL extension that adds a vector data type + similarity search, used
here to store and query embeddings without a separate vector database.
