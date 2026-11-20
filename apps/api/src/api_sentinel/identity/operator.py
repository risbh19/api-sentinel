"""Local operator entry points for schema access and initial identities."""

import argparse
import getpass
import os
import sys
from uuid import UUID

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api_sentinel.database import open_engine, transaction
from api_sentinel.organizations.models import Organization
from api_sentinel.organizations.records import create_organization

from .models import Membership, User
from .security import HASHER, Role, display_name, normalized_email


def prepare() -> None:
    password = os.environ["SENTINEL_APP_PASSWORD"]
    if len(password) < 32:
        raise SystemExit("Run scripts/init_env.py to generate the application credential")
    command.upgrade(Config("alembic.ini"), "head")
    with psycopg.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(173824, 2)")
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='sentinel_app'").fetchone():
            conn.execute("CREATE ROLE sentinel_app LOGIN")
        verifier = conn.pgconn.encrypt_password(
            password.encode(), b"sentinel_app", b"scram-sha-256"
        ).decode()
        conn.execute(sql.SQL("ALTER ROLE sentinel_app PASSWORD {}").format(sql.Literal(verifier)))
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO sentinel_app").format(
                sql.Identifier(conn.info.dbname)
            )
        )
        conn.execute("GRANT USAGE ON SCHEMA public TO sentinel_app")
        conn.execute("GRANT SELECT ON users, organizations TO sentinel_app")
        conn.execute("GRANT UPDATE (name) ON organizations TO sentinel_app")
        conn.execute("GRANT SELECT, INSERT, DELETE ON web_sessions TO sentinel_app")
        conn.execute("GRANT SELECT, INSERT, UPDATE ON login_windows TO sentinel_app")
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON projects, organization_memberships TO sentinel_app"
        )


def provision(
    email: str, password: str, organization: str | None, organization_id: UUID | None = None
) -> None:
    email = normalized_email(email)
    if not 12 <= len(password) <= 256:
        raise ValueError("Password length must be 12 to 256 characters")
    if organization is not None:
        organization = display_name(organization)
    encoded = HASHER.hash(password)
    engine = open_engine()
    try:
        with transaction(engine) as db:
            user = User(email=email, password_hash=encoded)
            db.add(user)
            db.flush()
            if organization is not None:
                org = create_organization(db, organization)
                organization_id = org.id
            elif organization_id is not None:
                locked = db.scalar(
                    select(Organization.id)
                    .where(Organization.id == organization_id)
                    .with_for_update()
                )
                if locked is None:
                    raise ValueError("Organization does not exist")
                existing = db.scalar(
                    select(Membership.user_id)
                    .where(Membership.organization_id == organization_id)
                    .limit(1)
                )
                if existing is not None:
                    raise ValueError("This organization already has members")
            if organization_id is not None:
                db.add(
                    Membership(organization_id=organization_id, user_id=user.id, role=Role.OWNER)
                )
        print(f"Created user {user.id}")
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    user = commands.add_parser("create-user")
    user.add_argument("email")
    group = user.add_mutually_exclusive_group()
    group.add_argument("--new-organization")
    group.add_argument("--organization-id", type=UUID)
    user.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
        return
    password = (
        sys.stdin.readline().rstrip("\r\n")
        if args.password_stdin
        else getpass.getpass("New password: ")
    )
    try:
        provision(args.email, password, args.new_organization, args.organization_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except IntegrityError:
        raise SystemExit(
            "User creation failed. Check whether the account already exists."
        ) from None


if __name__ == "__main__":
    main()
