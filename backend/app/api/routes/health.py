"""Health check endpoint."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.google_keys import get_pool as get_google_pool
from app.services.sarvam_keys import get_pool as get_sarvam_pool

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):  # noqa: B008
    """Return service status and DB connectivity."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    payload = {
        "status": "ok" if db_ok else "degraded",
        "db": "connected" if db_ok else "unreachable",
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }

    # Counts only, never key labels: this endpoint is unauthenticated. Enough to
    # answer "how much budget is left before a service degrades" without reading
    # server logs mid-demo.
    sarvam_pool = get_sarvam_pool()
    if sarvam_pool.configured:
        payload["sarvam_keys"] = sarvam_pool.summary()

    google_pool = get_google_pool()
    if google_pool.configured:
        payload["google_keys"] = google_pool.summary()

    return payload
