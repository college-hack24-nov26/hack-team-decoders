"""Tests for the Phase 1 auth endpoints.

These run without Docker: the DB session is replaced with an in-memory fake
that mimics the small slice of the SQLAlchemy Session API the routes use.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.models import Patient
from app.services.auth_provider import hash_aadhaar
from app.services.jwt import decode_patient_token
from tests.fake_db import FakeSession


@pytest.fixture()
def db() -> FakeSession:
    return FakeSession()


@pytest.fixture()
def client(db: FakeSession):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /languages
# ---------------------------------------------------------------------------


def test_languages_lists_english_and_hindi(client: TestClient):
    res = client.get("/api/v1/languages")
    assert res.status_code == 200
    codes = [item["code"] for item in res.json()["languages"]]
    assert "en" in codes
    assert "hi" in codes


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


def test_register_creates_patient_and_returns_usable_token(client: TestClient, db: FakeSession):
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Sunita Devi",
            "age": 41,
            "gender": "female",
            "phone": "9812345678",
            "preferred_language": "hi",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Sunita Devi"

    # The token must decode back to the created patient.
    assert decode_patient_token(body["token"]) == uuid.UUID(body["patient_id"])

    patients = db.rows_of(Patient)
    assert len(patients) == 1
    assert patients[0].preferred_language == "hi"


def test_register_rejects_invalid_gender(client: TestClient):
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "X", "age": 30, "gender": "unknown", "phone": "9812345678"},
    )
    assert res.status_code == 422


def test_register_never_stores_raw_aadhaar(client: TestClient, db: FakeSession):
    raw = "123412341234"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Aadhaar Patient",
            "age": 50,
            "gender": "male",
            "phone": "9800000000",
            "aadhaar": raw,
        },
    )
    assert res.status_code == 201

    stored = db.rows_of(Patient)[0].aadhaar_ref
    assert stored is not None
    assert raw not in stored
    assert stored.startswith("sha256$")
    assert stored == hash_aadhaar(raw)


def test_register_is_audited(client: TestClient, db: FakeSession):
    client.post(
        "/api/v1/auth/register",
        json={"name": "Audited", "age": 20, "gender": "other", "phone": "9800000001"},
    )
    assert "patient.register" in db.audit_actions()


# ---------------------------------------------------------------------------
# POST /auth/abha/lookup  (MOCK provider)
# ---------------------------------------------------------------------------


def test_abha_lookup_returns_seeded_mock_patient(client: TestClient):
    res = client.post("/api/v1/auth/abha/lookup", json={"abha_id": "91-1234-5678-9012"})
    assert res.status_code == 200
    body = res.json()
    assert body["found"] is True
    assert body["name"] == "Ramesh Kumar"
    assert body["token"]


def test_abha_lookup_rejects_malformed_id(client: TestClient, db: FakeSession):
    res = client.post("/api/v1/auth/abha/lookup", json={"abha_id": "not-an-abha"})
    assert res.status_code == 200
    assert res.json()["found"] is False
    assert res.json()["token"] is None
    assert "auth.abha_lookup.not_found" in db.audit_actions()


def test_abha_lookup_reuses_existing_patient(client: TestClient, db: FakeSession):
    first = client.post("/api/v1/auth/abha/lookup", json={"abha_id": "91-9876-5432-1098"})
    second = client.post("/api/v1/auth/abha/lookup", json={"abha_id": "91-9876-5432-1098"})

    assert first.json()["patient_id"] == second.json()["patient_id"]
    assert len(db.rows_of(Patient)) == 1


# ---------------------------------------------------------------------------
# POST /auth/aadhaar/lookup  (MOCK provider — no UIDAI e-KYC)
# ---------------------------------------------------------------------------


def test_aadhaar_lookup_reports_not_found_for_unknown_number(client: TestClient):
    res = client.post("/api/v1/auth/aadhaar/lookup", json={"aadhaar": "999988887777"})
    assert res.status_code == 200
    assert res.json()["found"] is False


def test_aadhaar_lookup_resumes_a_returning_patient(client: TestClient):
    raw = "111122223333"
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Returning Patient",
            "age": 33,
            "gender": "male",
            "phone": "9700000000",
            "aadhaar": raw,
        },
    )

    res = client.post("/api/v1/auth/aadhaar/lookup", json={"aadhaar": raw})
    assert res.status_code == 200
    assert res.json()["found"] is True
    assert res.json()["name"] == "Returning Patient"
    assert res.json()["token"]


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


def test_login_issues_token_for_existing_patient(client: TestClient):
    created = client.post(
        "/api/v1/auth/register",
        json={"name": "Login Test", "age": 25, "gender": "female", "phone": "9700000002"},
    ).json()

    res = client.post("/api/v1/auth/login", json={"patient_id": created["patient_id"]})
    assert res.status_code == 200
    assert decode_patient_token(res.json()["token"]) == uuid.UUID(created["patient_id"])


def test_login_404_for_unknown_patient(client: TestClient):
    res = client.post("/api/v1/auth/login", json={"patient_id": str(uuid.uuid4())})
    assert res.status_code == 404


def test_login_400_for_malformed_patient_id(client: TestClient):
    res = client.post("/api/v1/auth/login", json={"patient_id": "not-a-uuid"})
    assert res.status_code == 400
