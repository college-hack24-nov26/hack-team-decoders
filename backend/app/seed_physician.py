"""Create or reset a physician account for the dashboard.

Physician login verifies a bcrypt hash, so an account has to exist before the
dashboard is reachable. There is no self-signup: clinical staff accounts are
provisioned deliberately.

Usage:
    python -m app.seed_physician
    python -m app.seed_physician --email doctor@aiia.gov.in --password 's3cret' \
        --name "Dr A Sharma" --role physician
"""

from __future__ import annotations

import argparse
import sys
import uuid

from app.db.session import SessionLocal
from app.models.models import Physician
from app.services.password import hash_password

DEFAULT_EMAIL = "doctor@medikiosk.in"
DEFAULT_PASSWORD = "medikiosk-demo"
DEFAULT_NAME = "Dr Demo Physician"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--role", default="physician", choices=["physician", "staff", "admin"])
    args = parser.parse_args(argv)

    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        existing = db.query(Physician).filter(Physician.email == email).first()
        if existing:
            existing.hashed_password = hash_password(args.password)
            existing.full_name = args.name
            existing.role = args.role
            existing.is_active = True
            db.commit()
            print(f"Reset password for existing physician: {email} (role={args.role})")
        else:
            db.add(
                Physician(
                    id=uuid.uuid4(),
                    email=email,
                    hashed_password=hash_password(args.password),
                    full_name=args.name,
                    role=args.role,
                    is_active=True,
                )
            )
            db.commit()
            print(f"Created physician: {email} (role={args.role})")

        if args.password == DEFAULT_PASSWORD:
            print(
                "\nWARNING: this is the default demo password. Do not use it "
                "anywhere real; pass --password to set your own.",
                file=sys.stderr,
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
