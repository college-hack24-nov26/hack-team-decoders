"""Initial schema — Phase 0 tables from docs/design/03-data-model.md

Revision ID: 0001_initial_schema
Revises: (none)
Create Date: 2026-08-27

DEFERRED TABLES (noted here, will be added in later phases):
  - embeddings: Deferred to Phase 3/4.  The vector column dimension depends on
    the embedding model chosen for the summariser (Phase 4).  The pgvector
    `vector(n)` type requires a known dimension at DDL time.  A dedicated
    migration will create this table once the embedding model is decided.

All other tables from the data model are implemented below.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # patients
    # ------------------------------------------------------------------
    op.create_table(
        "patients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("abha_id", sa.Text(), nullable=True, unique=True),
        sa.Column("aadhaar_ref", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # ------------------------------------------------------------------
    # consent_records
    # ------------------------------------------------------------------
    op.create_table(
        "consent_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("scope", JSONB(), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("audio_confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "given_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_consent_records_patient_id", "consent_records", ["patient_id"])

    # ------------------------------------------------------------------
    # interview_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "interview_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("chief_complaint", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(20), nullable=False, server_default="general"),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_interview_sessions_patient_id", "interview_sessions", ["patient_id"])

    # ------------------------------------------------------------------
    # interview_answers
    # ------------------------------------------------------------------
    op.create_table(
        "interview_answers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", UUID(as_uuid=True), sa.ForeignKey("interview_sessions.id"), nullable=False
        ),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("raw_transcript", sa.Text(), nullable=True),
        sa.Column("input_mode", sa.String(10), nullable=False, server_default="touch"),
    )
    op.create_index("ix_interview_answers_session_id", "interview_answers", ["session_id"])

    # ------------------------------------------------------------------
    # red_flags
    # ------------------------------------------------------------------
    op.create_table(
        "red_flags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", UUID(as_uuid=True), sa.ForeignKey("interview_sessions.id"), nullable=False
        ),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("triage_notified", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_red_flags_session_id", "red_flags", ["session_id"])

    # ------------------------------------------------------------------
    # documents
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("file_uri", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("ocr_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_documents_patient_id", "documents", ["patient_id"])

    # ------------------------------------------------------------------
    # document_entities
    # ------------------------------------------------------------------
    op.create_table(
        "document_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("is_abnormal", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_document_entities_document_id", "document_entities", ["document_id"])

    # ------------------------------------------------------------------
    # summaries
    # ------------------------------------------------------------------
    op.create_table(
        "summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "session_id", UUID(as_uuid=True), sa.ForeignKey("interview_sessions.id"), nullable=False
        ),
        sa.Column("structured_content", JSONB(), nullable=False, server_default="{}"),
        sa.Column("generated_by", sa.String(30), nullable=False, server_default="main_api"),
        sa.Column("physician_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("pushed_to_his_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abha_linked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_summaries_patient_id", "summaries", ["patient_id"])
    op.create_index("ix_summaries_session_id", "summaries", ["session_id"])

    # ------------------------------------------------------------------
    # physicians
    # ------------------------------------------------------------------
    op.create_table(
        "physicians",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="physician"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_physicians_email", "physicians", ["email"], unique=True)

    # ------------------------------------------------------------------
    # audit_logs  (append-only — required for DPDP Act compliance)
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("physicians.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource", sa.String(200), nullable=False),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("physicians")
    op.drop_table("summaries")
    op.drop_table("document_entities")
    op.drop_table("documents")
    op.drop_table("red_flags")
    op.drop_table("interview_answers")
    op.drop_table("interview_sessions")
    op.drop_table("consent_records")
    op.drop_table("patients")
