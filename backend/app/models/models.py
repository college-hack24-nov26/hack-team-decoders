"""ORM models implementing the schema defined in docs/design/03-data-model.md.

All primary keys are server-generated UUIDs. Timestamps use TIMESTAMPTZ so they
are always timezone-aware. JSON columns use the JsonbOrJson decorator below,
which resolves to JSONB on Postgres and JSON on SQLite, so the same models run
under Docker and under the SQLite-backed test suite.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.db.session import Base

# ---------------------------------------------------------------------------
# Cross-DB type helpers (Postgres uses JsonbOrJson() + native UUID; SQLite uses JSON + CHAR(36))
# ---------------------------------------------------------------------------


class JsonbOrJson(TypeDecorator):
    """Use JSONB on Postgres, plain JSON on SQLite.

    The Postgres branch must return the *dialect's* JSONB type. Returning this
    class instead makes load_dialect_impl call itself for ever, which is what
    happened when JSONB was renamed to JsonbOrJson by a global find-and-replace:
    every Postgres query raised RecursionError while SQLite kept working, so the
    test suite stayed green and only Docker broke.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())


class _UUID(TypeDecorator):
    """Use native UUID on Postgres, CHAR(36) on SQLite.

    See JsonbOrJson above for why the Postgres branch cannot return _UUID().
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value


# ---------------------------------------------------------------------------
# Helper defaults
# ---------------------------------------------------------------------------


def _uuid() -> uuid.UUID:  # noqa: D401
    return uuid.uuid4()


def _now() -> datetime:  # noqa: D401
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# patients
# ---------------------------------------------------------------------------


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    abha_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    aadhaar_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # store hash, not raw
    name: Mapped[str] = mapped_column(Text, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Indexed: returning-patient login looks a patient up by phone, and without
    # the index that is a full table scan on every kiosk login.
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    # relationships
    consent_records: Mapped[list["ConsentRecord"]] = relationship(back_populates="patient")
    interview_sessions: Mapped[list["InterviewSession"]] = relationship(back_populates="patient")
    documents: Mapped[list["Document"]] = relationship(back_populates="patient")
    summaries: Mapped[list["Summary"]] = relationship(back_populates="patient")
    visits: Mapped[list["Visit"]] = relationship(back_populates="patient")


# ---------------------------------------------------------------------------
# consent_records
# ---------------------------------------------------------------------------


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("patients.id"), nullable=False
    )
    scope: Mapped[dict] = mapped_column(
        JsonbOrJson(), nullable=False
    )  # granular: interview, documents, ABDM push …
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    audio_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    given_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="consent_records")


# ---------------------------------------------------------------------------
# interview_sessions
# ---------------------------------------------------------------------------


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("patients.id"), nullable=False
    )
    chief_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="general"
    )  # 'ayush' | 'general'
    #: Which interview engine drives this session.
    #:
    #: 'legacy'       — the deterministic ontology state machine, question by question.
    #: 'conversation' — the LLM-driven conversational agent (app/interview/conversation.py).
    #:
    #: Stored per session rather than read from config at request time because a
    #: session that started as a conversation cannot be finished by the state
    #: machine: the two disagree about whose turn it is, and the patient would be
    #: re-asked things they already answered in prose. Defaults to 'legacy' so
    #: rows written before this column existed describe themselves correctly.
    engine: Mapped[str] = mapped_column(
        String(20), nullable=False, default="legacy", server_default="legacy"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_progress"
    )  # in_progress | completed | red_flagged
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="interview_sessions")
    answers: Mapped[list["InterviewAnswer"]] = relationship(back_populates="session")
    red_flags: Mapped[list["RedFlag"]] = relationship(back_populates="session")
    summaries: Mapped[list["Summary"]] = relationship(back_populates="session")
    messages: Mapped[list["InterviewMessage"]] = relationship(back_populates="session")


# ---------------------------------------------------------------------------
# interview_answers
# ---------------------------------------------------------------------------


class InterviewAnswer(Base):
    __tablename__ = "interview_answers"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("interview_sessions.id"), nullable=False
    )
    field: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # e.g. hpi.onset, drug_history.current_meds
    value: Mapped[dict] = mapped_column(JsonbOrJson(), nullable=False)
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="touch"
    )  # 'voice' | 'touch'

    session: Mapped["InterviewSession"] = relationship(back_populates="answers")


# ---------------------------------------------------------------------------
# interview_messages  (conversational engine)
# ---------------------------------------------------------------------------


class InterviewMessage(Base):
    """One turn of the conversational interview.

    Separate from ``interview_answers`` because the two answer different
    questions. ``interview_answers`` is the *clinical record*: canonical ontology
    field ids with validated values, and it is all the summariser reads. This
    table is the *conversation*: what was actually said, in the patient's own
    words, in the order it was said.

    Both are needed. The clinical record alone loses the phrasing a clinician may
    want to read back ("it feels like someone sitting on my chest"), and it
    cannot be replayed to resume an interrupted interview. The transcript alone
    is unstructured and reaches no summary field.

    ``extracted_data`` records what the model claimed to extract from this turn
    *after* ontology validation, so a later reviewer can see which utterance
    produced which field — and, when a field is wrong, which sentence to blame.
    """

    __tablename__ = "interview_messages"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("interview_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # 'patient' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Fields accepted from this turn, as {field_id: value}. Null on assistant
    #: turns and on patient turns that yielded nothing usable.
    extracted_data: Mapped[dict | None] = mapped_column(JsonbOrJson(), nullable=True)
    #: How the patient produced this turn, mirroring InterviewAnswer.input_mode.
    input_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="touch")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    session: Mapped["InterviewSession"] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# red_flags
# ---------------------------------------------------------------------------


class RedFlag(Base):
    __tablename__ = "red_flags"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("interview_sessions.id"), nullable=False
    )
    symptom: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    triage_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session: Mapped["InterviewSession"] = relationship(back_populates="red_flags")


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("patients.id"), nullable=False
    )
    file_uri: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # pointer to blob storage, not the blob
    doc_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # prescription | lab_report | discharge_summary
    document_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    ocr_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | done | failed
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    patient: Mapped["Patient"] = relationship(back_populates="documents")
    entities: Mapped[list["DocumentEntity"]] = relationship(back_populates="document")


# ---------------------------------------------------------------------------
# document_entities
# ---------------------------------------------------------------------------


class DocumentEntity(Base):
    __tablename__ = "document_entities"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("documents.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # diagnosis | medication | investigation_value | procedure
    value: Mapped[dict] = mapped_column(JsonbOrJson(), nullable=False)
    is_abnormal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="entities")


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("patients.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("interview_sessions.id"), nullable=False
    )
    structured_content: Mapped[dict] = mapped_column(JsonbOrJson(), nullable=False, default=dict)
    generated_by: Mapped[str] = mapped_column(
        String(30), nullable=False, default="main_api"
    )  # main_api | local_offline
    physician_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft | confirmed | rejected
    pushed_to_his_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    abha_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Attribution for the confirmation. `physician_edited` records *that* a human
    # changed the draft; these record *who* signed it off and when, which is what
    # makes the confirmed record accountable rather than merely approved.
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("physicians.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="summaries")
    session: Mapped["InterviewSession"] = relationship(back_populates="summaries")
    confirmed_by: Mapped["Physician | None"] = relationship()


# ---------------------------------------------------------------------------
# physicians
# ---------------------------------------------------------------------------


class Physician(Base):
    __tablename__ = "physicians"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="physician"
    )  # physician | staff | admin
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="actor")


# ---------------------------------------------------------------------------
# audit_logs  (append-only — required for DPDP Act compliance)
# ---------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("physicians.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JsonbOrJson(), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    actor: Mapped["Physician | None"] = relationship(back_populates="audit_logs")


# ---------------------------------------------------------------------------
# document_embeddings (pgvector — Phase 3)
# ---------------------------------------------------------------------------


class DocumentEmbedding(Base):
    """Vector embedding of document text for retrieval by Module C's summarizer.

    Uses pgvector with dimension 384 (sentence-transformers/all-MiniLM-L6-v2).
    Each row represents one document's full-text embedding.  Module C queries
    via `<->` cosine distance operator keyed on patient_id.
    """

    __tablename__ = "document_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("documents.id"), nullable=False, unique=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("patients.id"), nullable=False
    )
    # The vector column is handled via raw SQL in the migration because
    # SQLAlchemy's mapped_column doesn't natively support pgvector's vector type.
    # At runtime we read/write via raw SQL or the pgvector SQLAlchemy integration.


# ---------------------------------------------------------------------------
# doctors  (selectable at the kiosk — distinct from physicians who log in)
# ---------------------------------------------------------------------------


class Doctor(Base):
    """A doctor a patient can be routed to, with a live queue count.

    Deliberately separate from ``Physician``. A Physician is a login: an account
    with a password and a role that reads the dashboard. A Doctor is a choice on
    the kiosk — the person a patient picks by department, whose queue grows as
    visits are booked. The two are different concerns (authentication vs.
    routing) and most Doctors will never have a dashboard login, so folding them
    into one table would put a password column on a queue entry and a queue count
    on an admin account.
    """

    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    specialization: Mapped[str | None] = mapped_column(Text, nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Patients currently waiting. Incremented when a visit is booked; a real
    #: deployment would decrement it as consultations finish.
    queue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    visits: Mapped[list["Visit"]] = relationship(back_populates="doctor")


# ---------------------------------------------------------------------------
# visits  (one trip through the kiosk, tying the journey together)
# ---------------------------------------------------------------------------


class Visit(Base):
    """One kiosk visit: identify -> pick doctor -> interview -> summary -> consult.

    The visit is the spine the other records hang off. interview_session_id and
    summary_id are nullable and filled in as the patient moves through the flow,
    so a visit exists from the moment a token is issued rather than only once an
    interview has happened.

    ``token_number`` restarts each day. It is not a global sequence: a queue
    ticket that reads #417 on the third morning helps nobody, so it is computed
    per calendar day at creation time (see the visits route).
    """

    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("doctors.id"), nullable=True
    )
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    interview_session_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("interview_sessions.id"), nullable=True
    )
    summary_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("summaries.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="registered"
    )  # registered | in_interview | documents_uploaded | waiting | summary_ready | in_consultation | completed
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chief_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="visits")
    doctor: Mapped["Doctor | None"] = relationship(back_populates="visits")
