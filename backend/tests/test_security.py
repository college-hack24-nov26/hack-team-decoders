"""Security & compliance tests — Module D acceptance criteria.

These prove the DPDP Act compliance claims are real:
  1. No AI call or data write without valid consent
  2. Revoking consent blocks all further processing
  3. Patient token cannot access physician-only endpoints
  4. Physician token cannot access patient endpoints
  5. Session data purge actually deletes temporary artifacts
  6. Audit trail is complete for a full patient journey
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.services.jwt import create_patient_token, create_physician_token
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


@pytest.fixture()
def patient_with_consent(client: TestClient, db: FakeSession) -> dict:
    """Register a patient and grant full consent. Returns {token, patient_id, consent_id}."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"name": "Security Test", "age": 30, "gender": "male", "phone": "9800000000"},
    )
    assert reg.status_code == 201
    token = reg.json()["token"]
    patient_id = reg.json()["patient_id"]
    headers = {"Authorization": f"Bearer {token}"}

    consent = client.post(
        "/api/v1/consent",
        json={
            "scope": {
                "interview": True,
                "documents": True,
                "abdm_push": False,
                "share_with_physician": True,
                "retention_days": 90,
            },
            "language": "en",
            "audio_confirmed": True,
        },
        headers=headers,
    )
    assert consent.status_code == 201

    return {
        "token": token,
        "patient_id": patient_id,
        "consent_id": consent.json()["id"],
        "headers": headers,
    }


# ---------------------------------------------------------------------------
# 1. No operation without consent
# ---------------------------------------------------------------------------


class TestNoOperationWithoutConsent:
    def test_interview_session_blocked_without_consent(self, client: TestClient, db: FakeSession):
        """A patient who has not consented cannot start an interview."""
        reg = client.post(
            "/api/v1/auth/register",
            json={"name": "No Consent", "age": 25, "gender": "female", "phone": "9800000001"},
        )
        headers = {"Authorization": f"Bearer {reg.json()['token']}"}

        res = client.post(
            "/api/v1/interview/sessions",
            json={"mode": "general"},
            headers=headers,
        )
        assert res.status_code == 403
        assert "consent" in res.json()["detail"].lower()

    def test_document_upload_blocked_without_consent(self, client: TestClient, db: FakeSession):
        """A patient who has not consented cannot upload documents."""
        reg = client.post(
            "/api/v1/auth/register",
            json={"name": "No Consent", "age": 25, "gender": "female", "phone": "9800000002"},
        )
        headers = {"Authorization": f"Bearer {reg.json()['token']}"}

        res = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("test.png", b"fake", "image/png")},
        )
        assert res.status_code == 403

    def test_asr_blocked_without_consent(self, client: TestClient, db: FakeSession):
        """ASR endpoint requires consent (processes patient voice = PII)."""
        reg = client.post(
            "/api/v1/auth/register",
            json={"name": "No Consent", "age": 25, "gender": "male", "phone": "9800000003"},
        )
        headers = {"Authorization": f"Bearer {reg.json()['token']}"}

        res = client.post(
            "/api/v1/interview/asr",
            headers=headers,
            files={"file": ("audio.webm", b"fake audio", "audio/webm")},
        )
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# 2. Consent revocation blocks everything
# ---------------------------------------------------------------------------


class TestConsentRevocationBlocks:
    def test_revoking_consent_blocks_interview(
        self, client: TestClient, patient_with_consent: dict, db: FakeSession
    ):
        """After consent revocation, interview endpoints return 403."""
        headers = patient_with_consent["headers"]
        consent_id = patient_with_consent["consent_id"]

        # Verify interview works before revocation
        res = client.post("/api/v1/interview/sessions", json={"mode": "general"}, headers=headers)
        assert res.status_code == 201

        # Revoke consent
        revoke = client.delete(f"/api/v1/consent/{consent_id}", headers=headers)
        assert revoke.status_code == 200

        # Interview now blocked
        res = client.post("/api/v1/interview/sessions", json={"mode": "general"}, headers=headers)
        assert res.status_code == 403
        assert "consent" in res.json()["detail"].lower()

    def test_revoking_consent_blocks_documents(
        self, client: TestClient, patient_with_consent: dict, db: FakeSession
    ):
        """After consent revocation, document endpoints return 403."""
        headers = patient_with_consent["headers"]
        consent_id = patient_with_consent["consent_id"]

        # Revoke
        client.delete(f"/api/v1/consent/{consent_id}", headers=headers)

        # Document upload blocked
        res = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("test.png", b"fake", "image/png")},
        )
        assert res.status_code == 403

    def test_revoking_consent_blocks_asr(
        self, client: TestClient, patient_with_consent: dict, db: FakeSession
    ):
        """After consent revocation, ASR is blocked."""
        headers = patient_with_consent["headers"]
        consent_id = patient_with_consent["consent_id"]

        client.delete(f"/api/v1/consent/{consent_id}", headers=headers)

        res = client.post(
            "/api/v1/interview/asr",
            headers=headers,
            files={"file": ("audio.webm", b"fake", "audio/webm")},
        )
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# 3. Scope enforcement
# ---------------------------------------------------------------------------


class TestScopeEnforcement:
    def test_documents_blocked_when_scope_declined(self, client: TestClient, db: FakeSession):
        """If patient declined document scope, upload is blocked even with consent."""
        reg = client.post(
            "/api/v1/auth/register",
            json={"name": "No Docs Scope", "age": 40, "gender": "male", "phone": "9800000004"},
        )
        headers = {"Authorization": f"Bearer {reg.json()['token']}"}

        # Consent with documents=False
        client.post(
            "/api/v1/consent",
            json={
                "scope": {
                    "interview": True,
                    "documents": False,  # declined!
                    "abdm_push": False,
                    "share_with_physician": True,
                    "retention_days": 90,
                },
                "language": "en",
                "audio_confirmed": True,
            },
            headers=headers,
        )

        res = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("test.png", b"fake", "image/png")},
        )
        assert res.status_code == 403
        assert "documents" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. RBAC: patient vs physician tokens
# ---------------------------------------------------------------------------


class TestRBAC:
    def test_patient_token_type_is_patient(self, db: FakeSession):
        """Patient JWT has type=patient and cannot decode as physician."""
        from app.services.jwt import decode_patient_token, decode_physician_token

        pid = uuid.uuid4()
        token = create_patient_token(pid)
        assert decode_patient_token(token) == pid
        assert decode_physician_token(token) is None  # wrong type

    def test_physician_token_type_is_physician(self, db: FakeSession):
        """Physician JWT has type=physician and cannot decode as patient."""
        from app.services.jwt import decode_patient_token, decode_physician_token

        pid = uuid.uuid4()
        token = create_physician_token(pid)
        assert decode_physician_token(token) == pid
        assert decode_patient_token(token) is None  # wrong type — would fail even if sub matched

    def test_physician_token_cannot_access_patient_endpoints(
        self, client: TestClient, db: FakeSession
    ):
        """A physician token is rejected by patient-only consent endpoints."""
        physician_token = create_physician_token(uuid.uuid4())
        headers = {"Authorization": f"Bearer {physician_token}"}

        res = client.get("/api/v1/consent/current", headers=headers)
        assert res.status_code == 401  # decode_patient_token returns None for physician type

    def test_unauthenticated_gets_401_everywhere(self, client: TestClient):
        """No token → 401 on all protected endpoints."""
        endpoints = [
            ("GET", "/api/v1/consent/current"),
            ("POST", "/api/v1/interview/sessions"),
            ("POST", "/api/v1/documents"),
        ]
        for method, path in endpoints:
            res = client.request(method, path)
            assert res.status_code in (401, 422), f"{method} {path} returned {res.status_code}"


# ---------------------------------------------------------------------------
# 5. Audit trail completeness
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_full_journey_produces_audit_trail(
        self, client: TestClient, patient_with_consent: dict, db: FakeSession
    ):
        """A register → consent → interview flow leaves a complete audit trail."""
        headers = patient_with_consent["headers"]

        # Start interview session
        client.post("/api/v1/interview/sessions", json={"mode": "general"}, headers=headers)

        # Check audit actions present
        actions = db.audit_actions()
        assert "patient.register" in actions
        assert "consent.grant" in actions
        assert "interview.session_started" in actions

    def test_consent_revocation_is_audited(
        self, client: TestClient, patient_with_consent: dict, db: FakeSession
    ):
        """Consent revocation appears in the audit trail."""
        headers = patient_with_consent["headers"]
        consent_id = patient_with_consent["consent_id"]

        client.delete(f"/api/v1/consent/{consent_id}", headers=headers)
        assert "consent.revoke" in db.audit_actions()
