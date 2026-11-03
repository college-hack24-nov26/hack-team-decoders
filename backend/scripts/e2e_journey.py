"""End-to-end journey: Identify → Converse → Scan → Summarize → Consult.

Run against the Docker stack:
    docker compose exec backend python scripts/e2e_journey.py

Walks a single patient through every step and asserts the expected output exists
at each stage. This proves the full vertical slice works, not just individual
endpoints.
"""

import sys

import httpx

BASE = "http://localhost:8000/api/v1"
OK = "[OK]"
FAIL = "[FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = OK if condition else FAIL
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def must(label: str, response: httpx.Response, expected: int = 200) -> dict:
    ok = response.status_code == expected
    check(label, ok, f"{response.status_code}" + (f" {response.text[:120]}" if not ok else ""))
    if not ok:
        return {}
    return (
        response.json()
        if response.headers.get("content-type", "").startswith("application/json")
        else {}
    )


# ===========================================================================
print("\n╔══ STEP 1: IDENTIFY ══════════════════════════════════════════════╗")
# ===========================================================================

print("\n  1a. Language selection")
langs = must("GET /languages", httpx.get(f"{BASE}/languages"))
check("English and Hindi available", len(langs.get("languages", [])) >= 2)

print("\n  1b. ABHA lookup (mocked)")
lookup = must(
    "ABHA lookup finds seeded patient",
    httpx.post(f"{BASE}/auth/abha/lookup", json={"abha_id": "91-1234-5678-9012"}),
)
check("returns patient name", lookup.get("name") == "Ramesh Kumar")

print("\n  1c. Registration (new patient for this journey)")
reg = must(
    "register new patient",
    httpx.post(
        f"{BASE}/auth/register",
        json={
            "name": "E2E Journey Patient",
            "age": 40,
            "gender": "female",
            "phone": "9811223344",
            "preferred_language": "en",
        },
    ),
    expected=201,
)
token = reg.get("token", "")
patient_id = reg.get("patient_id", "")
ph = {"Authorization": f"Bearer {token}"}

print("\n  1d. Consent")
consent = must(
    "grant consent",
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
    ),
    expected=201,
)
check(
    "consent active", httpx.get(f"{BASE}/consent/current", headers=ph).json().get("active") is True
)

# ===========================================================================
print("\n╔══ STEP 2: CONVERSE ═════════════════════════════════════════════╗")
# ===========================================================================

print("\n  2a. Start interview")
sess = must(
    "start interview session",
    httpx.post(f"{BASE}/interview/sessions", headers=ph, json={"mode": "general"}),
    expected=201,
)
session_id = sess.get("session_id", "")
check(
    "first question is chief complaint",
    sess.get("next_question", {}).get("field_id") == "chief_complaint",
)

print("\n  2b. Answer chief complaint")
ans1 = must(
    "answer chief complaint",
    httpx.post(
        f"{BASE}/interview/sessions/{session_id}/answer",
        headers=ph,
        json={
            "field_id": "chief_complaint",
            "value": "chest_pain",
            "input_mode": "touch",
        },
    ),
)
check("accepted", ans1.get("accepted") is True)
check("next question advances", ans1.get("next_question") is not None)

print("\n  2c. Answer a few HPI questions to trigger red flag")
for field, value in [
    ("hpi.site", "central"),
    ("hpi.onset", "hours"),
    ("hpi.severity", 9),
    ("hpi.associated_symptoms", ["breathlessness", "sweating"]),
]:
    httpx.post(
        f"{BASE}/interview/sessions/{session_id}/answer",
        headers=ph,
        json={
            "field_id": field,
            "value": value,
            "input_mode": "touch",
        },
    )

flags = httpx.get(f"{BASE}/interview/sessions/{session_id}/red-flags", headers=ph).json()
check("red flag fired", len(flags) > 0, f"{len(flags)} flag(s)")

print("\n  2d. Complete interview")
comp = must(
    "complete session", httpx.post(f"{BASE}/interview/sessions/{session_id}/complete", headers=ph)
)
check(
    "session status is red_flagged or completed", comp.get("status") in ("completed", "red_flagged")
)

# ===========================================================================
print("\n╔══ STEP 3: SCAN ════════════════════════════════════════════════╗")
# ===========================================================================

print("\n  3a. Upload a document")
from PIL import Image, ImageDraw  # noqa: E402

img = Image.new("RGB", (800, 400), "white")
ImageDraw.Draw(img).text(
    (20, 20),
    "Date: 15/03/2025\nHemoglobin 9.0 g/dL 13.0-17.0\nFasting Glucose 138 mg/dL 70-100",
    fill="black",
)
img.save("/tmp/e2e_lab.png")

with open("/tmp/e2e_lab.png", "rb") as f:
    upload = must(
        "upload document",
        httpx.post(
            f"{BASE}/documents",
            headers=ph,
            files={"file": ("lab.png", f, "image/png")},
            data={"doc_type": "lab_report"},
            timeout=60.0,
        ),
        expected=201,
    )
check("OCR ran", upload.get("ocr_status") == "done")

print("\n  3b. Timeline")
timeline = must(
    "get timeline",
    httpx.get(f"{BASE}/patients/{patient_id}/documents/timeline", headers=ph),
)
check("timeline has 1 document", len(timeline.get("documents", [])) >= 1)

# ===========================================================================
print("\n╔══ STEP 4: SUMMARIZE & ROUTE ══════════════════════════════════╗")
# ===========================================================================

print("\n  4a. Physician login")
# These must match what seed_physician.py creates.
PHYSICIAN_EMAIL = "doctor@medikiosk.in"
PHYSICIAN_PASSWORD = "medikiosk-demo"

doc_login = must(
    "physician login",
    httpx.post(
        f"{BASE}/auth/physician/login",
        json={"email": PHYSICIAN_EMAIL, "password": PHYSICIAN_PASSWORD},
    ),
)
dh = {"Authorization": f"Bearer {doc_login.get('token', '')}"}

print("\n  4b. Generate summary")
summary = must(
    "generate summary",
    httpx.post(
        f"{BASE}/summaries/generate", headers=dh, json={"session_id": session_id}, timeout=120.0
    ),
    expected=201,
)
summary_id = summary.get("id", "")
check("summary is a draft", summary.get("status") == "draft")
check(
    "structured_content has chief complaint",
    "chief_complaint" in str(summary.get("structured_content", {})),
)

print("\n  4c. Confirm summary")
confirm = must(
    "physician confirms",
    httpx.post(f"{BASE}/summaries/{summary_id}/confirm", headers=dh, json={"decision": "accept"}),
)
check("status is confirmed", confirm.get("status") == "confirmed")

print("\n  4d. Push to ABDM")
push = must(
    "push FHIR bundle",
    httpx.post(f"{BASE}/summaries/{summary_id}/push-abdm", headers=dh, timeout=60.0),
)
check("FHIR Bundle generated", push.get("bundle", {}).get("resourceType") == "Bundle")

# ===========================================================================
print("\n╔══ STEP 5: CONSULT ═════════════════════════════════════════════╗")
# ===========================================================================

print("\n  5a. Dashboard queue")
queue = must("get queue", httpx.get(f"{BASE}/dashboard/queue", headers=dh))
check("queue is not empty", len(queue.get("patients", [])) > 0)

print("\n  5b. Patient summary view")
pview = must(
    "patient summary view",
    httpx.get(f"{BASE}/dashboard/patients/{patient_id}/summary", headers=dh),
)
check("summary is present", pview.get("summary") is not None)
check("documents are present", len(pview.get("documents", [])) > 0)
check("red flags are present", len(pview.get("red_flags", [])) > 0)

# ===========================================================================
print("\n" + "=" * 66)
if failures:
    print(f"\n{FAIL} {len(failures)} STEP(S) FAILED:")
    for f_name in failures:
        print(f"    • {f_name}")
    sys.exit(1)
else:
    print("\n✅ FULL END-TO-END JOURNEY PASSED — all stages verified.")
    sys.exit(0)
