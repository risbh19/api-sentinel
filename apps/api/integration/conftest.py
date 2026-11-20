from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine

from api_sentinel.database import open_engine

API = Path(__file__).resolve().parents[1]


@pytest.fixture
def config() -> Config:
    return Config(str(API / "alembic.ini"))


@pytest.fixture
def empty_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    # Create a fresh database. Never downgrade the database named in the environment.
    name = "sentinel_test_" + uuid4().hex
    with psycopg.connect(dbname="postgres", autocommit=True, connect_timeout=3) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
        )
        try:
            monkeypatch.setenv("PGDATABASE", name)
            engine = open_engine()
            try:
                yield engine
            finally:
                engine.dispose()
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def database(empty_database: Engine, config: Config) -> Engine:
    command.upgrade(config, "head")
    return empty_database
