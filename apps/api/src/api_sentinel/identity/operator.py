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

from api_sentinel.audit.records import Action, record
from api_sentinel.database import open_engine, transaction
from api_sentinel.organizations.models import Organization
from api_sentinel.organizations.records import OrganizationRecords, create_organization

from .models import Membership, User
from .security import HASHER, Role, display_name, normalized_email


def prepare() -> None:
    passwords = {
        "sentinel_app": os.environ["SENTINEL_APP_PASSWORD"],
        "sentinel_worker": os.environ["SENTINEL_WORKER_PASSWORD"],
    }
    if any(len(value) < 32 for value in passwords.values()):
        raise SystemExit("Run scripts/init_env.py to generate the service credentials")
    command.upgrade(Config("alembic.ini"), "head")
    with psycopg.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(173824, 2)")
        for name, password in passwords.items():
            role = sql.Identifier(name)
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
            verifier = conn.pgconn.encrypt_password(
                password.encode(), name.encode(), b"scram-sha-256"
            ).decode()
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(role, sql.Literal(verifier)))
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(conn.info.dbname), role
                )
            )
        grant_table_access(conn)


def grant_table_access(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute("GRANT USAGE ON SCHEMA public TO sentinel_app, sentinel_worker")
    conn.execute("GRANT INSERT (event_id) ON event_jobs TO sentinel_app")
    conn.execute(
        "GRANT SELECT, UPDATE (state, attempts, available_at, last_error_code, delivery_delay_ms) ON event_jobs TO sentinel_worker"
    )
    conn.execute(
        "GRANT SELECT (id, project_id, source_id, external_event_id, occurred_at, received_at, "
        "event_type, actor_hash, client_hash, method, route_template) ON security_events TO sentinel_worker"
    )
    conn.execute("GRANT SELECT, INSERT, UPDATE (evidence) ON rule_findings TO sentinel_worker")
    conn.execute("GRANT SELECT, INSERT ON alerts TO sentinel_worker")
    conn.execute("GRANT SELECT, INSERT, DELETE ON alert_evidence TO sentinel_worker")
    conn.execute("GRANT SELECT (id) ON alerts TO sentinel_app")
    conn.execute(
        "GRANT SELECT, INSERT, UPDATE (status, assignee_id, resolved_at, version) ON incidents TO sentinel_app"
    )
    conn.execute("GRANT SELECT, INSERT ON incident_activity, incident_alerts TO sentinel_app")
    conn.execute("GRANT SELECT ON alert_summaries, alert_evidence TO sentinel_app")
    conn.execute("GRANT SELECT, INSERT ON api_imports, api_endpoints TO sentinel_app")
    conn.execute("GRANT SELECT, INSERT ON event_sources, security_events TO sentinel_app")
    conn.execute("GRANT SELECT, INSERT, UPDATE ON ingestion_state TO sentinel_app")
    conn.execute(
        "GRANT SELECT, INSERT (project_id, label, prefix, key_hash, last_used_at, revoked_at), "
        "UPDATE (revoked_at, last_used_at) ON ingestion_keys TO sentinel_app"
    )
    conn.execute("GRANT SELECT ON audit_entries TO sentinel_app")
    conn.execute(
        "GRANT INSERT (action, organization_id, project_id, actor_id, key_id, subject_user_id, "
        "old_role, new_role, incident_id, incident_version, request_id) ON audit_entries TO sentinel_app"
    )
    conn.execute("GRANT SELECT ON users, organizations TO sentinel_app")
    conn.execute("GRANT UPDATE (name) ON organizations TO sentinel_app")
    conn.execute("GRANT SELECT, INSERT, DELETE ON web_sessions TO sentinel_app")
    conn.execute("GRANT SELECT, INSERT, UPDATE ON login_windows TO sentinel_app")
    conn.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON projects, organization_memberships TO sentinel_app"
    )


def provision(
    email: str,
    password: str,
    organization: str | None,
    organization_id: UUID | None = None,
    *,
    demo: bool = False,
) -> None:
    if demo:
        if organization is not None or organization_id is not None:
            raise ValueError("The demo requires a new, isolated organization")
        organization = "Synthetic demo team"
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
            record(db, Action.ACCOUNT_CREATED, subject_user_id=user.id)
            if organization is not None:
                org = create_organization(db, organization)
                organization_id = org.id
                if demo:
                    project = OrganizationRecords(db, org.id).create_project(
                        "Synthetic login demo", "synthetic-login"
                    )
                    record(
                        db, Action.PROJECT_CREATED, organization_id=org.id, project_id=project.id
                    )
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
                record(
                    db,
                    Action.MEMBER_ADDED,
                    organization_id=organization_id,
                    subject_user_id=user.id,
                    new_role=Role.OWNER,
                )
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
    group.add_argument(
        "--demo", action="store_true", help="Create an isolated synthetic demo team and project"
    )
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
        provision(
            args.email, password, args.new_organization, args.organization_id, demo=args.demo
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except IntegrityError:
        raise SystemExit(
            "User creation failed. Check whether the account already exists."
        ) from None


if __name__ == "__main__":
    main()
