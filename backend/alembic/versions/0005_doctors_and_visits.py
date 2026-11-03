"""Doctors and visits: patient login, doctor selection, and visit tracking (F2).

Two new tables and one index:

``doctors``  — a doctor a patient can pick at the kiosk, with a live queue count.
               Separate from ``physicians`` (which is a login/account): most
               doctors never log in, and a queue entry has no business carrying a
               password column.
``visits``   — one trip through the kiosk, tying identify → doctor → interview →
               summary → consult together. Its foreign keys to the interview
               session and summary are nullable and filled in as the patient
               progresses.
``patients.phone`` gains an index, because returning-patient login looks a
               patient up by phone on every kiosk sign-in.

Revision ID: 0005_doctors_and_visits
Revises: 0004_conversational_interview
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_doctors_and_visits"
down_revision: str = "0004_conversational_interview"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doctors",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("department", sa.String(50), nullable=False),
        sa.Column("specialization", sa.Text(), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("queue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_doctors_department", "doctors", ["department"])

    op.create_table(
        "visits",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("patient_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("department", sa.String(50), nullable=True),
        sa.Column("interview_session_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("summary_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="registered"),
        sa.Column("token_number", sa.Integer(), nullable=False),
        sa.Column("chief_complaint", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], name="fk_visits_patient_id"),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name="fk_visits_doctor_id"),
        sa.ForeignKeyConstraint(
            ["interview_session_id"],
            ["interview_sessions.id"],
            name="fk_visits_interview_session_id",
        ),
        sa.ForeignKeyConstraint(["summary_id"], ["summaries.id"], name="fk_visits_summary_id"),
    )
    op.create_index("ix_visits_patient_id", "visits", ["patient_id"])
    # Token numbers are computed per day, so the hot query is "visits created
    # today"; this index keeps that from scanning the whole table as it grows.
    op.create_index("ix_visits_created_at", "visits", ["created_at"])

    op.create_index("ix_patients_phone", "patients", ["phone"])


def downgrade() -> None:
    op.drop_index("ix_patients_phone", table_name="patients")
    op.drop_index("ix_visits_created_at", table_name="visits")
    op.drop_index("ix_visits_patient_id", table_name="visits")
    op.drop_table("visits")
    op.drop_index("ix_doctors_department", table_name="doctors")
    op.drop_table("doctors")
