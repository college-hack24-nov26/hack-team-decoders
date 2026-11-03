"""Tests for consent capture, revocation, and enforcement.

The important assertion here is the Phase 1 acceptance criterion:
*nothing past the consent step is reachable without a valid, current consent
record* — enforced server-side, not just by the frontend router.
"""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.dependencies import (
    ConsentedPatient,
    require_consent_scope,
)
from app.main import app
from app.models.models import ConsentRecord, Patient
from tests.fake_db import FakeSession

VALID_SCOPE = {
    "interview": True,
    "documents": True,
    "abdm_push": False,
    "share_with_physician": True,
    "retention_days": 90,
}


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
def auth(client: TestClient) -> dict[str, str]:
    """Register a patient and return an Authorization header for them."""
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "Consent Tester", "age": 38, "gender": "female", "phone": "9811111111"},
    )
    assert res.status_code == 201
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _grant(client: TestClient, auth: dict[str, str], **overrides):
    payload = {
        "scope": {**VALID_SCOPE, **overrides.pop("scope", {})},
        "language": "hi",
        "audio_confirmed": True,
    }
    payload.update(overrides)
    return client.post("/api/v1/consent", json=payload, headers=auth)


# ---------------------------------------------------------------------------
# POST /consent
# ---------------------------------------------------------------------------


def test_consent_requires_authentication(client: TestClient):
    res = client.post(
        "/api/v1/consent",
        json={"scope": VALID_SCOPE, "language": "en", "audio_confirmed": True},
    )
    assert res.status_code == 401


def test_consent_is_stored_with_scope_language_and_audio_flag(
    client: TestClient, auth: dict[str, str], db: FakeSession
):
    res = _grant(client, auth)
    assert res.status_code == 201
    body = res.json()
    assert body["language"] == "hi"
    assert body["audio_confirmed"] is True
    assert body["scope"]["interview"] is True
    assert body["scope"]["abdm_push"] is False

    stored = db.rows_of(ConsentRecord)
    assert len(stored) == 1
    assert stored[0].scope["retention_days"] == 90
    assert stored[0].revoked_at is None


def test_consent_accepted_without_audio_but_records_it(
    client: TestClient, auth: dict[str, str], db
):
    """Unheard audio is recorded, not rejected.

    Ticking each scope is the affirmation; the narration is how the terms reach a
    patient who cannot read them. Refusing the consent because playback did not
    finish punished the literate patient in a queue without making the other
    patient any better informed — and it desynced from the UI, which had already
    stopped requiring it, so a Continue button that looked enabled returned 400.

    What still matters is that the record is honest about how the terms were
    conveyed, so an audit can tell the two cases apart. That is what this asserts.
    """
    res = _grant(client, auth, audio_confirmed=False)

    assert res.status_code == 201
    assert res.json()["audio_confirmed"] is False

    stored = db.rows_of(ConsentRecord)
    assert len(stored) == 1
    assert stored[0].audio_confirmed is False


def test_consent_rejected_when_mandatory_scope_declined(client: TestClient, auth: dict[str, str]):
    res = _grant(client, auth, scope={"interview": False})
    assert res.status_code == 400


def test_optional_scopes_may_be_declined(client: TestClient, auth: dict[str, str]):
    res = _grant(client, auth, scope={"documents": False, "abdm_push": False})
    assert res.status_code == 201


def test_consent_grant_is_audited(client: TestClient, auth: dict[str, str], db: FakeSession):
    _grant(client, auth)
    assert "consent.grant" in db.audit_actions()


def test_audit_entry_records_patient_but_not_physician_fk(
    client: TestClient, auth: dict[str, str], db: FakeSession
):
    _grant(client, auth)
    entry = next(e for e in db.audit_entries() if e.action == "consent.grant")
    assert entry.actor_id is None  # FK targets physicians; patients go in detail
    assert entry.detail["patient_id"] == str(db.rows_of(Patient)[0].id)


# ---------------------------------------------------------------------------
# GET /consent/current
# ---------------------------------------------------------------------------


def test_current_consent_inactive_before_granting(client: TestClient, auth: dict[str, str]):
    res = client.get("/api/v1/consent/current", headers=auth)
    assert res.status_code == 200
    assert res.json()["active"] is False


def test_current_consent_active_after_granting(client: TestClient, auth: dict[str, str]):
    _grant(client, auth)
    res = client.get("/api/v1/consent/current", headers=auth)
    assert res.status_code == 200
    assert res.json()["active"] is True
    assert res.json()["scope"]["interview"] is True


# ---------------------------------------------------------------------------
# DELETE /consent/{id}
# ---------------------------------------------------------------------------


def test_revoke_marks_consent_revoked_and_audits(
    client: TestClient, auth: dict[str, str], db: FakeSession
):
    consent_id = _grant(client, auth).json()["id"]

    res = client.delete(f"/api/v1/consent/{consent_id}", headers=auth)
    assert res.status_code == 200
    assert res.json()["revoked_at"]
    assert db.rows_of(ConsentRecord)[0].revoked_at is not None
    assert "consent.revoke" in db.audit_actions()


def test_revoked_consent_is_no_longer_current(client: TestClient, auth: dict[str, str]):
    consent_id = _grant(client, auth).json()["id"]
    client.delete(f"/api/v1/consent/{consent_id}", headers=auth)

    res = client.get("/api/v1/consent/current", headers=auth)
    assert res.json()["active"] is False


def test_double_revoke_conflicts(client: TestClient, auth: dict[str, str]):
    consent_id = _grant(client, auth).json()["id"]
    client.delete(f"/api/v1/consent/{consent_id}", headers=auth)
    res = client.delete(f"/api/v1/consent/{consent_id}", headers=auth)
    assert res.status_code == 409


def test_cannot_revoke_another_patients_consent(client: TestClient, auth: dict[str, str]):
    consent_id = _grant(client, auth).json()["id"]

    other = client.post(
        "/api/v1/auth/register",
        json={"name": "Someone Else", "age": 22, "gender": "male", "phone": "9822222222"},
    ).json()
    other_auth = {"Authorization": f"Bearer {other['token']}"}

    res = client.delete(f"/api/v1/consent/{consent_id}", headers=other_auth)
    assert res.status_code == 404


def test_revoke_rejects_malformed_id(client: TestClient, auth: dict[str, str]):
    res = client.delete("/api/v1/consent/not-a-uuid", headers=auth)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# The gate itself: require_valid_consent / require_consent_scope
#
# Nothing in Phase 1 consumes these yet, so we mount a probe app that uses them
# exactly the way Module A (Phase 2) will.
# ---------------------------------------------------------------------------


@pytest.fixture()
def gated(db: FakeSession):
    """A probe app whose routes are protected by the consent dependencies."""
    probe = FastAPI()

    @probe.get("/gated/any")
    def any_consent(patient: ConsentedPatient):
        return {"patient": patient.name}

    @probe.get("/gated/documents")
    def documents_scope(
        patient: Annotated[Patient, Depends(require_consent_scope("documents"))],
    ):
        return {"patient": patient.name}

    @probe.get("/gated/abdm")
    def abdm_scope(
        patient: Annotated[Patient, Depends(require_consent_scope("abdm_push"))],
    ):
        return {"patient": patient.name}

    def override_get_db():
        yield db

    probe.dependency_overrides[get_db] = override_get_db
    with TestClient(probe) as c:
        yield c


def test_gate_blocks_unauthenticated_request(gated: TestClient):
    assert gated.get("/gated/any").status_code == 401


def test_gate_blocks_authenticated_patient_without_consent(
    gated: TestClient, client: TestClient, auth: dict[str, str]
):
    """A logged-in patient who has not consented cannot pass the gate."""
    res = gated.get("/gated/any", headers=auth)
    assert res.status_code == 403
    assert "consent" in res.json()["detail"].lower()


def test_gate_allows_patient_with_valid_consent(
    gated: TestClient, client: TestClient, auth: dict[str, str]
):
    _grant(client, auth)
    res = gated.get("/gated/any", headers=auth)
    assert res.status_code == 200
    assert res.json()["patient"] == "Consent Tester"


def test_gate_blocks_again_after_revocation(
    gated: TestClient, client: TestClient, auth: dict[str, str]
):
    """Revoking consent must immediately halt further processing."""
    consent_id = _grant(client, auth).json()["id"]
    assert gated.get("/gated/any", headers=auth).status_code == 200

    client.delete(f"/api/v1/consent/{consent_id}", headers=auth)
    assert gated.get("/gated/any", headers=auth).status_code == 403


def test_scope_gate_allows_granted_scope(
    gated: TestClient, client: TestClient, auth: dict[str, str]
):
    _grant(client, auth)  # documents=True by default
    assert gated.get("/gated/documents", headers=auth).status_code == 200


def test_scope_gate_blocks_declined_scope(
    gated: TestClient, client: TestClient, auth: dict[str, str]
):
    """abdm_push is declined by default, so an ABDM push must be refused."""
    _grant(client, auth)
    res = gated.get("/gated/abdm", headers=auth)
    assert res.status_code == 403
    assert "abdm_push" in res.json()["detail"]


def test_gate_rejects_garbage_token(gated: TestClient):
    res = gated.get("/gated/any", headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401
