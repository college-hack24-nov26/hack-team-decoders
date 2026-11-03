"""Password hashing for physician accounts.

Patients authenticate via ABHA/Aadhaar and never have a password, so this is
used only by clinical staff logging into the dashboard.

Uses the ``bcrypt`` package directly rather than passlib. passlib 1.7.4 (last
released 2020) reads ``bcrypt.__about__.__version__``, which bcrypt 4.1 removed,
so the combination pinned in requirements.txt raised on first use. bcrypt is the
real implementation underneath passlib anyway, and its API is two calls.

Passwords are SHA-256'd before hashing. bcrypt truncates at 72 bytes, which is a
property of the algorithm rather than a bug: without the pre-hash, two long
passphrases sharing a 72-byte prefix would be interchangeable at login.
"""

import base64
import hashlib

import bcrypt

#: bcrypt work factor. 12 is the common default: a few hundred milliseconds per
#: verification, which is unnoticeable on a login and expensive in bulk.
_ROUNDS = 12


def _prepare(plain: str) -> bytes:
    """Reduce a password to a fixed-width value bcrypt can consume whole.

    base64 of the SHA-256 digest is 44 bytes, comfortably under bcrypt's 72-byte
    limit, and contains no NUL bytes (bcrypt truncates at the first NUL).
    """
    digest = hashlib.sha256(plain.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(plain: str) -> str:
    """Hash a plaintext password for storage."""
    return bcrypt.hashpw(_prepare(plain), bcrypt.gensalt(rounds=_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plaintext password against a stored hash.

    Returns False rather than raising on a malformed or empty hash, so a
    corrupted row fails the login instead of surfacing a 500 that distinguishes
    it from a wrong password.
    """
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False
