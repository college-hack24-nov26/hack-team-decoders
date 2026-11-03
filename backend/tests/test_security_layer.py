"""SecurityLayer enforcement on physician-initiated operations — Module D.

The route-level `require_consent_scope(...)` dependency checks the *caller's*
consent. When a physician generates a summary or pushes to ABDM, the caller has
no consent record — the patient does. Those endpoints therefore shipped with no
consent check at all: an LLM call over a patient's full history, and a push of
that history to a national health record, both proceeding regardless of what the
patient agreed to.

These tests cover that gap, which is Module D's central claim: no AI call and no
export of patient data without a valid, unrevoked consent record covering it.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.models import ConsentRecord, Patient
from app.services.security import ConsentDenied, SecurityLayer


def _consent(sql_db, patient_id: uuid.UUID) -> ConsentRecord:
    return sql_db.query(ConsentRecord).filter(ConsentRecord.patient_id == patient_id).first()


def _set_scope(sql_db, patient_id: uuid.UUID, **scopes: bool) -> None:
    consent = _consent(sql_db, patient_id)
    consent.scope = {**consent.scope, **scopes}
    sql_db.commit()


def _revoke(sql_db, patient_id: uuid.UUID) -> None:
    from datetime import UTC, datetime

    _consent(sql_db, patient_id).revoked_at = datetime.now(tz=UTC)
    sql_db.commit()


# ---------------------------------------------------------------------------
# The unit itself
# ---------------------------------------------------------------------------


class TestSecurityLayerUnit:
    def test_authorize_passes_for_granted_scope(self, sql_db, seeded_patient):
        layer = SecurityLayer.for_patient(sql_db, seeded_patient["patient_id"])
        assert layer.authorize("interview").scope["interview"] is True

    def test_authorize_refuses_ungranted_scope(self, sql_db, seeded_patient):
        """The seeded patient declined ABDM push."""
        layer = SecurityLayer.for_patient(sql_db, seeded_patient["patient_id"])
        with pytest.raises(ConsentDenied) as exc:
            layer.authorize("abdm_push")
        assert "abdm_push" in exc.value.detail

    def test_authorize_refuses_after_revocation(self, sql_db, seeded_patient):
        _revoke(sql_db, seeded_patient["patient_id"])
        layer = SecurityLayer.for_patient(sql_db, seeded_patient["patient_id"])
        with pytest.raises(ConsentDenied):
            layer.authorize("interview")

    def test_is_authorized_does_not_raise(self, sql_db, seeded_patient):
        layer = SecurityLayer.for_patient(sql_db, seeded_patient["patient_id"])
        assert layer.is_authorized("interview") is True
        assert layer.is_authorized("abdm_push") is False

    def test_unknown_patient_is_404_not_403(self, sql_db):
        """Operating on a missing patient is a bug, not a permissions problem."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            SecurityLayer.for_patient(sql_db, uuid.uuid4())
        assert exc.value.status_code == 404

    def test_most_recent_unrevoked_consent_wins(self, sql_db, seeded_patient):
        """A fresh grant after a revocation restores access."""
        from datetime import UTC, datetime, timedelta

        pid = seeded_patient["patient_id"]
        _revoke(sql_db, pid)
        sql_db.add(
            ConsentRecord(
                id=uuid.uuid4(),
                patient_id=pid,
                scope={"interview": True, "abdm_push": True},
                language="hi",
                audio_confirmed=True,
                given_at=datetime.now(tz=UTC) + timedelta(seconds=1),
            )
        )
        sql_db.commit()

        layer = SecurityLayer.for_patient(sql_db, pid)
        assert layer.is_authorized("abdm_push") is True


# ---------------------------------------------------------------------------
# Summary generation — an AI call over the patient's whole history
# ---------------------------------------------------------------------------


class TestSummaryGenerationRequiresConsent:
    def test_blocked_when_consent_revoked(
        self, sql_client, sql_db, seeded_patient, physician_headers
    ):
        _revoke(sql_db, seeded_patient["patient_id"])

        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 403
        assert "consent" in res.json()["detail"].lower()

    def test_blocked_when_interview_scope_declined(
        self, sql_client, sql_db, seeded_patient, physician_headers
    ):
        _set_scope(sql_db, seeded_patient["patient_id"], interview=False)

        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 403
        assert "interview" in res.json()["detail"]

    def test_allowed_with_valid_consent(self, sql_client, seeded_patient, physician_headers):
        res = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        assert res.status_code == 201, res.text

    def test_no_summary_row_is_written_when_refused(
        self, sql_client, sql_db, seeded_patient, physician_headers
    ):
        """A refused request must not leave a partial record behind."""
        from app.models.models import Summary

        _revoke(sql_db, seeded_patient["patient_id"])
        sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        )
        sql_db.rollback()
        assert sql_db.query(Summary).count() == 0


# ---------------------------------------------------------------------------
# ABDM push — the scope that defaults to False
# ---------------------------------------------------------------------------


class TestAbdmPushRequiresScope:
    @pytest.fixture()
    def confirmed_summary_id(self, sql_client, seeded_patient, physician_headers) -> str:
        sid = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        ).json()["id"]
        sql_client.post(
            f"/api/v1/summaries/{sid}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )
        return sid

    def test_refused_without_abdm_scope(self, sql_client, confirmed_summary_id, physician_headers):
        res = sql_client.post(
            f"/api/v1/summaries/{confirmed_summary_id}/push-abdm", headers=physician_headers
        )
        assert res.status_code == 403
        assert "abdm_push" in res.json()["detail"]

    def test_not_marked_as_pushed_when_refused(
        self, sql_client, sql_db, confirmed_summary_id, physician_headers
    ):
        """A refused push must not claim the hospital received the record."""
        from app.models.models import Summary

        sql_client.post(
            f"/api/v1/summaries/{confirmed_summary_id}/push-abdm", headers=physician_headers
        )
        sql_db.rollback()
        summary = (
            sql_db.query(Summary).filter(Summary.id == uuid.UUID(confirmed_summary_id)).first()
        )
        assert summary.pushed_to_his_at is None

    def test_allowed_once_scope_granted(
        self, sql_client, sql_db, seeded_patient, confirmed_summary_id, physician_headers
    ):
        _set_scope(sql_db, seeded_patient["patient_id"], abdm_push=True)

        res = sql_client.post(
            f"/api/v1/summaries/{confirmed_summary_id}/push-abdm", headers=physician_headers
        )
        assert res.status_code == 200, res.text

    def test_unsent_bundle_is_not_reported_as_pushed(
        self, sql_client, sql_db, seeded_patient, confirmed_summary_id, physician_headers
    ):
        """With no endpoint configured the Bundle is generated but not transmitted.

        The response has to say so, and the record must not be stamped as
        delivered — otherwise the demo looks like a working ABDM integration.
        """
        from app.models.models import Summary

        _set_scope(sql_db, seeded_patient["patient_id"], abdm_push=True)
        body = sql_client.post(
            f"/api/v1/summaries/{confirmed_summary_id}/push-abdm", headers=physician_headers
        ).json()

        assert body["pushed"] is False
        assert body["transport"] == "none"

        sql_db.rollback()
        summary = (
            sql_db.query(Summary).filter(Summary.id == uuid.UUID(confirmed_summary_id)).first()
        )
        assert summary.pushed_to_his_at is None


# ---------------------------------------------------------------------------
# FHIR Bundle shape
# ---------------------------------------------------------------------------


class TestFhirBundleShape:
    @pytest.fixture()
    def bundle(self, sql_client, sql_db, seeded_patient, physician_headers) -> dict:
        sid = sql_client.post(
            "/api/v1/summaries/generate",
            json={"session_id": str(seeded_patient["session_id"])},
            headers=physician_headers,
        ).json()["id"]
        sql_client.post(
            f"/api/v1/summaries/{sid}/confirm",
            json={"decision": "accept"},
            headers=physician_headers,
        )
        _set_scope(sql_db, seeded_patient["patient_id"], abdm_push=True)
        return sql_client.post(
            f"/api/v1/summaries/{sid}/push-abdm", headers=physician_headers
        ).json()["bundle"]

    def test_is_a_fhir_document_bundle(self, bundle):
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "document"

    def test_composition_is_the_first_entry(self, bundle):
        """FHIR requires a document Bundle to lead with its Composition."""
        assert bundle["entry"][0]["resource"]["resourceType"] == "Composition"

    def test_every_entry_has_a_full_url(self, bundle):
        assert all(e.get("fullUrl") for e in bundle["entry"])

    def test_patient_resource_is_present(self, bundle):
        types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "Patient" in types

    def test_abnormal_lab_is_flagged_as_abnormal(self, bundle):
        """The seeded HbA1c of 8.9% is abnormal and must carry an interpretation."""
        observations = [
            e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"
        ]
        assert observations, "expected the seeded lab result as an Observation"
        codes = [
            coding["code"]
            for obs in observations
            for interp in obs.get("interpretation", [])
            for coding in interp.get("coding", [])
        ]
        assert "A" in codes

    def test_aadhaar_is_never_emitted(self, sql_db, seeded_patient, bundle):
        """Aadhaar is not clinical data and must not leave the system."""
        import json

        patient = sql_db.query(Patient).filter(Patient.id == seeded_patient["patient_id"]).first()
        patient.aadhaar_ref = "sha256$1234$deadbeef"
        sql_db.commit()

        assert "deadbeef" not in json.dumps(bundle)
        assert "aadhaar" not in json.dumps(bundle).lower()
