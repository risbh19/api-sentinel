from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from api_sentinel.database import open_engine, transaction
from api_sentinel.organizations.models import Organization
from api_sentinel.organizations.records import OrganizationRecords, create_organization


def test_migration_round_trip(empty_database: Engine, config: Config) -> None:
    assert inspect(empty_database).get_table_names() == []
    command.upgrade(config, "head")
    with transaction(empty_database) as session:
        owner = create_organization(session, "Synthetic organization")
        project = OrganizationRecords(session, owner.id).create_project("Test project", "test")
    command.upgrade(config, "head")
    with transaction(empty_database) as session:
        assert OrganizationRecords(session, owner.id).project(project.id) is not None
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(empty_database).get_table_names()) == {"alembic_version"}
    command.upgrade(config, "head")
    command.check(config)
    with transaction(empty_database) as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 0


def test_organization_and_project_lifecycle(database: Engine) -> None:
    with transaction(database) as session:
        org = create_organization(session, "Synthetic team")
        records = OrganizationRecords(session, org.id)
        assert records.organization() is org
        updated = records.rename_organization("Platform")
        assert updated is not None and updated.name == "Platform"
        project = records.create_project("Main API", "main-api")
        assert project.created_at.utcoffset() is not None
        renamed = records.rename_project(project.id, "Gateway")
        assert renamed is not None and renamed.name == "Gateway"
    with transaction(database) as session:
        records = OrganizationRecords(session, org.id)
        assert [p.name for p in records.projects()] == ["Gateway"]
        assert records.delete_project(project.id)
        assert records.project(project.id) is None
        assert records.delete_organization()
        assert records.organization() is None


def test_foreign_project_is_invisible_to_reads_and_writes(database: Engine) -> None:
    with transaction(database) as session:
        first = OrganizationRecords(session, create_organization(session, "Alpha").id)
        second = OrganizationRecords(session, create_organization(session, "Beta").id)
        first.create_project("Alpha API", "shared")
        other = second.create_project("Beta API", "shared")
        assert [p.name for p in first.projects()] == ["Alpha API"]
        assert first.project(other.id) is None
        assert first.rename_project(other.id, "Another name") is None
        assert not first.delete_project(other.id)
    with transaction(database) as session:
        found = OrganizationRecords(session, other.organization_id).project(other.id)
        assert found is not None and found.name == "Beta API"


def test_duplicate_slug_rolls_back_the_entire_unit_of_work(database: Engine) -> None:
    with pytest.raises(IntegrityError), transaction(database) as session:
        org = create_organization(session, "Temporary")
        records = OrganizationRecords(session, org.id)
        records.create_project("One", "same")
        records.create_project("Two", "same")
    with transaction(database) as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 0


def test_organization_must_exist_and_cannot_be_removed_while_projects_remain(
    database: Engine,
) -> None:
    with pytest.raises(IntegrityError), transaction(database) as session:
        OrganizationRecords(session, uuid4()).create_project("Orphan", "orphan")
    with transaction(database) as session:
        org = create_organization(session, "Team")
        project = OrganizationRecords(session, org.id).create_project("API", "api")
    with pytest.raises(IntegrityError), transaction(database) as session:
        OrganizationRecords(session, org.id).delete_organization()
    with transaction(database) as session:
        assert OrganizationRecords(session, org.id).project(project.id) is not None


@pytest.mark.parametrize(("name", "slug"), [("  ", "test"), ("Valid", "UPPER"), ("Valid", "a--b")])
def test_database_rejects_invalid_record_fields(database: Engine, name: str, slug: str) -> None:
    with pytest.raises(IntegrityError), transaction(database) as session:
        records = OrganizationRecords(session, create_organization(session, "Team").id)
        records.create_project(name, slug)


def test_project_pages_have_a_stable_scoped_order(database: Engine) -> None:
    with transaction(database) as session:
        records = OrganizationRecords(session, create_organization(session, "Team").id)
        for slug in ("z", "a", "m"):
            records.create_project(slug, slug)
        page = records.projects(limit=2)
        assert [p.slug for p in page] == ["a", "m"]
        assert [p.slug for p in records.projects(after_slug=page[-1].slug)] == ["z"]
        with pytest.raises(ValueError):
            records.projects(limit=101)


def test_text_round_trip_uses_utf8_even_with_legacy_client_default(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PGCLIENTENCODING", "SQL_ASCII")
    engine = open_engine()
    try:
        with transaction(engine) as session:
            org = create_organization(session, "Équipe démo")
        with transaction(engine) as session:
            found = OrganizationRecords(session, org.id).organization()
            assert found is not None and found.name == "Équipe démo"
    finally:
        engine.dispose()
