"""MediKiosk — FastAPI application entrypoint.

Live: auth, consent and languages (Phase 1), the interview engine / Module A
(Phase 2), document digitization / Module B (Phase 3), summaries and the
physician dashboard / Module C (Phase 4-5), and the security/compliance layer
plus FHIR push / Module D (Phase 6).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.abdm_mock import router as abdm_mock_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.clinic import router as clinic_router
from app.api.routes.consent import router as consent_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.interview import router as interview_router
from app.api.routes.languages import router as languages_router
from app.api.routes.summaries import router as summaries_router
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed doctors + admin (and optionally wipe patient data) on boot.

    Driven by the MEDIKIOSK_BOOTSTRAP env var so a Render free service, which has
    no shell to run seed scripts in, can still be seeded and reset by setting an
    env var and redeploying. A no-op unless that var is set, so it costs nothing
    in normal operation or in tests. See app/bootstrap.py.
    """
    from app.bootstrap import run_from_env

    run_from_env()
    yield


app = FastAPI(
    title=settings.app_name,
    description="AI-powered patient case-taking kiosk — SIH 2026 PS-26047",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — configured via CORS_ORIGINS env var (comma-separated list of URLs,
#        or "*" to allow all origins).
#
#  On Render: set  CORS_ORIGINS=https://your-frontend.onrender.com
#  For quick demos you can use  CORS_ORIGINS=*  (credentials disabled then).
# ---------------------------------------------------------------------------
_raw_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_allow_all = _raw_origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _raw_origins,
    allow_credentials=not _allow_all,  # browsers reject credentials + "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers — Phase 1: auth, consent, languages
#           Phase 2: interview      Phase 3: documents
#           Phase 4-5: summaries, dashboard
#           Phase 6: abdm_mock (local FHIR sink — see the module docstring)
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(clinic_router, prefix="/api/v1")
app.include_router(consent_router, prefix="/api/v1")
app.include_router(languages_router, prefix="/api/v1")
app.include_router(interview_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(summaries_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")

# MOCK. Registered so the FHIR push has somewhere real to go in a local demo.
# Point ABDM_FHIR_ENDPOINT at a real gateway and remove this in production.
app.include_router(abdm_mock_router, prefix="/api/v1")
