# Data Model (Draft)

Working schema for PostgreSQL + pgvector. Treat as a starting point — refine per module as you
build. Types are indicative (Postgres-flavored), not final DDL.

## Core entities

### `patients`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| abha_id | text, nullable, unique | null for new/unregistered patients |
| aadhaar_ref | text, nullable | store a reference/hash, not raw Aadhaar |
| name | text | |
| age | int | |
| gender | text | |
| phone | text | |
| preferred_language | text | ISO code |
| created_at | timestamptz | |

### `consent_records`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| patient_id | uuid, fk → patients | |
| scope | jsonb | granular: interview, documents, ABDM push, etc. |
| language | text | which language the consent was given/explained in |
| audio_confirmed | boolean | patient heard + confirmed audio explanation |
| given_at | timestamptz | |
| revoked_at | timestamptz, nullable | |

### `interview_sessions`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| patient_id | uuid, fk | |
| chief_complaint | text | |
| mode | text | `ayush` or `general` |
| status | text | `in_progress`, `completed`, `red_flagged` |
| started_at / completed_at | timestamptz | |

### `interview_answers`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| session_id | uuid, fk → interview_sessions | |
| field | text | e.g. `hpi.onset`, `drug_history.current_meds`, `ayush.prakriti` |
| value | jsonb | structured answer |
| raw_transcript | text, nullable | original voice transcript if applicable |
| input_mode | text | `voice` or `touch` |

### `red_flags`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| session_id | uuid, fk | |
| symptom | text | |
| severity | text | |
| triggered_at | timestamptz | |
| triage_notified | boolean | |

### `documents`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| patient_id | uuid, fk | |
| file_uri | text | pointer to blob storage, not the blob itself |
| doc_type | text | `prescription`, `lab_report`, `discharge_summary` |
| document_date | date, nullable | extracted/inferred date for chronological sort |
| ocr_status | text | `pending`, `done`, `failed` |
| uploaded_at | timestamptz | |

### `document_entities`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| document_id | uuid, fk | |
| entity_type | text | `diagnosis`, `medication`, `investigation_value`, `procedure` |
| value | jsonb | e.g. `{drug, dose, freq}` or `{test, value, unit, ref_range}` |
| is_abnormal | boolean, nullable | for investigation values |

### `embeddings`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| source_type | text | `document` or `interview_answer` |
| source_id | uuid | |
| embedding | vector(n) | pgvector column; dimension per chosen embedding model |

### `summaries`
| column | type | notes |
|---|---|---|
| id | uuid, pk | |
| patient_id | uuid, fk | |
| session_id | uuid, fk | |
| structured_content | jsonb | CC → HPI → PMH/PSH → drug/allergy → family → personal → ROS → prior investigations |
| generated_by | text | which model path: `main_api` or `local_offline` |
| physician_edited | boolean | |
| status | text | `draft`, `confirmed`, `rejected` |
| pushed_to_his_at | timestamptz, nullable | |
| abha_linked_at | timestamptz, nullable | |

### `physicians` / `audit_logs`
Standard role-based user table for physicians/staff, and an append-only audit log
(`actor_id`, `action`, `resource`, `detail`, `timestamp`) covering every read/write of patient data —
required for DPDP Act compliance and worth having from day one rather than bolting on later.

**Implementation note (Phase 1):** The `audit_logs.actor_id` FK targets `physicians`, so for
patient-initiated actions (register, login, consent), the patient ID is stored in
`detail.actor_id` (JSONB) while `actor_id` stays NULL. This avoids a polymorphic FK while
still providing a complete audit trail. A future migration can add a nullable `patient_id` FK
if needed.

## Notes

- Keep PII/health data columns clearly separated so encryption-at-rest and access policies can
  be applied precisely (see `05-modules/module-d-consent-privacy-abdm.md`).
- `structured_content` in `summaries` should mirror whatever schema you land on for the
  physician-facing summary in `04-api-spec.md` — keep them in sync.
