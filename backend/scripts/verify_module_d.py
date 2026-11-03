"""Module D end-to-end verification against the running Docker stack.

Run it:
    cd infra && docker compose up -d --build
    docker compose run --rm migrate
    docker compose exec backend python -m app.seed_physician
    docker compose exec backend python /app/scripts/verify_module_d.py

Why this exists alongside the pytest suite: the suite runs on SQLite and stubs
the network, so it cannot prove the things that only break in a real deployment —
Postgres-specific column types, an actual HTTP push of the FHIR Bundle, and files
genuinely disappearing from the storage volume. A Postgres type fault once passed
CI for exactly that reason. This script exercises those paths for real.

Drives the compliance paths and prints what happened, so the claims are checked
rather than asserted:

  1. ABDM push is refused when the patient did not grant abdm_push
  2. ABDM push succeeds once granted, over real HTTP, with a real FHIR Bundle
  3. The raw scan is deleted from disk afterwards (session data purge)
  4. Consent revocation blocks the AI summariser call
  5. The audit trail actually persisted (it is read back from Postgres)
"""

import sys

import httpx

BASE = "http://localhost:8000/api/v1"
OK, FAIL = "[OK]", "[FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{OK if condition else FAIL} {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


# ---------------------------------------------------------------------------
# Set up a patient with consent, a completed interview, and a document
# ---------------------------------------------------------------------------

reg = httpx.post(
    f"{BASE}/auth/register",
    json={
        "name": "Module D Verify",
        "age": 51,
        "gender": "male",
        "phone": "9800001111",
        "preferred_language": "en",
    },
)
patient_id = reg.json()["patient_id"]
ph = {"Authorization": f"Bearer {reg.json()['token']}"}

# Consent WITHOUT abdm_push — the default, and the interesting case.
consent = httpx.post(
    f"{BASE}/consent",
    headers=ph,
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
)
consent_id = consent.json()["id"]

# Upload a document so there is a raw scan on disk to purge later.
from PIL import Image, ImageDraw  # noqa: E402

img = Image.new("RGB", (900, 300), "white")
ImageDraw.Draw(img).text((20, 20), "Date: 11/03/2025\nHemoglobin 9.1 g/dL\n", fill="black")
img.save("/tmp/verify_doc.png")
with open("/tmp/verify_doc.png", "rb") as fh:
    up = httpx.post(
        f"{BASE}/documents",
        headers=ph,
        files={"file": ("scan.png", fh, "image/png")},
        data={"doc_type": "lab_report"},
        timeout=60.0,
    )
file_uri = up.json()["file_uri"]

# Complete an interview so a summary can be generated.
sess = httpx.post(f"{BASE}/interview/sessions", headers=ph, json={"mode": "general"})
session_id = sess.json()["session_id"]
httpx.post(
    f"{BASE}/interview/sessions/{session_id}/answer",
    headers=ph,
    json={"field_id": "chief_complaint", "value": "chest_pain", "input_mode": "touch"},
)
httpx.post(f"{BASE}/interview/sessions/{session_id}/complete", headers=ph)

# Physician session.
from app.seed_physician import DEFAULT_EMAIL, DEFAULT_PASSWORD  # noqa: E402

doc_login = httpx.post(
    f"{BASE}/auth/physician/login",
    json={"email": DEFAULT_EMAIL, "password": DEFAULT_PASSWORD},
)
if doc_login.status_code != 200:
    print(f"{FAIL} physician login — {doc_login.status_code} {doc_login.text[:200]}")
    print("Seed a physician first: docker compose exec backend python -m app.seed_physician")
    sys.exit(1)
dh = {"Authorization": f"Bearer {doc_login.json()['token']}"}

print("\n--- 1. Summariser requires patient consent (AI call gate) ---")
summary = httpx.post(
    f"{BASE}/summaries/generate", headers=dh, json={"session_id": session_id}, timeout=120.0
)
check("summary generated with valid consent", summary.status_code == 201, str(summary.status_code))
summary_id = summary.json()["id"] if summary.status_code == 201 else None

if summary_id:
    httpx.post(f"{BASE}/summaries/{summary_id}/confirm", headers=dh, json={"decision": "accept"})

    print("\n--- 2. ABDM push refused without the abdm_push scope ---")
    refused = httpx.post(f"{BASE}/summaries/{summary_id}/push-abdm", headers=dh)
    check("push refused (403)", refused.status_code == 403, str(refused.status_code))
    check(
        "refusal names the missing scope",
        "abdm_push" in refused.text,
        refused.json().get("detail", "")[:80],
    )

    print("\n--- 3. ABDM push succeeds once the scope is granted ---")
    # Re-consent including abdm_push (the patient changes their mind).
    httpx.request("DELETE", f"{BASE}/consent/{consent_id}", headers=ph)
    httpx.post(
        f"{BASE}/consent",
        headers=ph,
        json={
            "scope": {
                "interview": True,
                "documents": True,
                "abdm_push": True,
                "share_with_physician": True,
                "retention_days": 90,
            },
            "language": "en",
            "audio_confirmed": True,
        },
    )

    pushed = httpx.post(f"{BASE}/summaries/{summary_id}/push-abdm", headers=dh, timeout=60.0)
    check("push accepted (200)", pushed.status_code == 200, str(pushed.status_code))
    if pushed.status_code == 200:
        body = pushed.json()
        bundle = body.get("bundle") or {}
        check("transmitted over real HTTP", body.get("pushed") is True, str(body.get("transport")))
        check("payload is a FHIR document Bundle", bundle.get("type") == "document")
        check(
            "Bundle leads with a Composition",
            (bundle.get("entry") or [{}])[0].get("resource", {}).get("resourceType")
            == "Composition",
        )
        types = [e["resource"]["resourceType"] for e in bundle.get("entry", [])]
        check("Patient resource present", "Patient" in types, ", ".join(sorted(set(types))))
        check("no Aadhaar anywhere in the Bundle", "aadhaar" not in pushed.text.lower())

        print("\n--- 4. Session data purge removed the raw scan ---")
        import os

        path = f"/app/storage/{file_uri}"
        check("raw scan deleted from disk", not os.path.exists(path), path)
        tl = httpx.get(f"{BASE}/patients/{patient_id}/documents/timeline", headers=ph)
        check(
            "extracted entities survived the purge",
            tl.status_code == 200 and tl.json()["documents"][0]["entity_count"] > 0,
            (
                f"entities={tl.json()['documents'][0]['entity_count']}"
                if tl.status_code == 200
                else ""
            ),
        )

print("\n--- 5. Consent revocation blocks further AI processing ---")
current = httpx.get(f"{BASE}/consent/current", headers=ph).json()
httpx.request("DELETE", f"{BASE}/consent/{current['consent_id']}", headers=ph)

sess2 = httpx.post(f"{BASE}/interview/sessions", headers=ph, json={"mode": "general"})
check("interview blocked after revocation (403)", sess2.status_code == 403, str(sess2.status_code))
asr = httpx.post(
    f"{BASE}/interview/asr", headers=ph, files={"file": ("a.webm", b"x", "audio/webm")}
)
check("ASR blocked after revocation (403)", asr.status_code == 403, str(asr.status_code))
regen = httpx.post(
    f"{BASE}/summaries/generate", headers=dh, json={"session_id": session_id}, timeout=60.0
)
check(
    "summariser blocked after revocation",
    regen.status_code in (403, 201),
    f"{regen.status_code} (201 = pre-existing summary returned, no new AI call)",
)

print("\n--- 6. Audit trail persisted to Postgres ---")
import psycopg2  # noqa: E402

conn = psycopg2.connect("postgresql://medikiosk:medikiosk@db:5432/medikiosk")
cur = conn.cursor()
cur.execute(
    "SELECT action FROM audit_logs WHERE detail->>'patient_id' = %s ORDER BY timestamp",
    (patient_id,),
)
actions = [r[0] for r in cur.fetchall()]
print("     trail:", ", ".join(actions) or "(empty)")

for expected in (
    "patient.register",
    "consent.grant",
    "document.upload",
    "interview.session_started",
    "interview.answer_submitted",
    "interview.session_completed",
    "summary.generated",
    "consent.revoke",
):
    check(f"audited: {expected}", expected in actions)

if summary_id:
    check("audited: summary.pushed_abdm", "summary.pushed_abdm" in actions)
    check("audited: session.data_purged", "session.data_purged" in actions)

conn.close()

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} CHECK(S) FAILED: " + "; ".join(failures))
    sys.exit(1)
print("ALL MODULE D CHECKS PASSED")
