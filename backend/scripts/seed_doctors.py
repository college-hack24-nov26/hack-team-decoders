"""Seed the six demo doctors patients can pick at the kiosk (F2).

Idempotent: matches on (name, department) so re-running does not duplicate rows.
These are *selectable doctors* with a queue, not login accounts — see the Doctor
vs Physician distinction in models.py.

Usage:
    python -m scripts.seed_doctors
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Allow running as a plain script (python scripts/seed_doctors.py) as well as a
# module, by ensuring the backend root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import DEMO_DOCTORS as DOCTORS  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.models import Doctor  # noqa: E402


def main() -> int:
    db = SessionLocal()
    created = 0
    try:
        for name, department, specialization in DOCTORS:
            existing = (
                db.query(Doctor)
                .filter(Doctor.name == name, Doctor.department == department)
                .first()
            )
            if existing:
                # Keep the demo consistent on re-run without wiping queue state.
                existing.specialization = specialization
                existing.available = True
                continue
            db.add(
                Doctor(
                    id=uuid.uuid4(),
                    name=name,
                    department=department,
                    specialization=specialization,
                    available=True,
                    queue_count=0,
                )
            )
            created += 1
        db.commit()

        print(f"Seeded {created} new doctor(s); {len(DOCTORS)} total in the demo set.")
        for name, department, _ in DOCTORS:
            print(f"  - {name} ({department})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
