"""JWT issuance and validation for patient and physician sessions.

Two distinct subject types share one signing key, so the ``type`` claim is
checked on decode as well as set on encode. Without that check a physician
token would satisfy a patient dependency and vice versa: the ``sub`` of one
would be looked up as the id of the other, and whichever table happened to
contain a row with that UUID would grant access.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from jose import JWTError, jwt

from app.core.config import get_settings

TokenType = Literal["patient", "physician"]


def _create_token(subject_id: uuid.UUID, token_type: TokenType) -> str:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(subject_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "type": token_type,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_type: TokenType) -> uuid.UUID | None:
    """Decode a JWT, returning the subject id only if the type claim matches."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None

    if payload.get("type") != expected_type:
        return None

    subject = payload.get("sub")
    if not subject:
        return None
    try:
        return uuid.UUID(subject)
    except ValueError:
        return None


def create_patient_token(patient_id: uuid.UUID) -> str:
    """Issue a JWT for a patient session."""
    return _create_token(patient_id, "patient")


def decode_patient_token(token: str) -> uuid.UUID | None:
    """Decode a patient JWT. Returns patient_id, or None if invalid or not a
    patient token."""
    return _decode_token(token, "patient")


def create_physician_token(physician_id: uuid.UUID) -> str:
    """Issue a JWT for a physician dashboard session."""
    return _create_token(physician_id, "physician")


def decode_physician_token(token: str) -> uuid.UUID | None:
    """Decode a physician JWT. Returns physician_id, or None if invalid or not a
    physician token."""
    return _decode_token(token, "physician")
