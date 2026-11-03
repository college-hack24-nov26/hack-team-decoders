"""Retrieval step — pull interview answers + document entities for a patient session.

This is backend deliverable #2 of Wave 4: "given a session_id, pull the relevant
interview_answers and document_entities/embeddings for that patient."

The data is formatted into a context block that the LLM prompt template consumes.
No embeddings/vector search in the MVP — direct DB queries are sufficient since
we're pulling ALL answers and entities for the patient, not doing semantic retrieval
over a large corpus. The pgvector path is a post-hackathon optimization for when
patients have dozens of prior documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.models import (
    Document,
    DocumentEntity,
    InterviewAnswer,
    InterviewSession,
    RedFlag,
)


@dataclass
class RetrievedContext:
    """Everything the summarizer needs to produce a structured summary."""

    session: InterviewSession
    answers: list[InterviewAnswer] = field(default_factory=list)
    red_flags: list[RedFlag] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    entities: list[DocumentEntity] = field(default_factory=list)

    @property
    def chief_complaint(self) -> str:
        return self.session.chief_complaint or "Not specified"

    @property
    def mode(self) -> str:
        return self.session.mode or "general"

    @property
    def patient_language(self) -> str:
        return self.session.patient.preferred_language if self.session.patient else "en"

    def answers_by_field(self) -> dict[str, str]:
        """Flat dict of field_id → human-readable value for the prompt."""
        result: dict[str, str] = {}
        for answer in self.answers:
            val = answer.value
            # Unwrap {"answer": ...} wrapper from simple values
            if isinstance(val, dict) and "answer" in val and len(val) == 1:
                val = val["answer"]
            # Skip skipped questions
            if isinstance(val, dict) and val.get("skipped"):
                continue
            # Convert lists to comma-separated string
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            result[answer.field] = str(val) if val is not None else ""
        return result

    def entities_grouped(self) -> dict[str, list[dict]]:
        """Entities grouped by type for the prompt context.

        ``is_abnormal`` is folded in from the column, not read out of ``value``.
        Module B stores the abnormal-value verdict as a column on
        DocumentEntity while ``value`` holds only the extracted fields, so
        consumers that looked for ``value["is_abnormal"]`` silently saw every
        result as normal — an HbA1c of 8.9% reached the physician's summary
        unflagged.
        """
        grouped: dict[str, list[dict]] = {}
        for entity in self.entities:
            payload = dict(entity.value or {})
            payload["is_abnormal"] = bool(entity.is_abnormal)
            grouped.setdefault(entity.entity_type, []).append(payload)
        return grouped

    def format_for_prompt(self) -> str:
        """Format the retrieved context into a text block the LLM prompt consumes."""
        parts: list[str] = []

        # Interview answers
        parts.append("=== INTERVIEW ANSWERS ===")
        parts.append(f"Chief Complaint: {self.chief_complaint}")
        parts.append(f"Mode: {self.mode}")
        parts.append("")

        answers = self.answers_by_field()
        for field_id, value in sorted(answers.items()):
            if field_id == "chief_complaint":
                continue
            label = field_id.replace(".", " > ").replace("_", " ").title()
            parts.append(f"  {label}: {value}")

        # Red flags
        if self.red_flags:
            parts.append("")
            parts.append("=== RED FLAGS (TRIGGERED) ===")
            for flag in self.red_flags:
                parts.append(f"  ⚠️ {flag.symptom} (severity: {flag.severity})")

        # Document entities
        if self.entities:
            parts.append("")
            parts.append("=== DOCUMENT ENTITIES (from uploaded documents) ===")
            grouped = self.entities_grouped()
            for entity_type, items in grouped.items():
                parts.append(f"  [{entity_type.upper()}]")
                for item in items:
                    if entity_type == "medication":
                        parts.append(
                            f"    - {item.get('drug', '?')} "
                            f"{item.get('dose', '')} {item.get('frequency', '')}"
                        )
                    elif entity_type == "investigation_value":
                        abnormal = " ⚠️ ABNORMAL" if item.get("is_abnormal") else ""
                        parts.append(
                            f"    - {item.get('test', '?')}: {item.get('value', '')} "
                            f"{item.get('unit', '')} (ref: {item.get('ref_range', 'N/A')}){abnormal}"
                        )
                    elif entity_type == "diagnosis":
                        parts.append(f"    - {item.get('name', item.get('value', '?'))}")
                    else:
                        parts.append(f"    - {item}")

        return "\n".join(parts)


def retrieve_session_context(session_id: str, db: Session) -> RetrievedContext:
    """Pull all relevant data for a session to feed the summarizer.

    Args:
        session_id: The interview session UUID.
        db: SQLAlchemy session.

    Returns:
        RetrievedContext with all interview answers, red flags, and document entities.

    Raises:
        ValueError: If the session doesn't exist.
    """
    import uuid

    session = (
        db.query(InterviewSession).filter(InterviewSession.id == uuid.UUID(session_id)).first()
    )
    if session is None:
        raise ValueError(f"Interview session {session_id} not found")

    # All answers for this session
    answers = db.query(InterviewAnswer).filter(InterviewAnswer.session_id == session.id).all()

    # Red flags for this session
    red_flags = db.query(RedFlag).filter(RedFlag.session_id == session.id).all()

    # All documents for the same patient
    documents = (
        db.query(Document)
        .filter(Document.patient_id == session.patient_id)
        .order_by(Document.document_date.desc().nullslast(), Document.uploaded_at.desc())
        .all()
    )

    # All entities from those documents
    doc_ids = [doc.id for doc in documents]
    entities: list[DocumentEntity] = []
    if doc_ids:
        entities = db.query(DocumentEntity).filter(DocumentEntity.document_id.in_(doc_ids)).all()

    return RetrievedContext(
        session=session,
        answers=answers,
        red_flags=red_flags,
        documents=documents,
        entities=entities,
    )
