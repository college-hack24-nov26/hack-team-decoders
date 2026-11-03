"""Add patient review, edit, and confirmation fields to summaries table.

Revision ID: 0006_patient_summary_fields
Revises: 0005_doctors_and_visits
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_patient_summary_fields"
down_revision: str = "0005_doctors_and_visits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "summaries",
        sa.Column("patient_edited", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "summaries",
        sa.Column("patient_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "summaries",
        sa.Column("patient_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("summaries", "patient_confirmed_at")
    op.drop_column("summaries", "patient_confirmed")
    op.drop_column("summaries", "patient_edited")
