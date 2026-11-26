import logging

import pytest
from fastapi.testclient import TestClient

from api_sentinel.main import create_app


def test_liveness_does_not_contact_database() -> None:
    async def unexpected_probe() -> bool:
        pytest.fail("Liveness contacted the database")

    with TestClient(create_app(unexpected_probe)) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("available", "code", "status"), [(True, 200, "ready"), (False, 503, "unavailable")]
)
def test_readiness_contract(available: bool, code: int, status: str) -> None:
    async def probe() -> bool:
        return available

    with TestClient(create_app(probe)) as client:
        response = client.get("/health/ready")
    assert response.status_code == code
    assert response.json() == {"status": status}
    assert response.headers["cache-control"] == "no-store"


def test_connection_failure_is_private(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "1")
    monkeypatch.setenv("PGUSER", "sentinel_app")
    monkeypatch.setenv("PGDATABASE", "synthetic")
    secret = "synthetic-secret-for-log-test"
    monkeypatch.setenv("SENTINEL_APP_PASSWORD", secret)
    monkeypatch.setenv("PGPASSWORD", secret)
    with caplog.at_level(logging.INFO), TestClient(create_app()) as client:
        response = client.get("/health/ready", headers={"Authorization": f"Bearer {secret}"})
        assert client.get("/health/live").status_code == 200
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert secret not in caplog.text
    assert secret not in response.text


def test_missing_application_password_skips_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    import psycopg

    connect = AsyncMock(side_effect=AssertionError("Readiness used fallback credentials"))
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    monkeypatch.delenv("SENTINEL_APP_PASSWORD", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200
    connect.assert_not_awaited()


def test_request_log_omits_unmatched_path_query_and_headers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from uuid import UUID

    secret = "synthetic-privacy-marker"
    with caplog.at_level(logging.INFO, logger="uvicorn.error"), TestClient(create_app()) as client:
        response = client.get(
            f"/{secret}?token={secret}", headers={"X-Request-ID": secret, "Cookie": secret}
        )
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    records = [record.message for record in caplog.records if record.name == "uvicorn.error"]
    assert len(records) == 1
    assert request_id in records[0] and "unmatched" in records[0]
    assert secret not in records[0]
