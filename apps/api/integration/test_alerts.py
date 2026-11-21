from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from access_helpers import ORIGIN, add_user, login
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, event, text
from sqlalchemy.engine import Connection
from test_detection_rules import drain, project, sample, send
from test_events import make_project

from api_sentinel.detections.rules import AUTH_DENIALS, AUTH_FAILURES, REQUEST_VOLUME
from api_sentinel.identity.operator import grant_table_access
from api_sentinel.identity.security import Role
from api_sentinel.main import create_app
from api_sentinel.worker import claim, process


def test_existing_findings_survive_upgrade_and_downgrade(database: Engine, config: Config) -> None:
    command.downgrade(config, "0008_detection_rules")
    owner = project(database)
    stamp = datetime.now(UTC) - timedelta(hours=1)
    send(database, owner, [sample(AUTH_FAILURES, f"old-{i}", stamp) for i in range(9)])
    drain(database)
    command.upgrade(config, "head")
    with database.connect() as conn:
        assert conn.scalar(text("SELECT occurrence_count FROM alert_summaries")) == 2
        assert conn.scalar(text("SELECT count(*) FROM alert_evidence")) == 9
    command.downgrade(config, "0008_detection_rules")
    with database.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM rule_findings")) == 2


def test_replay_late_arrivals_and_retention(database: Engine) -> None:
    owner = project(database)
    # One finding before the UTC bucket boundary. Its peer in the next bucket
    # shares seven events. A late arrival displaces one of these from the latter alert.
    boundary = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    stamps = [boundary - timedelta(seconds=9 - i) for i in range(8)] + [boundary]
    send(database, owner, [sample(AUTH_FAILURES, f"obs-{i}", t) for i, t in enumerate(stamps)])
    drain(database)
    with database.connect() as conn:
        alerts = conn.execute(
            text("SELECT id, fingerprint FROM alert_summaries ORDER BY bucket_start")
        ).all()
    assert len(alerts) == 2 and alerts[0].fingerprint != alerts[1].fingerprint
    send(
        database,
        owner,
        [
            sample(AUTH_FAILURES, "late", boundary - timedelta(seconds=1)),
            sample(AUTH_FAILURES, "next", boundary + timedelta(seconds=1)),
        ],
    )
    jobs = claim(database)
    barrier = Barrier(2)

    def run(job: tuple[UUID, int]) -> bool:
        barrier.wait(timeout=10)
        return process(database, *job)

    assert len(jobs) == 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(run, jobs))
    with database.begin() as conn:
        conn.execute(text("UPDATE event_jobs SET state='pending',attempts=0,available_at=now()"))
    drain(database)
    with database.begin() as conn:
        assert (
            conn.execute(
                text("SELECT id,fingerprint FROM alert_summaries ORDER BY bucket_start")
            ).all()
            == alerts
        )
        assert conn.scalars(
            text("SELECT occurrence_count FROM alert_summaries ORDER BY bucket_start")
        ).all() == [2, 2]
        evidence = conn.scalars(
            text("""SELECT e.external_event_id FROM alert_evidence ae
            JOIN security_events e ON e.id=ae.event_id WHERE ae.alert_id=:id ORDER BY 1"""),
            {"id": alerts[1].id},
        ).all()
        assert set(evidence) == {"late", "next", *(f"obs-{i}" for i in range(2, 9))}
        conn.execute(
            text("DELETE FROM security_events WHERE external_event_id IN ('obs-8','next')")
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM alert_evidence WHERE alert_id=:id"),
                {"id": alerts[1].id},
            )
            == 0
        )
        assert conn.scalar(text("SELECT count(*) FROM alert_summaries")) == 1


@pytest.mark.parametrize(
    ("role", "can_read_detail"),
    [(Role.OWNER, True), (Role.ANALYST, True), (Role.DEVELOPER, True), (Role.VIEWER, False)],
)
def test_alert_pages_evidence_and_scope(
    database: Engine, role: Role, can_read_detail: bool
) -> None:
    email, _, org = add_user(database, role)
    owner, foreign = make_project(database, org), project(database)
    stamp = datetime.now(UTC) - timedelta(hours=1)
    for target, source in ((owner, "one"), (owner, "two"), (foreign, "one")):
        send(database, target, [sample(AUTH_FAILURES, f"a-{i}", stamp) for i in range(9)], source)
    drain(database)
    with database.connect() as conn:
        foreign_alert = conn.scalar(
            text("SELECT id FROM alerts WHERE project_id=:project"), {"project": foreign}
        )
    url = f"/api/v1/projects/{owner}/alerts"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        assert client.get(url).status_code == 401
        login(client, email)
        page = client.get(url, params={"limit": 1, "status": "open"}).json()
        entry = page["entries"][0]
        assert entry["occurrence_count"] == 2 and entry["severity"] == "medium"
        assert "evidence" not in entry and "fingerprint" not in entry
        tail = client.get(url, params={"after": page["next_cursor"], "limit": 1}).json()
        assert tail["next_cursor"] is None and tail["entries"][0]["id"] != entry["id"]
        assert client.get(url, params={"status": "resolved"}).json()["entries"] == []
        assert client.get(url, params={"after": str(foreign_alert)}).status_code == 400
        assert client.get(f"/api/v1/projects/{foreign}/alerts").status_code == 404
        path = url + "/" + entry["id"]
        first = client.get(path, params={"limit": 4})
        if not can_read_detail:
            assert first.status_code == 403
            return
        assert client.get(f"{url}/{foreign_alert}").status_code == 404
        detail = first.json()
        assert detail["threshold"] == 8 and detail["version"] == 1
        assert "300 seconds" in detail["explanation"] and detail["caveat"]
        last = client.get(path, params={"after": detail["next_evidence_cursor"]}).json()
        ids = detail["evidence"] + last["evidence"]
        assert len(ids) == len(set(ids)) == 9 and last["next_evidence_cursor"] is None
        assert client.get(path, params={"after": str(uuid4())}).status_code == 400
        assert client.get(f"/api/v1/projects/{owner}/events/{ids[0]}").status_code == 200


def test_rule_dimensions_severity_and_counts(database: Engine) -> None:
    owner = project(database)
    stamp = datetime.now(UTC) - timedelta(hours=1)
    for label, method, route in (
        ("one", "GET", "/a"),
        ("two", "POST", "/a"),
        ("three", "GET", "/b"),
    ):
        send(
            database,
            owner,
            [
                sample(AUTH_DENIALS, f"{label}-{i}", stamp, method=method, route_template=route)
                for i in range(10)
            ],
        )
    for client in ("first", "second"):
        send(
            database,
            owner,
            [
                sample(REQUEST_VOLUME, f"{client}-{i}", stamp, client_token=client)
                for i in range(61)
            ],
        )
    drain(database)
    with database.connect() as conn:
        assert conn.execute(
            text("""SELECT rule_key,severity,count(*),sum(occurrence_count)
          FROM alert_summaries GROUP BY rule_key,severity ORDER BY rule_key""")
        ).all() == [
            ("authorization_denials", "medium", 3, 3),
            ("high_request_volume", "low", 2, 2),
        ]


def test_app_role_can_delete_project_with_alerts(database: Engine) -> None:
    owner = project(database)
    send(database, owner, [sample(AUTH_FAILURES, str(i), datetime.now(UTC)) for i in range(8)])
    drain(database)
    # Exercise the production grants only in the disposable DB. PostgreSQL roles
    # are cluster-wide; never change existing login credentials during a test.
    with psycopg.connect() as conn, conn.transaction(force_rollback=True):
        for role in ("sentinel_app", "sentinel_worker"):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        grant_table_access(conn)
        assert conn.execute("SELECT count(*) FROM alert_evidence").fetchone() == (8,)
        conn.execute("SET LOCAL ROLE sentinel_app")
        conn.execute("DELETE FROM projects WHERE id=%s", (owner,))
        conn.execute("RESET ROLE")
        for table in ("alerts", "alert_evidence", "rule_findings"):
            assert conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone() == (0,)


def test_detail_keeps_one_snapshot_during_retention(database: Engine) -> None:
    email, _, org = add_user(database)
    owner = make_project(database, org)
    send(database, owner, [sample(AUTH_FAILURES, str(i), datetime.now(UTC)) for i in range(8)])
    drain(database)
    with database.connect() as conn:
        alert = conn.scalar(text("SELECT id FROM alerts"))

    # Commit retention immediately after the database executes the detail SELECT.
    removed = False

    def expire(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        nonlocal removed
        if not removed and "alert_summaries" in statement:
            removed = True
            with database.begin() as writer:
                writer.execute(
                    text("DELETE FROM security_events WHERE project_id=:id"), {"id": owner}
                )

    path = f"/api/v1/projects/{owner}/alerts/{alert}"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        login(client, email)
        event.listen(database, "after_cursor_execute", expire)
        try:
            detail = client.get(path).json()
        finally:
            event.remove(database, "after_cursor_execute", expire)
        assert removed and detail["occurrence_count"] == 1 and len(detail["evidence"]) == 8
        assert client.get(path).status_code == 404
