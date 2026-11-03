"""AuthProvider interface + MOCK implementation for ABHA/Aadhaar identity lookup.

=============================================================================
  THIS ENTIRE MODULE IS A MOCK.  NO REAL ABDM / ABHA / UIDAI CALL IS MADE.
=============================================================================

Per docs/design/modules/module-d-consent-privacy-abdm.md: build against a clearly
labelled mock `AuthProvider` and document the swap-in path for the real ABDM
sandbox rather than faking a "real" ABHA lookup in the demo.

What the real implementation would add that this mock does NOT do:
  * OAuth2 / ABDM gateway handshake with client credentials
  * OTP challenge sent to the ABHA-linked mobile/email, and OTP verification
    BEFORE any session token is issued
  * Aadhaar verification via UIDAI (never by accepting a raw Aadhaar number
    over the wire the way this mock does)
  * Real demographic data returned by the ABDM gateway

Because the mock skips the OTP step, `POST /auth/abha/lookup` and
`POST /auth/aadhaar/lookup` currently issue a session token to anyone who
types a well-formed number.  That is acceptable for a local demo and is
called out in the API docs, but it MUST NOT ship to a real deployment.

To swap in the real ABDM sandbox later:
  1. Implement a class inheriting from `AuthProviderBase` (e.g.
     `AbdmSandboxAuthProvider`) that performs the real handshake + OTP flow.
  2. Return the same `IdentityLookupResult` shape.
  3. Wire it into `get_auth_provider()` when `settings.abha_sandbox_base_url`
     is set.
  No caller changes: every caller goes through `get_auth_provider()`.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class IdentityLookupResult:
    """Standard result returned by any AuthProvider implementation."""

    found: bool
    abha_id: str | None = None
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    phone: str | None = None
    # Non-reversible reference for Aadhaar. Never store or return raw Aadhaar.
    aadhaar_ref: str | None = None


def hash_aadhaar(aadhaar: str) -> str:
    """Return a non-reversible reference for an Aadhaar number.

    docs/design/03-data-model.md requires storing "a reference/hash, not raw Aadhaar".
    We keep the last 4 digits (the part routinely shown on documents, useful
    for the patient to recognise their own record) plus a salted SHA-256 of
    the full number for matching returning patients.

    NOTE: the salt is derived from JWT_SECRET for demo convenience.  A real
    deployment should use a dedicated, rotated pepper stored in a KMS/HSM.
    """
    digits = "".join(ch for ch in aadhaar if ch.isdigit())
    salt = get_settings().jwt_secret
    digest = hashlib.sha256(f"{salt}:{digits}".encode()).hexdigest()
    return f"sha256${digits[-4:]}${digest}"


def _normalise(number: str) -> str:
    """Strip spaces/hyphens so '91-1234' and '911234' compare equal."""
    return "".join(ch for ch in number if ch.isdigit())


class AuthProviderBase(ABC):
    """Interface every ABHA/Aadhaar identity provider must implement."""

    @abstractmethod
    def lookup_abha(self, abha_id: str) -> IdentityLookupResult:
        """Look up a patient by ABHA ID. Returns found=False when unknown."""
        ...

    @abstractmethod
    def lookup_aadhaar(self, aadhaar: str) -> IdentityLookupResult:
        """Look up a patient by Aadhaar number (fallback for patients with no ABHA)."""
        ...


class MockAuthProvider(AuthProviderBase):
    """MOCK provider — returns believable fake data. NOT a real integration.

    Behaviour:
      * Three pre-seeded ABHA IDs return fixed demo patients (stable for demos
        and tests).
      * Any other well-formed 14-digit ABHA ID returns a generated patient so
        the happy path always works on stage.
      * Anything malformed returns found=False.
      * Aadhaar lookup always returns found=False (no demographics available
        without UIDAI); the caller falls back to new-patient registration and
        stores only the hashed Aadhaar reference.
    """

    _MOCK_DB: dict[str, IdentityLookupResult] = {
        "91123456789012": IdentityLookupResult(
            found=True,
            abha_id="91-1234-5678-9012",
            name="Ramesh Kumar",
            age=45,
            gender="male",
            phone="9876543210",
        ),
        "91987654321098": IdentityLookupResult(
            found=True,
            abha_id="91-9876-5432-1098",
            name="Priya Sharma",
            age=32,
            gender="female",
            phone="8765432109",
        ),
        "91555566667777": IdentityLookupResult(
            found=True,
            abha_id="91-5555-6666-7777",
            name="Anil Verma",
            age=60,
            gender="male",
            phone="7654321098",
        ),
    }

    def lookup_abha(self, abha_id: str) -> IdentityLookupResult:
        digits = _normalise(abha_id)

        seeded = self._MOCK_DB.get(digits)
        if seeded is not None:
            return seeded

        # MOCK: generate a believable patient for any other valid-shaped ABHA ID
        # so the demo never dead-ends. A real provider would return not-found.
        if len(digits) == 14:
            return IdentityLookupResult(
                found=True,
                abha_id=abha_id,
                name=f"Patient {digits[-4:]}",
                age=35,
                gender="other",
                phone=f"9{digits[-9:]}",
            )

        return IdentityLookupResult(found=False)

    def lookup_aadhaar(self, aadhaar: str) -> IdentityLookupResult:
        """MOCK: Aadhaar never resolves to demographics.

        Real Aadhaar verification requires UIDAI e-KYC, which we do not have.
        We validate the shape (12 digits), return the hashed reference so the
        caller can create/find a patient record, and report found=False so the
        UI routes the patient into the registration form.
        """
        digits = _normalise(aadhaar)
        if len(digits) != 12:
            return IdentityLookupResult(found=False)
        return IdentityLookupResult(found=False, aadhaar_ref=hash_aadhaar(digits))


# ---------------------------------------------------------------------------
# Factory — the only function callers should use
# ---------------------------------------------------------------------------


def get_auth_provider() -> AuthProviderBase:
    """Return the configured AuthProvider.

    Currently always the mock.  When a real `AbdmSandboxAuthProvider` exists,
    return it here when `settings.abha_sandbox_base_url` is set.
    """
    settings = get_settings()
    if settings.abha_sandbox_base_url:
        # TODO(phase-4/6): return AbdmSandboxAuthProvider(settings.abha_sandbox_base_url)
        # Falling through to the mock on purpose: no real client exists yet, and
        # silently pretending to be real would be worse than being obviously mocked.
        pass
    return MockAuthProvider()
