import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session


def open_engine(*, application: bool = False) -> Engine:
    """Create one bounded pool per owner. libpq reads the password from its environment."""
    required = ("PGHOST", "PGDATABASE", "PGUSER")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise ValueError("Missing database settings: " + ", ".join(missing))
    raw_port = os.environ.get("PGPORT", "5432")
    if not raw_port.isascii() or not raw_port.isdecimal() or not 1 <= int(raw_port) <= 65535:
        raise ValueError("PGPORT must be an integer between 1 and 65535")
    if application and not os.environ.get("SENTINEL_APP_PASSWORD"):
        raise ValueError("Missing SENTINEL_APP_PASSWORD")
    url = URL.create(
        "postgresql+psycopg",
        host=os.environ["PGHOST"],
        port=int(raw_port),
        database=os.environ["PGDATABASE"],
        username="sentinel_app" if application else os.environ["PGUSER"],
        password=os.environ["SENTINEL_APP_PASSWORD"] if application else None,
    )
    return create_engine(
        url,
        pool_size=4,
        max_overflow=0,
        pool_timeout=3,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 3,
            "client_encoding": "UTF8",
            "options": "-csearch_path=public",
        },
    )


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    """Commit one unit of work on success and roll it back on failure."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        yield session
