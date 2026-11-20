import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from access_helpers import ORIGIN, add_user, login
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from api_sentinel.audit.records import Action, AuditEntry
from api_sentinel.database import transaction
from api_sentinel.identity.security import Role
from api_sentinel.inventory.models import Endpoint, ImportRevision
from api_sentinel.inventory.parser import MAX_BYTES
from api_sentinel.main import create_app
from api_sentinel.organizations.records import OrganizationRecords


def document(path: str) -> bytes:
    return json.dumps(
        {
            "openapi": "3.1.1",
            "info": {"title": "private example", "version": "1"},
            "paths": {path: {"get": {"operationId": "read"}, "put": {"security": []}}},
        }
    ).encode()


def project(engine: Engine, org: UUID) -> str:
    with transaction(engine) as db:
        return f"/api/v1/projects/{OrganizationRecords(db, org).create_project('Synthetic', 'api').id}"


@pytest.mark.parametrize("role", list(Role))
def test_inventory_roles_and_project_isolation(database: Engine, role: Role) -> None:
    email, _, org = add_user(database, role)
    other, _, foreign_org = add_user(database)
    base, foreign = project(database, org), project(database, foreign_org)
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(base + "/endpoints").status_code == 401
        fh = {**login(client, other), "Content-Type": "application/json"}
        assert (
            client.post(foreign + "/imports", content=document("/foreign"), headers=fh).status_code
            == 201
        )
        headers = {**login(client, email), "Content-Type": "application/json"}
        for suffix in ("/imports", "/endpoints", "/endpoints?revision=1"):
            assert client.get(foreign + suffix).status_code == 404
        assert (
            client.post(
                foreign + "/imports", content=document("/foreign"), headers=headers
            ).status_code
            == 404
        )
        assert client.get(base + "/imports").json() == []
        assert client.get(base + "/endpoints").json()["revision"] is None
        assert (
            client.post(
                base + "/imports",
                content=document("/local"),
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            ).status_code
            == 403
        )
        data = client.post(base + "/imports", content=document("/local"), headers=headers)
        assert data.status_code == (403 if role == Role.VIEWER else 201)
        if role != Role.VIEWER:
            assert client.get(base + "/endpoints").json()["entries"][0]["path"] == "/local"


def test_revisions_atomicity_paging_and_duplicate_history(database: Engine) -> None:
    email, _, org = add_user(database)
    base = project(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = {**login(client, email), "Content-Type": "application/json"}
        for path, expected in (("/first", 201), ("/second", 201), ("/first", 200)):
            result = client.post(base + "/imports", headers=headers, content=document(path))
            assert result.status_code == expected
        assert result.json()["revision"] == 1
        a = client.get(base + "/imports", params={"limit": 1}).json()
        assert a[0]["revision"] == 2 and "private example" not in str(a)
        assert client.get(base + "/imports?before=2").json()[0]["revision"] == 1
        page = client.get(base + "/endpoints?limit=1").json()
        assert page["revision"]["revision"] == 2 and page["next_offset"] == 1
        assert page["entries"][0]["path"] == "/second"
        assert (
            client.get(base + "/endpoints?revision=2&offset=1").json()["entries"][0]["method"]
            == "PUT"
        )
        assert (
            client.get(base + "/endpoints?revision=1&method=GET").json()["entries"][0]["path"]
            == "/first"
        )
        assert client.get(base + "/endpoints?revision=999").status_code == 404
        assert (
            client.post(base + "/imports", content=b"not JSON", headers=headers).status_code == 422
        )
        assert (
            client.post(
                base + "/imports", content=iter([b" " * 8192] * 17), headers=headers
            ).status_code
            == 413
        )
        assert (
            client.post(
                base + "/imports", content=b"{}", headers={**headers, "Content-Encoding": "gzip"}
            ).status_code
            == 415
        )
        assert (
            client.post(
                base + "/imports", content=b"{}", headers={**headers, "Content-Type": "text/plain"}
            ).status_code
            == 415
        )
        assert client.get(base + "/imports").json()[0]["revision"] == 2
        assert (
            client.post(
                "/api/v1/auth/login", content=b" " * (MAX_BYTES // 2), headers=headers
            ).status_code
            == 413
        )
    with transaction(database) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEntry)
                .where(AuditEntry.action == Action.INVENTORY_IMPORTED)
            )
            == 2
        )
        assert db.scalar(select(func.count()).select_from(Endpoint)) == 4


def test_simultaneous_identical_files_have_one_revision(database: Engine) -> None:
    email, _, org = add_user(database)
    base = project(database, org)
    app = create_app(engine=database)
    barrier = Barrier(2)

    def upload() -> int:
        with TestClient(app, base_url=ORIGIN) as client:
            headers = {**login(client, email), "Content-Type": "application/json"}
            barrier.wait(timeout=10)
            return client.post(
                base + "/imports", headers=headers, content=document("/one")
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        jobs = [workers.submit(upload) for _ in range(2)]
        assert sorted(j.result() for j in jobs) == [200, 201]
    with transaction(database) as db:
        assert db.scalar(select(func.count()).select_from(ImportRevision)) == 1


def test_migration_preserves_audited_imports_on_rollback(database: Engine, config: Config) -> None:
    command.downgrade(config, "0003_audit_activity")
    assert "api_imports" not in inspect(database).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
    email, _, org = add_user(database)
    base = project(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = {**login(client, email), "Content-Type": "application/json"}
        assert (
            client.post(base + "/imports", headers=headers, content=document("/one")).status_code
            == 201
        )
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0003_audit_activity")
    with transaction(database) as db:
        assert db.scalar(select(func.count()).select_from(ImportRevision)) == 1
    command.check(config)
