"""SQLAlchemy 2.x engine and session factory.

Supports both PostgreSQL (production / Docker) and SQLite (local dev without
Docker). The driver is selected automatically from DATABASE_URL.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


def _build_engine():
    settings = get_settings()
    url = str(settings.database_url)
    is_sqlite = url.startswith("sqlite")

    kwargs: dict = {
        "echo": settings.debug,
    }

    if not is_sqlite:
        # Postgres-specific: connection pool health checks
        kwargs["pool_pre_ping"] = True
    else:
        # SQLite needs check_same_thread=False for FastAPI's threaded model
        kwargs["connect_args"] = {"check_same_thread": False}

    eng = create_engine(url, **kwargs)

    # SQLite doesn't enforce FKs by default
    if is_sqlite:

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return eng


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


# ---------------------------------------------------------------------------
# Auto-create tables for SQLite (no Alembic needed for local dev)
# ---------------------------------------------------------------------------


def _auto_create_tables():
    """Create all tables if using SQLite. Safe no-op for Postgres (use Alembic)."""
    url = str(get_settings().database_url)
    if url.startswith("sqlite"):
        # Import models so they register with Base.metadata
        import app.models.models  # noqa: F401

        Base.metadata.create_all(bind=engine)


_auto_create_tables()


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
