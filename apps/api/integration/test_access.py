from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from api_sentinel.database import transaction
from api_sentinel.identity.models import Membership, User, WebSession
from api_sentinel.identity.operator import provision
from api_sentinel.identity.security import COOKIE, HASHER, Role, digest
from api_sentinel.main import create_app
from api_sentinel.organizations.records import OrganizationRecords, create_organization

ORIGIN = "http://127.0.0.1:8080"
PASSWORD = "synthetic-access-test-password"


def add_user(engine: Engine, role: Role = Role.OWNER) -> tuple[str, UUID, UUID]:
    email = f"{uuid4().hex}@example.test"
    with transaction(engine) as session:
        user = User(email=email, password_hash=HASHER.hash(PASSWORD))
        session.add(user)
        org = create_organization(session, "Test team")
        session.add(Membership(organization_id=org.id, user_id=user.id, role=role))
        return email, user.id, org.id


def login(client: TestClient, email: str, origin: str = ORIGIN) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email.upper(), "password": PASSWORD},
        headers={"Origin": origin},
    )
    assert response.status_code == 200, response.text
    return {"Origin": origin, "X-CSRF-Token": response.json()["csrf_token"]}


def test_session_rotation_csrf_and_revocation(database: Engine) -> None:
    email, _, org = add_user(database)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        headers = login(client, email)
        first = client.cookies[COOKIE]
        assert client.get("/api/v1/auth/me").json()["organizations"][0]["id"] == str(org)
        assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/logout", headers={**headers, "Origin": "https://other.example"}
            ).status_code
            == 403
        )
        headers = login(client, email)
        token = client.cookies[COOKIE]
        assert token != first
        with transaction(database) as session:
            assert session.get(WebSession, digest(first)) is None
            assert session.get(WebSession, digest(token)) is not None
            assert session.get(WebSession, token) is None
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        client.cookies.clear()
        client.cookies.set(COOKIE, token)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rejects_foreign_origins_and_hides_fields(database: Engine) -> None:
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        body = {"email": "missing@example.test", "password": PASSWORD}
        assert client.post("/api/v1/auth/login", json=body).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/login", json=body, headers={"Origin": "https://other.example"}
            ).status_code
            == 403
        )
        invalid = client.post(
            "/api/v1/auth/login", json={**body, "email": "invalid"}, headers={"Origin": ORIGIN}
        )
        assert invalid.status_code == 422 and PASSWORD not in invalid.text
        assert invalid.headers["Cache-Control"] == "no-store"


def test_invalid_login_is_throttled_and_has_generic_errors(database: Engine) -> None:
    email, uid, _ = add_user(database)
    with transaction(database) as db:
        db.execute(update(User).where(User.id == uid).values(active=False))
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:

        def attempt(address: str) -> tuple[int, str]:
            res = client.post(
                "/api/v1/auth/login",
                json={"email": address, "password": PASSWORD},
                headers={"Origin": ORIGIN},
            )
            return res.status_code, res.text

        denied = attempt("missing@example.test")
        assert denied[0] == 401 and attempt(email) == denied
        # Even across one clock-minute boundary the bucket fills within 17 further attempts.
        assert any(attempt(email)[0] == 429 for _ in range(17))


def test_expiry_inactive_accounts_and_secure_cookies(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = "https://sentinel.example.test"
    monkeypatch.setenv("SENTINEL_WEB_ORIGIN", origin)
    email, uid, _ = add_user(database)
    with TestClient(create_app(engine=database), base_url=origin) as client:
        res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={"Origin": origin},
        )
        assert res.status_code == 200
        cookie = res.headers["set-cookie"].lower()
        assert all(s in cookie for s in ("httponly", "secure", "samesite=strict", "path=/api/v1"))
        with transaction(database) as db:
            db.execute(
                update(WebSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert client.get("/api/v1/auth/me").status_code == 401
        login(client, email, origin)
        with transaction(database) as db:
            db.execute(update(User).where(User.id == uid).values(active=False))
        assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("role", list(Role))
def test_project_permissions_and_cross_tenant_reads_writes(database: Engine, role: Role) -> None:
    email, uid, org = add_user(database, role)
    _, _, other = add_user(database)
    with transaction(database) as db:
        local = OrganizationRecords(db, org).create_project("Local", "local")
        foreign = OrganizationRecords(db, other).create_project("Foreign", "foreign")
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        assert client.get(f"/api/v1/projects/{local.id}").status_code == 200
        assert client.get(f"/api/v1/projects/{foreign.id}").status_code == 404
        assert client.get(f"/api/v1/organizations/{other}/projects").status_code == 404
        project = {"name": "Another", "slug": "another"}

        def collection(oid: UUID) -> str:
            return f"/api/v1/organizations/{oid}/projects"

        assert client.post(collection(other), json=project, headers=headers).status_code == 404
        assert (
            client.delete(f"{collection(other)}/{foreign.id}", headers=headers).status_code == 404
        )
        assert client.post(collection(org), json=project, headers=headers).status_code == (
            201 if role in {Role.OWNER, Role.DEVELOPER} else 403
        )
        assert client.delete(f"{collection(org)}/{local.id}", headers=headers).status_code == (
            204 if role == Role.OWNER else 403
        )
        assert client.put(
            f"/api/v1/organizations/{org}/members/{uid}", json={"role": "owner"}, headers=headers
        ).status_code == (204 if role == Role.OWNER else 403)
        listing = client.get(collection(org))
        assert listing.status_code == 200 and str(foreign.id) not in listing.text


def test_membership_changes_apply_to_an_existing_session(database: Engine) -> None:
    owner, uid, org = add_user(database)
    second, target, _ = add_user(database)
    path = f"/api/v1/organizations/{org}/members"
    projects = f"/api/v1/organizations/{org}/projects"
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as admin, TestClient(app, base_url=ORIGIN) as member:
        oh = login(admin, owner)
        mh = login(member, second)
        assert admin.delete(f"{path}/{uid}", headers=oh).status_code == 409
        assert admin.put(f"{path}/{uid}", json={"role": "viewer"}, headers=oh).status_code == 409
        assert (
            admin.put(f"{path}/{target}", json={"role": "developer"}, headers=oh).status_code
            == 204
        )
        assert (
            member.post(projects, json={"name": "App", "slug": "app"}, headers=mh).status_code
            == 201
        )
        assert (
            admin.put(f"{path}/{target}", json={"role": "viewer"}, headers=oh).status_code == 204
        )
        assert (
            member.post(projects, json={"name": "Other", "slug": "other"}, headers=mh).status_code
            == 403
        )
        assert admin.delete(f"{path}/{target}", headers=oh).status_code == 204
        assert member.get(projects).status_code == 404


def test_initial_owner_can_claim_an_existing_project_after_upgrade(
    empty_database: Engine, config: Config
) -> None:
    command.upgrade(config, "0001_project_records")
    with transaction(empty_database) as db:
        org = create_organization(db, "Existing team")
        project = OrganizationRecords(db, org.id).create_project("Existing API", "existing")
    command.upgrade(config, "head")
    provision("owner@example.test", PASSWORD, None, org.id)
    with pytest.raises(ValueError, match="already has members"):
        provision("other@example.test", PASSWORD, None, org.id)
    with transaction(empty_database) as db:
        assert db.scalar(select(User.id).where(User.email == "other@example.test")) is None
    with TestClient(create_app(engine=empty_database), base_url=ORIGIN) as client:
        login(client, "owner@example.test")
        assert client.get(f"/api/v1/projects/{project.id}").status_code == 200
    command.downgrade(config, "0001_project_records")
    with transaction(empty_database) as db:
        assert OrganizationRecords(db, org.id).project(project.id) is not None


def test_direct_api_bounds_streamed_login_input(database: Engine) -> None:
    with TestClient(create_app(engine=database)) as client:
        res = client.post(
            "/api/v1/auth/login",
            content=iter([b" " * 8192] * 3),
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
        )
        assert res.status_code == 413


def test_database_text_rejects_control_characters(database: Engine) -> None:
    email, _, org = add_user(database)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        bad = client.post(
            "/api/v1/auth/login",
            json={"email": "invalid\x00@example.test", "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert bad.status_code == 422 and PASSWORD not in bad.text
        headers = login(client, email)
        bad = client.post(
            f"/api/v1/organizations/{org}/projects",
            json={"name": "Bad\x00Name", "slug": "bad"},
            headers=headers,
        )
        assert bad.status_code == 422 and "Bad" not in bad.text
    with pytest.raises(ValueError, match="control characters"):
        provision("another@example.test", PASSWORD, "Bad\x00Name")
