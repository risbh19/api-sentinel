import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
from access_helpers import ORIGIN, add_user, login
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select, text, update

from api_sentinel.database import transaction
from api_sentinel.identity.models import Membership
from api_sentinel.identity.security import Role
from api_sentinel.ingestion import records
from api_sentinel.ingestion.models import EventSource, IngestionState, SecurityEvent
from api_sentinel.main import create_app
from api_sentinel.organizations.records import OrganizationRecords


@pytest.fixture(autouse=True)
def event_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_EVENT_HMAC_KEY", "17" * 32)


def make_project(database: Engine, org: UUID, slug: str = "demo") -> UUID:
    with transaction(database) as db:
        return OrganizationRecords(db, org).create_project("Demo", slug).id


def emit_headers(client: TestClient, project: UUID, headers: dict[str, str]) -> dict[str, str]:
    response = client.post(
        f"/api/v1/projects/{project}/ingestion-keys",
        json={"label": "Synthetic emitter"},
        headers=headers,
    )
    assert response.status_code == 201
    return {"Authorization": "Bearer " + response.json()["secret"]}


def batch(*ids: str, source: str = "synthetic-api", **changes: object) -> dict[str, object]:
    return {
        "source_id": source,
        "events": [
            {
                "event_id": external,
                "occurred_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "event_type": "authentication_failure",
                "method": "POST",
                "route_template": "/api/login",
                "status_code": 401,
                "actor_token": "synthetic-actor-marker",
                "client_token": "synthetic-client-marker",
                **changes,
            }
            for external in ids
        ],
    }


def query(**extra: str | int) -> dict[str, str | int]:
    now = datetime.now(UTC)
    return {"since": (now - timedelta(days=2)).isoformat(), "until": now.isoformat(), **extra}


def test_atomic_deduplication_persistence_and_privacy(
    database: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    email, _, org = add_user(database)
    project = make_project(database, org)
    with (
        caplog.at_level(logging.INFO, logger="uvicorn.error"),
        TestClient(create_app(engine=database), base_url=ORIGIN) as client,
    ):
        headers = login(client, email)
        auth = emit_headers(client, project, headers)
        payload = batch("one", "one", "two")
        first = client.post("/api/v1/ingest/events", json=payload, headers=auth)
        assert first.status_code == 200, first.text
        assert first.json() == {
            "project_id": str(project),
            "accepted": 2,
            "duplicate": 1,
            "rejected": 0,
        }
        assert first.headers["cache-control"] == "no-store"
        replay = client.post("/api/v1/ingest/events", json=batch("one", "two"), headers=auth)
        assert replay.json()["accepted"] == 0 and replay.json()["duplicate"] == 2
        assert (
            client.post(
                "/api/v1/ingest/events", json=batch("one", source="another"), headers=auth
            ).json()["accepted"]
            == 1
        )
        invalid = client.post(
            "/api/v1/ingest/events",
            json=batch("fresh", "also-fresh", password="never-store-this-password"),
            headers=auth,
        )
        assert invalid.status_code == 422 and "never-store" not in invalid.text
        mismatch = client.post(
            "/api/v1/ingest/events", json=batch("fresh", status_code=200), headers=auth
        )
        assert mismatch.status_code == 422
        with transaction(database) as db:
            assert db.scalar(select(func.count()).select_from(SecurityEvent)) == 3
            stored = (
                db.execute(text("select row_to_json(e)::text from security_events e"))
                .scalars()
                .all()
            )
            assert all(
                "synthetic-actor-marker" not in row and "synthetic-client-marker" not in row
                for row in stored
            )
            assert len(db.scalars(select(SecurityEvent.actor_hash)).first() or "") == 64
        assert (
            "synthetic-actor-marker" not in caplog.text
            and "synthetic-client-marker" not in caplog.text
        )
        assert auth["Authorization"] not in caplog.text


def test_bad_second_event_rolls_back_entire_batch(database: Engine) -> None:
    email, _, org = add_user(database)
    project = make_project(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        auth = emit_headers(client, project, headers)
        payload = batch("one", "two")
        assert isinstance(payload["events"], list)
        payload["events"][1]["occurred_at"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        assert client.post("/api/v1/ingest/events", json=payload, headers=auth).status_code == 422
        with transaction(database) as db:
            assert db.scalar(select(func.count()).select_from(SecurityEvent)) == 0
            assert db.scalar(select(func.count()).select_from(EventSource)) == 0
            assert db.scalar(select(func.count()).select_from(IngestionState)) == 0


@pytest.mark.parametrize("role", list(Role))
def test_event_role_matrix_and_tenant_boundaries(database: Engine, role: Role) -> None:
    owner, _, org = add_user(database)
    reader, uid, _ = add_user(database)
    project = make_project(database, org)
    foreign = make_project(database, org, "another")
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as client, TestClient(app, base_url=ORIGIN) as machine:
        headers = login(client, owner)
        auth = emit_headers(client, project, headers)
        assert (
            client.post("/api/v1/ingest/events", json=batch("one"), headers=headers).status_code
            == 401
        )
        assert (
            machine.post("/api/v1/ingest/events", json=batch("one"), headers=auth).status_code
            == 200
        )
        url = f"/api/v1/projects/{project}/events"
        assert machine.get(url, params=query(), headers=auth).status_code == 401
        summary = client.get(url, params=query()).json()["entries"][0]
        eid = summary["id"]
        assert "actor_hash" not in summary and "external_event_id" not in summary
        assert client.get(f"/api/v1/projects/{foreign}/events/{eid}").status_code == 404
        login(client, reader)
        assert client.get(url, params=query()).status_code == 404
        assert client.get(url + "/" + eid).status_code == 404
        with transaction(database) as db:
            db.add(Membership(organization_id=org, user_id=uid, role=role))
        assert client.get(url, params=query()).status_code == 200
        detail = client.get(url + "/" + eid)
        assert detail.status_code == (403 if role == Role.VIEWER else 200)
        if role != Role.VIEWER:
            assert detail.json()["actor_hash"] and "actor_token" not in detail.json()


def test_scoped_snapshot_pagination_and_filters(database: Engine) -> None:
    email, _, org = add_user(database)
    project = make_project(database, org)
    foreign = make_project(database, org, "other")
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        auth = emit_headers(client, project, headers)
        payload = batch("one", "two", "three")
        assert isinstance(payload["events"], list)
        payload["events"][1]["occurred_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        assert client.post("/api/v1/ingest/events", json=payload, headers=auth).status_code == 200
        url, params = f"/api/v1/projects/{project}/events", query(limit=1)
        first = client.get(url, params=params).json()
        cursor = first["next_cursor"]
        assert cursor
        assert (
            client.post("/api/v1/ingest/events", json=batch("later"), headers=auth).status_code
            == 200
        )
        second = client.get(url, params={**params, "after": cursor}).json()
        third = client.get(url, params={**params, "after": second["next_cursor"]}).json()
        assert third["next_cursor"] is None
        assert (
            len({first["entries"][0]["id"], second["entries"][0]["id"], third["entries"][0]["id"]})
            == 3
        )
        for invalid in (cursor[:-3] + "AAA", "abc"):
            assert client.get(url, params={**params, "after": invalid}).status_code == 400
        assert (
            client.get(
                f"/api/v1/projects/{foreign}/events", params={**params, "after": cursor}
            ).status_code
            == 400
        )
        assert (
            client.get(url, params={**params, "after": cursor, "status_code": 403}).status_code
            == 400
        )
        assert (
            client.get(url, params={**params, "after": cursor, "source": "other"}).status_code
            == 400
        )
        assert client.get(url, params={**params, "status_code": 403}).json()["entries"] == []
        assert (
            client.get(
                url,
                params={
                    **query(),
                    "source": "synthetic-api",
                    "event_type": "authentication_failure",
                },
            ).status_code
            == 200
        )
        assert (
            client.get(url, params={**params, "since": "2000-01-01T00:00:00Z"}).status_code == 422
        )


def test_concurrent_replay_across_two_project_keys(database: Engine) -> None:
    email, _, org = add_user(database)
    project = make_project(database, org)
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client, email)
        credentials = [emit_headers(client, project, headers) for _ in range(2)]
    barrier = Barrier(2)
    payload = batch("one", "two")

    def send(auth: dict[str, str]) -> dict[str, int]:
        with TestClient(app, base_url=ORIGIN) as emitter:
            barrier.wait(timeout=10)
            response = emitter.post("/api/v1/ingest/events", json=payload, headers=auth)
            assert response.status_code == 200, response.text
            return dict(response.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, credentials))
    assert sum(r["accepted"] for r in results) == 2
    assert sum(r["duplicate"] for r in results) == 2


def test_project_limits_revocation_and_database_rollback(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(records, "MAX_BATCHES_PER_MINUTE", 2)
    monkeypatch.setattr(records, "MAX_SOURCES", 1)
    email, _, org = add_user(database)
    project = make_project(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        auth = emit_headers(client, project, headers)
        assert (
            client.post("/api/v1/ingest/events", json=batch("one"), headers=auth).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/ingest/events", json=batch("two", source="other"), headers=auth
            ).status_code
            == 409
        )
        with database.begin() as conn:
            conn.execute(text("create unique index reject_event on security_events(method)"))
        failed = client.post("/api/v1/ingest/events", json=batch("two"), headers=auth)
        assert failed.status_code == 503 and "SQL" not in failed.text
        with database.begin() as conn:
            conn.execute(text("drop index reject_event"))
        assert (
            client.post("/api/v1/ingest/events", json=batch("two"), headers=auth).status_code
            == 200
        )
        limited = client.post("/api/v1/ingest/events", json=batch("three"), headers=auth)
        assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
        # Reset only the disposable test quota, then revoke through the real management API.
        with database.begin() as conn:
            conn.execute(update(IngestionState).values(window=0))
        base = f"/api/v1/projects/{project}/ingestion-keys"
        kid = client.get(base).json()["entries"][0]["id"]
        assert client.post(base + f"/{kid}/revoke", headers=headers).status_code == 204
        assert (
            client.post("/api/v1/ingest/events", json=batch("three"), headers=auth).status_code
            == 401
        )
        with transaction(database) as db:
            assert db.scalar(select(func.count()).select_from(SecurityEvent)) == 2


def test_event_migration_and_project_deletion(database: Engine, config: Config) -> None:
    email, _, org = add_user(database)
    project = make_project(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        auth = emit_headers(client, project, headers)
        assert (
            client.post("/api/v1/ingest/events", json=batch("one"), headers=auth).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/organizations/{org}/projects/{project}", headers=headers
            ).status_code
            == 204
        )
    with transaction(database) as db:
        assert db.scalar(select(func.count()).select_from(SecurityEvent)) == 0
        assert db.scalar(select(func.count()).select_from(EventSource)) == 0
    command.downgrade(config, "0005_ingestion_keys")
    assert "security_events" not in inspect(database).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
