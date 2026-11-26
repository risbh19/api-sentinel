import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api_sentinel.main import create_app


def test_working_admin_login_cannot_mask_invalid_application_password(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENTINEL_APP_PASSWORD", "invalid-synthetic-password")
    with TestClient(create_app()) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert client.get("/health/live").status_code == 200
