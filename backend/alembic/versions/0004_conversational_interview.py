"""Add the conversational interview engine: per-session engine + message log.

The interview was a deterministic walk through a fixed ontology. This adds the
option of driving it as a conversation instead, which the problem statement
requires ("dynamically branches based on chief complaint and prior answers").

Two schema changes:

``interview_sessions.engine``
    Which engine owns this session. Backfills to 'legacy' via server_default,
    because every row that exists when this migration runs was produced by the
    state machine and mislabelling them would make the transcript log look
    empty rather than absent. A session cannot change engine mid-flight: the
    two disagree about whose turn it is, so a conversation finished by the state
    machine would re-ask what the patient already answered in prose.

``interview_messages``
    The conversation itself. Deliberately separate from ``interview_answers``,
    which stays the clinical record: canonical ontology field ids with validated
    values, and the only thing the summariser reads. This table holds what was
    actually said, in the patient's own words and order, so an interrupted
    interview can be resumed and a clinician can read back the original phrasing.

Revision ID: 0004_conversational_interview
Revises: 0003_summary_confirmation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_conversational_interview"
down_revision: str = "0003_summary_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default (not just a Python-side default) so existing rows get a
    # value in the same statement that adds the NOT NULL column.
    op.add_column(
        "interview_sessions",
        sa.Column("engine", sa.String(20), nullable=False, server_default="legacy"),
    )

    op.create_table(
        "interview_messages",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # JSONB, matching every other JSON column in the schema and the ORM's
        # JsonbOrJson type. Plain JSON would store fine and then behave
        # differently under the containment operators and refuse to be indexed.
        sa.Column("extracted_data", JSONB(), nullable=True),
        sa.Column("input_mode", sa.String(10), nullable=False, server_default="touch"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["interview_sessions.id"],
            name="fk_interview_messages_session_id_interview_sessions",
        ),
    )
    # Every read of this table is "the whole conversation for one session, in
    # order", which is a sequential scan without this.
    op.create_index(
        "ix_interview_messages_session_created",
        "interview_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_interview_messages_session_created", table_name="interview_messages")
    op.drop_table("interview_messages")
    op.drop_column("interview_sessions", "engine")
