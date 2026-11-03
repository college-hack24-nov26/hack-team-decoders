"""Shared fixtures.

Wave 4 introduced queries FakeSession cannot express (``in_``, computed
``order_by``), which is the point its own docstring names for switching to a real
database. These fixtures give tests a real SQLite engine per test, which keeps
them hermetic and fast while exercising the actual SQL.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Provider guard — must run before anything from `app` is imported
# ---------------------------------------------------------------------------
#
# `app/__init__.py` calls load_dotenv() so that modules reading os.getenv (tts,
# asr) see the same .env that pydantic-settings reads. That is correct for the
# running app and wrong for tests: it hands the suite whatever real credentials
# the developer has configured, and the TTS-wired interview tests then bill a
# live provider for every question prompt they render.
#
# load_dotenv is called with override=False, so an entry already present in the
# environment wins. Setting these here — after the third-party imports but before
# the first `app` import, which is what triggers load_dotenv — pins every
# external provider off for the whole suite.
os.environ.update(
    {
        "TTS_PROVIDER": "none",
        "ASR_PROVIDER": "mock",
        "SARVAM_API_KEY": "",
        "GOOGLE_TTS_API_KEY": "",
        "GOOGLE_APPLICATION_CREDENTIALS": "",
        "WHISPER_API_URL": "",
        "WHISPER_API_KEY": "",
        "AZURE_SPEECH_KEY": "",
        "AZURE_OPENAI_ENDPOINT": "",
        "AZURE_OPENAI_API_KEY": "",
        "MAIN_LLM_API_KEY": "",
        "MAIN_LLM_ENDPOINT": "",
        "LOCAL_LLM_ENDPOINT": "",
    }
)

from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    ConsentRecord,
    Document,
    DocumentEntity,
    InterviewAnswer,
    InterviewSession,
    Patient,
    Physician,
    RedFlag,
)
from app.services.jwt import create_patient_token  # noqa: E402
from app.services.password import hash_password  # noqa: E402

PHYSICIAN_PASSWORD = "test-physician-pw"


@pytest.fixture()
def sql_db() -> Iterator[Session]:
    """A real SQLite session, isolated per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def sql_client(sql_db: Session) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        yield sql_db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def physician(sql_db: Session) -> Physician:
    doc = Physician(
        id=uuid.uuid4(),
        email="doctor@test.in",
        hashed_password=hash_password(PHYSICIAN_PASSWORD),
        full_name="Dr Test",
        role="physician",
        is_active=True,
    )
    sql_db.add(doc)
    sql_db.commit()
    return doc


@pytest.fixture()
def physician_headers(sql_client: TestClient, physician: Physician) -> dict[str, str]:
    res = sql_client.post(
        "/api/v1/auth/physician/login",
        json={"email": physician.email, "password": PHYSICIAN_PASSWORD},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture()
def seeded_patient(sql_db: Session) -> dict[str, uuid.UUID]:
    """A patient with a red-flagged interview and one abnormal lab result.

    Mirrors the Wave 4 acceptance criterion: a completed interview plus uploaded
    documents for the same patient.
    """
    pid, sid, docid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    sql_db.add_all(
        [
            Patient(
                id=pid,
                name="SYNTHETIC Kamla Devi",
                age=62,
                gender="female",
                phone="9999999999",
                preferred_language="hi",
            ),
            ConsentRecord(
                id=uuid.uuid4(),
                patient_id=pid,
                scope={"interview": True, "documents": True},
                language="hi",
                audio_confirmed=True,
            ),
            InterviewSession(
                id=sid,
                patient_id=pid,
                chief_complaint="chest_pain",
                mode="general",
                status="red_flagged",
            ),
            RedFlag(
                id=uuid.uuid4(),
                session_id=sid,
                symptom="cardiac_chest_pain_dyspnoea",
                severity="critical",
                triage_notified=False,
            ),
            Document(
                id=docid,
                patient_id=pid,
                file_uri="/tmp/lab.jpg",
                doc_type="lab_report",
                ocr_status="done",
            ),
            # is_abnormal lives on the column, not inside `value`.
            DocumentEntity(
                id=uuid.uuid4(),
                document_id=docid,
                entity_type="investigation_value",
                value={"test": "HbA1c", "value": "8.9", "unit": "%", "ref_range": "4.0-5.6"},
                is_abnormal=True,
            ),
            DocumentEntity(
                id=uuid.uuid4(),
                document_id=docid,
                entity_type="medication",
                value={"drug": "Metformin", "dose": "500mg", "frequency": "BD"},
                is_abnormal=None,
            ),
        ]
    )

    for field, value in (
        ("chief_complaint", {"answer": "chest_pain"}),
        ("hpi.site", {"answer": "central"}),
        ("hpi.onset", {"answer": "hours"}),
        ("hpi.severity", {"answer": 9}),
        ("past_medical.conditions", {"answer": ["diabetes", "hypertension"]}),
        ("allergy.known", {"skipped": True}),
    ):
        sql_db.add(
            InterviewAnswer(
                id=uuid.uuid4(),
                session_id=sid,
                field=field,
                value=value,
                input_mode="touch",
            )
        )

    sql_db.commit()
    return {"patient_id": pid, "session_id": sid, "document_id": docid}


@pytest.fixture()
def patient_headers(seeded_patient: dict[str, uuid.UUID]) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_patient_token(seeded_patient['patient_id'])}"}
