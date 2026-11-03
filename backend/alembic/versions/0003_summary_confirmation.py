"""Add confirmation attribution to summaries.

`physician_edited` already recorded *that* a human changed the draft. These
columns record *who* signed it off and *when*, which is what makes a confirmed
summary accountable rather than merely approved — the physician dashboard
promotes an AI draft into a record the hospital acts on, and that transition
needs a name against it.

Revision ID: 0003_summary_confirmation
Revises: 0002_document_embeddings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_summary_confirmation"
down_revision: str = "0002_document_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "summaries",
        sa.Column("confirmed_by_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "summaries",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_summaries_confirmed_by_id_physicians",
        "summaries",
        "physicians",
        ["confirmed_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_summaries_confirmed_by_id_physicians", "summaries", type_="foreignkey")
    op.drop_column("summaries", "confirmed_at")
    op.drop_column("summaries", "confirmed_by_id")
