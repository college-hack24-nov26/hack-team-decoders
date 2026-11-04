"""One-shot data bootstrap for environments with no shell (e.g. Render free tier).

There is no way to run `python -m scripts.seed_*` on a Render free web service, so
seeding is driven by an environment variable read at application startup instead:

    MEDIKIOSK_BOOTSTRAP=seed    ensure the 6 demo doctors and the admin login exist
                                (idempotent — safe to leave set on every boot)
    MEDIKIOSK_BOOTSTRAP=reset   ALSO wipe all patient / clinical data first
                                (destructive — use ONCE, then switch to `seed`)

The admin account is created from:
    ADMIN_EMAIL     (default: admin@medickiosk.in)
    ADMIN_PASSWORD  (default: winexe)

`reset` is deliberately not the default and never runs unless explicitly asked
for, because leaving it on would wipe every patient created during a demo on the
next cold start. That is exactly why the safe value (`seed`) is idempotent and
the destructive one has to be typed out.

Also runnable from a shell where one exists:  python -m app.bootstrap --reset
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.models import Doctor, Physician
from app.services.password import hash_password

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@medickiosk.in"
DEFAULT_ADMIN_PASSWORD = "winexe"  # noqa: S105 - demo default, overridable via env

#: A physician login for the dashboard, so judges can sign in and confirm /
#: generate summaries. Password matches the admin's (the demo uses one password).
DEMO_PHYSICIAN_EMAIL = "doctor@medikiosk.in"

# Demo doctors, at least one per department. The kiosk builds its department
# list from these rows, so a department exists on screen exactly when a doctor
# here belongs to it. Two Ayurveda because the project is for AIIA / Ministry of
# Ayush and that depth is the differentiator; the other AYUSH systems (Homeopathy,
# Unani, Yoga & Naturopathy) are listed so the AYUSH side of the kiosk is complete.
# The single source of truth: scripts/seed_doctors.py imports this list.
DEMO_DOCTORS = [
    ("Dr. Arvind Sharma", "General Medicine", "Internal Medicine"),
    ("Dr. Meera Patel", "Ayurveda", "Kayachikitsa"),
    ("Dr. Rajesh Reddy", "Cardiology", "Interventional Cardiology"),
    ("Dr. Sunita Gupta", "Pediatrics", "General Paediatrics"),
    ("Dr. Vikram Singh", "Orthopedics", "Trauma & Joint Replacement"),
    ("Dr. Kavya Menon", "ENT", "Otolaryngology"),
    ("Dr. Anita Joshi", "Ayurveda", "Panchakarma"),
    ("Dr. Rohan Verma", "General Medicine", "Family Medicine"),
    ("Dr. Priya Nair", "Gynaecology", "Obstetrics & Gynaecology"),
    ("Dr. Sameer Khan", "Dermatology", "Clinical Dermatology"),
    ("Dr. Lakshmi Iyer", "Homeopathy", "Classical Homeopathy"),
    ("Dr. Farah Siddiqui", "Unani", "Ilaj-bit-Tadbeer"),
    ("Dr. Ganesh Rao", "Yoga & Naturopathy", "Therapeutic Yoga"),
]
_DOCTORS = DEMO_DOCTORS

# Tables cleared by a reset, children before parents so foreign keys hold. Raw
# table names because document_embeddings has no ORM model, and a single ordered
# list keeps the FK ordering obvious and reviewable in one place.
_PATIENT_DATA_TABLES = [
    "visits",
    "document_embeddings",
    "document_entities",
    "documents",
    "summaries",
    "red_flags",
    "interview_messages",
    "interview_answers",
    "interview_sessions",
    "consent_records",
    "audit_logs",
    "patients",
]


def reset_patient_data(db: Session) -> None:
    """Delete every patient and all clinical data hanging off them.

    Keeps doctors and physician/admin logins — those are configuration, not
    patient data, and are re-seeded right after. Audit logs are cleared too:
    they are a demo's test noise here, not a real compliance trail.
    """
    for table in _PATIENT_DATA_TABLES:
        db.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed allowlist, no user input
    db.commit()
    logger.warning("bootstrap: wiped patient/clinical data (%d tables)", len(_PATIENT_DATA_TABLES))


def seed_doctors(db: Session) -> int:
    """Ensure the demo doctors exist. Idempotent — matches on (name, department)."""
    created = 0
    for name, department, specialization in _DOCTORS:
        existing = (
            db.query(Doctor).filter(Doctor.name == name, Doctor.department == department).first()
        )
        if existing:
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
    logger.info("bootstrap: doctors ensured (%d created, %d total)", created, len(_DOCTORS))
    return created


def seed_admin(db: Session, email: str, password: str) -> None:
    """Create the single super-admin, or reset it to these credentials if present.

    Resetting rather than skipping matters: a redeploy with a new ADMIN_PASSWORD
    should actually change the password, and an admin that somehow got
    deactivated should come back.
    """
    email = email.strip().lower()
    admin = db.query(Physician).filter(Physician.email == email).first()
    if admin is None:
        db.add(
            Physician(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password(password),
                full_name="Super Admin",
                role="admin",
                is_active=True,
            )
        )
        logger.info("bootstrap: created admin %s", email)
    else:
        admin.hashed_password = hash_password(password)
        admin.role = "admin"
        admin.is_active = True
        logger.info("bootstrap: reset admin %s", email)
    db.commit()


def seed_physician(db: Session, email: str, password: str, full_name: str = "Dr Demo") -> None:
    """Create (or reset) a role='physician' login for the dashboard.

    Distinct from the admin: this is the account judges use to view the queue,
    edit and confirm summaries. Same reset-if-present behaviour so a redeploy
    with a new password takes effect.
    """
    email = email.strip().lower()
    doc = db.query(Physician).filter(Physician.email == email).first()
    if doc is None:
        db.add(
            Physician(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role="physician",
                is_active=True,
            )
        )
        logger.info("bootstrap: created physician %s", email)
    else:
        doc.hashed_password = hash_password(password)
        doc.is_active = True
        logger.info("bootstrap: reset physician %s", email)
    db.commit()


def run(*, reset: bool, demo: bool, admin_email: str, admin_password: str) -> None:
    """Run the bootstrap against a fresh session.

    ``demo`` implies a reset — the demo dataset is a known, curated set of
    patients, so it always starts from a clean slate rather than piling on top of
    whatever was there.
    """
    db = SessionLocal()
    try:
        if reset or demo:
            reset_patient_data(db)
        seed_doctors(db)
        seed_admin(db, admin_email, admin_password)
        # The physician login shares the admin password (demo uses one password).
        seed_physician(db, DEMO_PHYSICIAN_EMAIL, admin_password)
        if demo:
            from app.demo_seed import build_demo

            build_demo(db)
    finally:
        db.close()


def run_from_env() -> None:
    """Entry point for the startup hook. No-op unless MEDIKIOSK_BOOTSTRAP is set.

    Never raises into startup: a seeding failure must not stop the API from
    booting, or a typo in an env var takes the whole service down.
    """
    mode = os.getenv("MEDIKIOSK_BOOTSTRAP", "").strip().lower()
    if mode not in ("seed", "reset", "demo"):
        return

    admin_email = os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    admin_password = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    try:
        logger.warning("bootstrap: MEDIKIOSK_BOOTSTRAP=%s — running", mode)
        run(
            reset=(mode == "reset"),
            demo=(mode == "demo"),
            admin_email=admin_email,
            admin_password=admin_password,
        )
        logger.warning("bootstrap: done")
    except Exception:  # noqa: BLE001 - startup must survive a seeding failure
        logger.exception("bootstrap: failed; continuing startup without it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe patient data first")
    parser.add_argument(
        "--demo", action="store_true", help="wipe, then build the full demo dataset"
    )
    parser.add_argument("--admin-email", default=os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL))
    parser.add_argument(
        "--admin-password", default=os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    )
    args = parser.parse_args(argv)

    run(
        reset=args.reset,
        demo=args.demo,
        admin_email=args.admin_email,
        admin_password=args.admin_password,
    )
    print(
        f"Bootstrap complete (reset={args.reset}, demo={args.demo}). "
        f"Admin: {args.admin_email.strip().lower()}. Doctors: {len(_DOCTORS)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
