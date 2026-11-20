import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from access_helpers import ORIGIN, PASSWORD, add_user, login
from alembic import command
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError

from api_sentinel.audit.records import Action, AuditEntry
from api_sentinel.database import transaction
from api_sentinel.identity.models import Membership, User
from api_sentinel.identity.operator import provision
from api_sentinel.identity.routes import DB, current_user
from api_sentinel.identity.security import COOKIE, Role
from api_sentinel.main import create_app
from api_sentinel.organizations.models import Project


def test_session_history_is_private_and_correlates_to_request(
    database: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    email = "fixture-private@example.test"
    provision(email, PASSWORD, "Private organization")
    marker = "synthetic-header-marker"
    with (
        caplog.at_level(logging.INFO, logger="uvicorn.error"),
        TestClient(create_app(engine=database), base_url=ORIGIN) as client,
    ):
        fail = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
            headers={"Origin": ORIGIN},
        )
        assert fail.status_code == 401
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-Request-ID": marker},
        )
        assert response.status_code == 200
        token = client.cookies[COOKIE]
        csrf = response.json()["csrf_token"]
        uid = response.json()["id"]
        entries = client.get("/api/v1/auth/activity").json()["entries"]
        assert [e["action"] for e in entries] == ["session.login", "account.created"]
        assert entries[0]["request_id"] == response.headers["x-request-id"]
        assert entries[0]["actor_id"] == uid
        assert entries[1]["actor_id"] is None and entries[1]["request_id"] is None
        org = response.json()["organizations"][0]["id"]
        org_feed = client.get(f"/api/v1/organizations/{org}/audit").json()["entries"]
        assert [e["action"] for e in org_feed] == ["member.added"]
        assert org_feed[0]["new_role"] == "owner"
        logout = client.post(
            "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
        )
        assert logout.status_code == 204
        assert client.get("/api/v1/auth/activity").status_code == 401
        login(client, email)
        history = client.get("/api/v1/auth/activity")
        assert any(
            e["request_id"] == logout.headers["x-request-id"] for e in history.json()["entries"]
        )
        other, _, _ = add_user(database)
        login(client, other)
        assert (
            client.get("/api/v1/auth/activity", params={"before": entries[0]["id"]}).status_code
            == 400
        )
        assert uid not in client.get("/api/v1/auth/activity").text
    with transaction(database) as db:
        failed = db.scalars(
            select(AuditEntry).where(AuditEntry.action == Action.LOGIN_FAILED)
        ).one()
        assert failed.request_id == fail.headers["x-request-id"]
        assert all(
            value is None
            for value in [
                failed.organization_id,
                failed.actor_id,
                failed.subject_user_id,
                failed.project_id,
            ]
        )
        stored = str(
            db.execute(text("SELECT row_to_json(a)::text FROM audit_entries a")).scalars().all()
        )
    request_logs = str([r.getMessage() for r in caplog.records if r.name == "uvicorn.error"])
    assert response.headers["x-request-id"] in request_logs
    for value in [email, PASSWORD, marker, token, csrf, "Private organization"]:
        assert value not in stored + history.text + request_logs


def test_org_changes_are_attributed_and_noops_and_conflicts_leave_no_entry(
    database: Engine,
) -> None:
    owner, uid, org = add_user(database)
    _, target, _ = add_user(database)
    api = f"/api/v1/organizations/{org}"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, owner)
        body = {"slug": "private", "name": "Secret display name"}
        response = client.post(api + "/projects", headers=headers, json=body)
        assert response.status_code == 201
        pid = response.json()["id"]
        assert client.post(api + "/projects", headers=headers, json=body).status_code == 409
        assert client.delete(f"{api}/projects/{pid}", headers=headers).status_code == 204
        member = f"{api}/members/{target}"
        for role in ("viewer", "viewer", "analyst"):
            assert client.put(member, headers=headers, json={"role": role}).status_code == 204
        assert client.delete(member, headers=headers).status_code == 204
        assert client.delete(f"{api}/members/{uid}", headers=headers).status_code == 409
        feed = client.get(api + "/audit")
        rows = feed.json()["entries"]
        assert [(r["action"], r["old_role"], r["new_role"]) for r in rows] == [
            ("member.removed", "analyst", None),
            ("member.role_changed", "viewer", "analyst"),
            ("member.added", None, "viewer"),
            ("project.deleted", None, None),
            ("project.created", None, None),
        ]
        assert all(r["actor_id"] == str(uid) for r in rows)
        assert rows[0]["subject_user_id"] == str(target)
        projects = client.get(api + "/audit", params={"project_id": pid}).json()["entries"]
        assert [r["id"] for r in projects] == [r["id"] for r in rows[-2:]]
        assert all(r["project_id"] == pid for r in projects)
        assert body["name"] not in feed.text and body["slug"] not in feed.text
        assert client.delete(api + "/audit", headers=headers).status_code == 405


@pytest.mark.parametrize("role", list(Role))
def test_read_permissions_and_cursors_are_bound_to_tenant(database: Engine, role: Role) -> None:
    email, _, org = add_user(database, role)
    _, _, other = add_user(database)
    stamp = datetime.now(UTC)
    project = uuid4()
    with transaction(database) as db:
        rows = [
            AuditEntry(
                organization_id=org,
                project_id=project,
                action=Action.PROJECT_CREATED,
                occurred_at=stamp,
            )
            for _ in range(3)
        ]
        foreign = AuditEntry(
            organization_id=other, project_id=uuid4(), action=Action.PROJECT_CREATED
        )
        db.add_all([*rows, foreign])
    url = f"/api/v1/organizations/{org}/audit"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        assert client.get(url).status_code == 401
        login(client, email)
        assert client.get(f"/api/v1/organizations/{other}/audit").status_code == 404
        res = client.get(url, params={"limit": 2})
        if role not in (Role.OWNER, Role.ANALYST):
            assert res.status_code == 403
            return
        assert res.status_code == 200
        first = res.json()
        assert len(first["entries"]) == 2 and first["next_cursor"] == first["entries"][-1]["id"]
        second = client.get(url, params={"limit": 2, "before": first["next_cursor"]}).json()
        assert second["next_cursor"] is None
        assert [r["id"] for r in first["entries"] + second["entries"]] == sorted(
            [str(row.id) for row in rows], reverse=True
        )
        assert client.get(url, params={"before": str(foreign.id)}).status_code == 400
        assert (
            client.get(
                url, params={"before": first["next_cursor"], "project_id": str(foreign.project_id)}
            ).status_code
            == 400
        )
        assert (
            client.get(url, params={"project_id": str(foreign.project_id)}).json()["entries"] == []
        )
        assert client.get(url, params={"limit": 101}).status_code == 422
        with transaction(database) as db:
            membership = db.scalars(
                select(Membership).where(Membership.organization_id == org)
            ).one()
            membership.role = Role.VIEWER
        assert client.get(url).status_code == 403


def test_failed_audit_insert_rolls_back_project(database: Engine) -> None:
    email, _, org = add_user(database)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        # Simulate audit storage rejecting an insert inside the disposable database.
        with database.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE audit_entries ADD CONSTRAINT reject_project_for_test CHECK (action <> 'project.created')"
                )
            )
        res = client.post(
            f"/api/v1/organizations/{org}/projects",
            json={"name": "Private", "slug": "private"},
            headers=headers,
        )
        assert res.status_code == 503 and res.headers["x-request-id"]
        assert "private" not in res.text.lower()
    with transaction(database) as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEntry)
                .where(AuditEntry.organization_id == org)
            )
            == 0
        )


def test_immutable_rows_and_revision_round_trip(empty_database: Engine, config: Config) -> None:
    command.upgrade(config, "0002_project_access")
    email, uid, org = add_user(empty_database)
    command.upgrade(config, "head")
    with TestClient(create_app(engine=empty_database), base_url=ORIGIN) as client:
        login(client, email)
    for sql in [
        "UPDATE audit_entries SET actor_id=NULL",
        "DELETE FROM audit_entries",
        "TRUNCATE audit_entries",
    ]:
        with pytest.raises(DBAPIError, match="append-only"), empty_database.begin() as conn:
            conn.execute(text(sql))
    with transaction(empty_database) as db:
        assert db.scalars(select(AuditEntry.actor_id)).one() == uid
    command.downgrade(config, "0002_project_access")
    assert "audit_entries" not in inspect(empty_database).get_table_names()
    with transaction(empty_database) as db:
        assert db.get(Membership, (org, uid)) is not None
    command.upgrade(config, "head")
    command.check(config)


def test_overlapping_signouts_record_one_revocation(database: Engine) -> None:
    email, uid, _ = add_user(database)
    app = create_app(engine=database)
    both_authenticated = Barrier(2)

    def authenticated_together(request: Request, db: DB) -> User:
        user = current_user(request, db)
        both_authenticated.wait(timeout=10)
        return user

    with TestClient(app, base_url=ORIGIN) as first, TestClient(app, base_url=ORIGIN) as second:
        headers = login(first, email)
        second.cookies.set(COOKIE, first.cookies[COOKIE])
        app.dependency_overrides[current_user] = authenticated_together
        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [
                workers.submit(client.post, "/api/v1/auth/logout", headers=headers)
                for client in (first, second)
            ]
            assert [job.result().status_code for job in pending] == [204, 204]
    with transaction(database) as db:
        assert db.scalars(
            select(AuditEntry.actor_id).where(AuditEntry.action == Action.LOGOUT)
        ).all() == [uid]


def test_session_replacement_keeps_the_other_account_private(database: Engine) -> None:
    first, uid, _ = add_user(database)
    other, other_id, _ = add_user(database)
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as reader, TestClient(app, base_url=ORIGIN) as switching:
        login(reader, first)
        login(switching, first)
        login(switching, other)
        prior = reader.get("/api/v1/auth/activity")
        entry = prior.json()["entries"][0]
        assert entry["action"] == "session.replaced" and entry["subject_user_id"] == str(uid)
        assert entry["actor_id"] is None and str(other_id) not in prior.text
        assert str(uid) not in switching.get("/api/v1/auth/activity").text
