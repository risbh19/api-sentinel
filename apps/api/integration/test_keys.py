import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from access_helpers import ORIGIN, add_user, login
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from api_sentinel.audit.records import Action, AuditEntry
from api_sentinel.database import transaction
from api_sentinel.identity.security import Role, digest
from api_sentinel.ingestion.models import IngestionKey
from api_sentinel.main import create_app
from api_sentinel.organizations.records import OrganizationRecords


def collection(database: Engine, org: UUID, slug: str = "demo") -> str:
    with transaction(database) as db:
        project = OrganizationRecords(db, org).create_project("Demo", slug)
        return f"/api/v1/projects/{project.id}/ingestion-keys"


def test_lifecycle_masking_and_project_bound_machine_auth(
    database: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    owner, _, org = add_user(database)
    base = collection(database, org)
    other = collection(database, org, "other")
    app = create_app(engine=database)
    with (
        caplog.at_level(logging.INFO, logger="uvicorn.error"),
        TestClient(app, base_url=ORIGIN) as client,
        TestClient(app, base_url=ORIGIN) as emitter,
    ):
        headers = login(client, owner)
        made = client.post(base, headers=headers, json={"label": "Local emitter"})
        assert made.status_code == 201 and made.headers["cache-control"] == "no-store"
        token = made.json()["secret"]
        key = made.json()["key"]
        auth = {"Authorization": "Bearer " + token}
        assert token.startswith(key["prefix"] + ".") and key["last_used_at"] is None
        assert emitter.get(base, headers=auth).status_code == 401
        assert emitter.get("/api/v1/auth/me", headers=auth).status_code == 401
        assert client.post(base + "/check", headers=headers).status_code == 401
        assert emitter.post(other + "/check", headers=auth).status_code == 401
        incorrect = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert (
            emitter.post(
                base + "/check", headers={"Authorization": "Bearer " + incorrect}
            ).status_code
            == 401
        )
        assert client.get(base).json()["entries"][0]["last_used_at"] is None
        assert emitter.post(base + "/check", headers=auth).status_code == 204
        assert (
            emitter.post(
                base + "/check", headers={"Authorization": "Bearer " + token[:-1]}
            ).status_code
            == 401
        )
        listing = client.get(base)
        assert listing.json()["entries"][0]["last_used_at"] is not None
        assert set(listing.json()["entries"][0]) == {
            "id",
            "label",
            "created_at",
            "project_id",
            "prefix",
            "last_used_at",
            "revoked_at",
        }
        with transaction(database) as db:
            stored = db.scalars(select(IngestionKey)).one()
            assert stored.key_hash == digest(token)
            assert token not in str(
                db.execute(text("select row_to_json(k)::text from ingestion_keys k")).scalar()
            )
        rotation = client.post(f"{base}/{key['id']}/rotate", headers=headers)
        new = rotation.json()
        assert rotation.status_code == 201 and rotation.headers["cache-control"] == "no-store"
        assert new["secret"] != token and new["key"]["id"] != key["id"]
        assert client.post(f"{base}/{key['id']}/rotate", headers=headers).status_code == 409
        assert emitter.post(base + "/check", headers=auth).status_code == 401
        new_auth = {"Authorization": "Bearer " + new["secret"]}
        assert emitter.post(base + "/check", headers=new_auth).status_code == 204
        revoke = f"{base}/{new['key']['id']}/revoke"
        assert client.post(revoke, headers={"Origin": ORIGIN}).status_code == 403
        assert client.post(revoke, headers=headers).status_code == 204
        assert emitter.post(base + "/check", headers=new_auth).status_code == 401
        assert client.post(revoke, headers=headers).status_code == 409
        first = client.get(base + "?limit=1").json()
        second = client.get(base, params={"after": first["next_cursor"]}).json()
        assert [first["entries"][0]["prefix"], second["entries"][0]["prefix"]] == sorted(
            [key["prefix"], new["key"]["prefix"]]
        )
        audit = client.get(f"/api/v1/organizations/{org}/audit")
        entries = [r for r in audit.json()["entries"] if r["action"].startswith("key.")]
        assert len(entries) == 4
        assert {
            r["key_id"] for r in entries if r["request_id"] == rotation.headers["x-request-id"]
        } == {key["id"], new["key"]["id"]}
        for secret in (token, new["secret"], digest(token), digest(new["secret"])):
            assert secret not in listing.text + audit.text + caplog.text


def test_rotation_requires_the_current_sessions_csrf_token(database: Engine) -> None:
    email, _, org = add_user(database)
    base = collection(database, org)
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as owner, TestClient(app, base_url=ORIGIN) as other:
        other_email, _, _ = add_user(database)
        foreign_headers = login(other, other_email)
        headers = login(owner, email)
        created = owner.post(base, headers=headers, json={"label": "Fixture key"})
        assert created.status_code == 201
        key = created.json()
        rotate = f"{base}/{key['key']['id']}/rotate"
        check = base + "/check"
        bearer = {"Authorization": "Bearer " + key["secret"]}
        assert owner.post(rotate, headers=foreign_headers).status_code == 403
        assert other.post(check, headers=bearer).status_code == 204
        assert len(owner.get(base).json()["entries"]) == 1
        assert owner.post(rotate, headers=headers).status_code == 201
        assert other.post(check, headers=bearer).status_code == 401


@pytest.mark.parametrize("role", list(Role))
def test_role_matrix_and_foreign_keys(database: Engine, role: Role) -> None:
    email, _, org = add_user(database, role)
    foreign, _, other = add_user(database)
    url = collection(database, org)
    foreign_url = collection(database, other)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        fh = login(client, foreign)
        kid = client.post(foreign_url, json={"label": "Fixture"}, headers=fh).json()["key"]["id"]
        headers = login(client, email)
        assert client.get(foreign_url).status_code == 404
        assert (
            client.post(foreign_url, headers=headers, json={"label": "Another"}).status_code == 404
        )
        for action in ("rotate", "revoke"):
            assert client.post(f"{foreign_url}/{kid}/{action}", headers=headers).status_code == 404
            assert client.post(f"{url}/{kid}/{action}", headers=headers).status_code == (
                404 if role in (Role.OWNER, Role.DEVELOPER) else 403
            )
        assert client.get(url).status_code == (403 if role == Role.VIEWER else 200)
        assert (
            client.post(url, headers={"Origin": ORIGIN}, json={"label": "Local"}).status_code
            == 403
        )
        assert client.post(url, headers=headers, json={"label": "Local"}).status_code == (
            201 if role in (Role.OWNER, Role.DEVELOPER) else 403
        )


def test_key_list_rejects_cross_project_and_unknown_cursors(database: Engine) -> None:
    email, _, org = add_user(database)
    base = collection(database, org)
    other = collection(database, org, "other")
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        issued = client.post(other, json={"label": "Other"}, headers=headers).json()
        assert client.get(base, params={"after": issued["key"]["prefix"]}).status_code == 400
        assert client.get(base, params={"after": "asi_" + "0" * 16}).status_code == 400


def test_concurrent_rotation_creates_one_replacement(database: Engine) -> None:
    email, _, org = add_user(database)
    base = collection(database, org)
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client, email)
        kid = client.post(base, headers=headers, json={"label": "Original"}).json()["key"]["id"]
    barrier = Barrier(2)

    def rotate() -> int:
        with TestClient(app, base_url=ORIGIN) as other:
            h = login(other, email)
            barrier.wait(timeout=10)
            return other.post(f"{base}/{kid}/rotate", headers=h).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(rotate) for _ in range(2)]
        assert sorted(f.result() for f in futures) == [201, 409]
    with transaction(database) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(IngestionKey)
                .where(IngestionKey.revoked_at.is_(None))
            )
            == 1
        )


def test_key_migration_and_failed_rotation_preserve_live_credential(
    database: Engine, config: Config
) -> None:
    command.downgrade(config, "0004_api_inventory")
    assert "ingestion_keys" not in inspect(database).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
    email, _, org = add_user(database)
    base = collection(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        key = client.post(base, json={"label": "Rollback"}, headers=headers).json()
        with database.begin() as conn:
            conn.execute(text("create unique index reject_replacement on ingestion_keys(label)"))
        assert client.post(f"{base}/{key['key']['id']}/rotate", headers=headers).status_code == 503
        with database.begin() as conn:
            conn.execute(text("drop index reject_replacement"))
        assert (
            client.post(
                base + "/check", headers={"Authorization": "Bearer " + key["secret"]}
            ).status_code
            == 204
        )
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0004_api_inventory")
    command.check(config)
    with transaction(database) as db:
        assert (
            db.scalars(
                select(AuditEntry.action).where(AuditEntry.action == Action.KEY_REVOKED)
            ).first()
            is None
        )
