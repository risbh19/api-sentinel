from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api_sentinel.database import transaction
from api_sentinel.identity.models import Membership, User
from api_sentinel.identity.security import HASHER, Role
from api_sentinel.organizations.records import create_organization

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
