"""Add document_embeddings table for pgvector storage.

Revision ID: 0002_document_embeddings
Revises: 0001_initial_schema
Create Date: 2026-08-27

Embedding dimension: 384 (sentence-transformers/all-MiniLM-L6-v2).
Requires the pgvector extension (created in Phase 0 docker init script).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002_document_embeddings"
down_revision: str = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    # Ensure pgvector extension exists (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "document_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        # pgvector vector column — must be created via raw DDL
    )

    # Add the vector column (pgvector extension type)
    op.execute(
        f"ALTER TABLE document_embeddings ADD COLUMN embedding vector({EMBEDDING_DIM}) NOT NULL"
    )

    # Index for fast cosine-distance retrieval per patient
    op.execute("CREATE INDEX ix_doc_embeddings_patient " "ON document_embeddings (patient_id)")
    # ivfflat index for approximate NN search (once there are enough rows)
    op.execute(
        "CREATE INDEX ix_doc_embeddings_vector "
        "ON document_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 10)"
    )


def downgrade() -> None:
    op.drop_table("document_embeddings")
