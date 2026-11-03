"""MOCK ABDM / HIS FHIR receiver — local demo only.

=============================================================================
  THIS IS NOT ABDM. It is a local endpoint that behaves like a FHIR server so
  the push path can be exercised end to end without a real Health Repository.
=============================================================================

Module D's spec allows the confirmed summary to be pushed to "either the real
ABDM sandbox or a clearly-labeled local mock endpoint that behaves like one".
This is that endpoint. It exists so the demo can show a genuine HTTP push of a
genuine FHIR R4 Bundle, rather than a function that returns "success" without
sending anything.

What it does: validates that the payload is a FHIR `document` Bundle led by a
Composition, and replies with a FHIR OperationOutcome, which is what a real FHIR
server returns.

What it does not do: consent-artefact exchange, ABDM gateway authentication,
Health Repository registration, or persistence. A real deployment points
ABDM_FHIR_ENDPOINT at an actual gateway and deletes this module.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/abdm-mock", tags=["ABDM (MOCK)"])


class MockPushAccepted(BaseModel):
    """FHIR-style OperationOutcome, plus an unmissable mock marker."""

    # camelCase is the FHIR wire format, so the field name is not ours to choose.
    resourceType: str = "OperationOutcome"  # noqa: N815
    mock: bool = True
    issue: list[dict[str, Any]]


def _outcome(severity: str, code: str, text: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "details": {"text": text}}


@router.post(
    "/fhir",
    response_model=MockPushAccepted,
    summary="MOCK ABDM FHIR receiver (not a real gateway)",
)
async def receive_fhir_bundle(bundle: dict[str, Any]):
    """Accept a FHIR document Bundle, as a real FHIR server would.

    Rejects malformed payloads so a Bundle-shape regression fails loudly here
    instead of appearing to succeed.
    """
    if bundle.get("resourceType") != "Bundle":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "resourceType": "OperationOutcome",
                "mock": True,
                "issue": [_outcome("error", "structure", "Payload is not a FHIR Bundle")],
            },
        )

    if bundle.get("type") != "document":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "resourceType": "OperationOutcome",
                "mock": True,
                "issue": [_outcome("error", "structure", "Bundle.type must be 'document'")],
            },
        )

    entries = bundle.get("entry") or []
    if not entries or entries[0].get("resource", {}).get("resourceType") != "Composition":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "resourceType": "OperationOutcome",
                "mock": True,
                "issue": [
                    _outcome(
                        "error",
                        "structure",
                        "A document Bundle must lead with a Composition entry",
                    )
                ],
            },
        )

    return MockPushAccepted(
        issue=[
            _outcome(
                "information",
                "informational",
                f"MOCK: accepted {len(entries)} entries. Nothing was stored and no "
                "real ABDM gateway was contacted.",
            )
        ]
    )
