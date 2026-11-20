from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from api_sentinel.identity.routes import session_for
from api_sentinel.ingestion.events import EventBatch, EventInput
from api_sentinel.ingestion.privacy import decode_cursor, encode_cursor, pseudonym, secret
from api_sentinel.main import create_app


def event(**changes: object) -> dict[str, object]:
    return {
        "event_id": "synthetic-1",
        "occurred_at": datetime.now(UTC).isoformat(),
        "event_type": "authentication_failure",
        "method": "POST",
        "route_template": "/api/login",
        "status_code": 401,
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "synthetic-secret"},
        {"headers": {"Authorization": "synthetic-secret"}},
        {"body": "synthetic-secret"},
        {"actor_token": "user@example.test"},
        {"client_token": "192.0.2.1"},
        {"route_template": "https://example.test/login"},
        {"route_template": "/api/login?password=synthetic-secret"},
        {"route_template": "/users/1234"},
        {"route_template": "/users/%73ecret"},
        {"route_template": "/api/\nlogin"},
        {"event_id": "a" * 97},
        {"method": "post"},
        {"status_code": True},
        {"status_code": "401"},
        {"occurred_at": 1700000000},
        {"occurred_at": "2026-11-21T12:00:00"},
        {"occurred_at": "2026-11-21T12:00:60Z"},
        {"event_type": "confirmed_exploit"},
    ],
)
def test_sensitive_or_malformed_fields_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventInput.model_validate(event(**changes))


def test_batch_bounds_timestamps_and_failure_status() -> None:
    now = datetime.now(UTC)
    for offset in (timedelta(days=-31), timedelta(minutes=6)):
        batch = EventBatch.model_validate(
            {"source_id": "demo", "events": [event(occurred_at=(now + offset).isoformat())]}
        )
        with pytest.raises(ValueError):
            batch.check_times(now)
    bad_status = EventBatch.model_validate(
        {"source_id": "demo", "events": [event(status_code=200)]}
    )
    with pytest.raises(ValueError):
        bad_status.check_times(now)
    for entries in ([], [event()] * 101):
        with pytest.raises(ValidationError):
            EventBatch.model_validate({"source_id": "demo", "events": entries})
    EventBatch.model_validate({"source_id": "demo", "events": [event()] * 100}).check_times(now)


def test_pseudonyms_are_scoped_and_domain_separated() -> None:
    key, project = bytes(range(32)), uuid4()
    one = pseudonym(key, project, "actor", "synthetic-user")
    assert one == pseudonym(key, project, "actor", "synthetic-user")
    assert one != pseudonym(key, uuid4(), "actor", "synthetic-user")
    assert one != pseudonym(key, project, "client", "synthetic-user")
    assert one != pseudonym(b"x" * 32, project, "actor", "synthetic-user")
    assert pseudonym(key, project, "actor", None) is None


def test_cursor_authentication_and_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_EVENT_HMAC_KEY", "17" * 32)
    encoded = encode_cursor({"project": str(uuid4()), "before": 2})
    assert decode_cursor(encoded)["before"] == 2
    for value in (encoded[:-3] + "AAA", "abc", "{}"):  # No unverified caller state.
        with pytest.raises(HTTPException) as exc:
            decode_cursor(value)
        assert exc.value.status_code == 400
    monkeypatch.delenv("SENTINEL_EVENT_HMAC_KEY")
    with pytest.raises(HTTPException) as exc:
        secret()
    assert exc.value.status_code == 503


def test_validation_and_streamed_size_errors_do_not_echo_input() -> None:
    marker = "synthetic-secret-validation-marker"
    app = create_app()
    app.dependency_overrides[session_for] = lambda: Session()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ingest/events",
            json={"source_id": "demo", "events": [event(**{marker: marker})]},
        )
        assert response.status_code == 422
        assert marker not in response.text
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
        streamed = client.post(
            "/api/v1/ingest/events",
            content=iter([b" " * 65536] * 3),
            headers={"Content-Type": "application/json"},
        )
        assert streamed.status_code == 413
        assert (
            client.post(
                "/api/v1/ingest/events", content=b"gzip", headers={"Content-Encoding": "gzip"}
            ).status_code
            == 415
        )
