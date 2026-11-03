"""Session data purge — Module D deliverable 7.

The problem statement's privacy story includes discarding the raw material once
the structured, consented record has been produced: the photographed
prescription and the recording of the patient's voice are the most sensitive
artefacts in the system and the least useful to keep.

These tests assert the purge genuinely deletes files from disk and clears
transcripts, and — just as important — that it does *not* take the consented
clinical data or the compliance records with it.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.models import (
    AuditLog,
    Document,
    DocumentEntity,
    InterviewAnswer,
    InterviewSession,
    Patient,
)
from app.services.purge import purge_session_data
from app.services.storage import LocalDiskStorage


@pytest.fixture()
def storage(tmp_path) -> LocalDiskStorage:
    """A disk-backed store rooted in a temp dir, not the process singleton."""
    return LocalDiskStorage(tmp_path / "blobs")


@pytest.fixture()
def patient_with_artifacts(sql_db, storage) -> dict:
    """A patient with a stored document image and a voice-derived transcript."""
    pid, sid, docid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    uri = storage.save(b"fake-scan-bytes", "prescription.jpg", pid)

    sql_db.add_all(
        [
            Patient(id=pid, name="Purge Test", age=44, gender="male", phone="9800000009"),
            InterviewSession(id=sid, patient_id=pid, mode="general", status="completed"),
            InterviewAnswer(
                id=uuid.uuid4(),
                session_id=sid,
                field="hpi.narrative",
                value={"answer": "burning chest pain after meals"},
                raw_transcript="I get a burning pain in my chest after I eat",
                input_mode="voice",
            ),
            InterviewAnswer(
                id=uuid.uuid4(),
                session_id=sid,
                field="hpi.onset",
                value={"answer": "weeks"},
                raw_transcript=None,
                input_mode="touch",
            ),
            Document(
                id=docid, patient_id=pid, file_uri=uri, doc_type="prescription", ocr_status="done"
            ),
            DocumentEntity(
                id=uuid.uuid4(),
                document_id=docid,
                entity_type="medication",
                value={"drug": "Pantoprazole", "dose": "40mg", "frequency": "OD"},
                is_abnormal=None,
            ),
        ]
    )
    sql_db.commit()
    return {"patient_id": pid, "session_id": sid, "document_id": docid, "file_uri": uri}


# ---------------------------------------------------------------------------
# What must be destroyed
# ---------------------------------------------------------------------------


class TestPurgeDeletesRawArtifacts:
    def test_the_file_is_actually_gone_from_disk(self, sql_db, storage, patient_with_artifacts):
        path = storage.resolve_path(patient_with_artifacts["file_uri"])
        assert path.exists(), "fixture should have written a file"

        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        assert not path.exists()

    def test_the_file_uri_is_marked_purged(self, sql_db, storage, patient_with_artifacts):
        """A dangling pointer to a deleted blob would look like data loss."""
        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        doc = (
            sql_db.query(Document)
            .filter(Document.id == patient_with_artifacts["document_id"])
            .first()
        )
        assert doc.file_uri == "[PURGED]"

    def test_raw_transcripts_are_cleared(self, sql_db, storage, patient_with_artifacts):
        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        transcripts = [
            a.raw_transcript
            for a in sql_db.query(InterviewAnswer)
            .filter(InterviewAnswer.session_id == patient_with_artifacts["session_id"])
            .all()
        ]
        assert all(t is None for t in transcripts)

    def test_reports_what_it_removed(self, sql_db, storage, patient_with_artifacts):
        result = purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )
        assert result["documents_purged"] == 1
        assert result["transcripts_cleared"] == 1


# ---------------------------------------------------------------------------
# What must survive
# ---------------------------------------------------------------------------


class TestPurgeKeepsConsentedData:
    def test_structured_answers_survive(self, sql_db, storage, patient_with_artifacts):
        """The whole point of the interview is the structured answer, not the audio."""
        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        answers = (
            sql_db.query(InterviewAnswer)
            .filter(InterviewAnswer.session_id == patient_with_artifacts["session_id"])
            .all()
        )
        assert len(answers) == 2
        narrative = next(a for a in answers if a.field == "hpi.narrative")
        assert narrative.value["answer"] == "burning chest pain after meals"

    def test_extracted_entities_survive(self, sql_db, storage, patient_with_artifacts):
        """OCR output is the consented record; only the source image goes."""
        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        entities = (
            sql_db.query(DocumentEntity)
            .filter(DocumentEntity.document_id == patient_with_artifacts["document_id"])
            .all()
        )
        assert len(entities) == 1
        assert entities[0].value["drug"] == "Pantoprazole"

    def test_the_purge_itself_is_audited(self, sql_db, storage, patient_with_artifacts):
        """Deleting patient data is itself an auditable event."""
        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        sql_db.rollback()  # only committed rows survive, as in production
        entry = sql_db.query(AuditLog).filter(AuditLog.action == "session.data_purged").first()
        assert entry is not None
        assert entry.detail["documents_purged"] == 1


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestPurgeRobustness:
    def test_a_missing_file_does_not_abort_the_purge(self, sql_db, storage, patient_with_artifacts):
        """A blob already gone must not stop transcripts from being cleared."""
        storage.resolve_path(patient_with_artifacts["file_uri"]).unlink()

        result = purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        assert result["transcripts_cleared"] == 1

    def test_purging_twice_is_safe(self, sql_db, storage, patient_with_artifacts):
        kwargs = {
            "patient_id": patient_with_artifacts["patient_id"],
            "session_id": patient_with_artifacts["session_id"],
            "storage": storage,
        }
        purge_session_data(sql_db, **kwargs)
        second = purge_session_data(sql_db, **kwargs)

        # Nothing left to clear the second time round.
        assert second["transcripts_cleared"] == 0

    def test_another_patients_data_is_untouched(self, sql_db, storage, patient_with_artifacts):
        other_pid = uuid.uuid4()
        other_uri = storage.save(b"other-scan", "other.jpg", other_pid)
        sql_db.add_all(
            [
                Patient(
                    id=other_pid, name="Bystander", age=30, gender="female", phone="9800000010"
                ),
                Document(
                    id=uuid.uuid4(),
                    patient_id=other_pid,
                    file_uri=other_uri,
                    doc_type="lab_report",
                    ocr_status="done",
                ),
            ]
        )
        sql_db.commit()

        purge_session_data(
            sql_db,
            patient_id=patient_with_artifacts["patient_id"],
            session_id=patient_with_artifacts["session_id"],
            storage=storage,
        )

        assert storage.resolve_path(other_uri).exists()
