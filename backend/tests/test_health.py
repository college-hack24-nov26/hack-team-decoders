"""Smoke tests for the /health endpoint.

These tests use a SQLite in-memory database so they run without Docker.
The DB session dependency is overridden via FastAPI's dependency_overrides.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client():
    """Return a TestClient with a mocked DB session."""
    mock_db = MagicMock()
    mock_db.execute.return_value = None  # simulate SELECT 1 succeeding

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health_ok(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
    assert "timestamp" in data


def test_health_degraded_when_db_fails():
    """When the DB raises, /health should return 'degraded' (not 500)."""
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("connection refused")

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        response = c.get("/health")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db"] == "unreachable"
