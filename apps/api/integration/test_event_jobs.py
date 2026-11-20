import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from api_sentinel.database import transaction
from api_sentinel.ingestion.events import EventBatch
from api_sentinel.ingestion.records import ingest
from api_sentinel.organizations.records import OrganizationRecords, create_organization
from api_sentinel.worker import BATCH_SIZE, MAX_ATTEMPTS, claim, process, status


def project(database: Engine) -> UUID:
    with transaction(database) as db:
        org = create_organization(db, "Synthetic organization")
        return OrganizationRecords(db, org.id).create_project("Demo", "demo").id


def emit(database: Engine, owner: UUID, *ids: str) -> int:
    batch = EventBatch.model_validate(
        {
            "source_id": "synthetic",
            "events": [
                {
                    "event_id": external,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "event_type": "request",
                    "method": "GET",
                    "route_template": "/widgets",
                    "status_code": 200,
                }
                for external in ids
            ],
        }
    )
    with transaction(database) as db:
        return ingest(db, owner, batch, bytes(32))


def due(database: Engine) -> None:
    # Advance only the due time in the disposable database, using PostgreSQL's clock.
    with database.begin() as conn:
        conn.execute(text("UPDATE event_jobs SET available_at = now() - interval '1 second'"))


def test_upgrade_backfills_and_ingestion_enqueues_atomically(
    database: Engine, config: Config
) -> None:
    command.downgrade(config, "0006_security_events")
    owner = project(database)
    assert emit(database, owner, "legacy") == 1
    command.upgrade(config, "head")
    assert emit(database, owner, "legacy", "new", "new") == 1
    assert status(database)["pending"] == 2
    with database.begin() as conn:
        conn.execute(text("ALTER TABLE event_jobs ADD CHECK (false) NOT VALID"))
    with pytest.raises(IntegrityError):
        emit(database, owner, "must-rollback")
    with database.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM security_events")).scalar_one() == 2
        conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": owner})
    assert status(database)["pending"] == 0


def test_two_workers_claim_disjoint_bounded_batches(database: Engine) -> None:
    count = BATCH_SIZE * 2 + 1
    assert emit(database, project(database), *(f"item-{i}" for i in range(count))) == count
    barrier = Barrier(2)

    def simultaneous() -> list[tuple[UUID, int]]:
        barrier.wait(timeout=10)
        return claim(database)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(simultaneous) for _ in range(2)]
        first, second = [future.result() for future in futures]
    assert len(first) == len(second) == BATCH_SIZE
    assert set(first).isdisjoint(second)
    assert len(claim(database)) == 1
    assert claim(database) == []


def test_crash_after_claim_and_replacement_worker(database: Engine) -> None:
    assert emit(database, project(database), "recover") == 1
    crash = subprocess.run(
        [
            sys.executable,
            "-c",
            """import os
from api_sentinel.database import open_engine
from api_sentinel.worker import claim
assert len(claim(open_engine())) == 1
os._exit(17)
""",
        ],
        check=False,
    )
    assert crash.returncode == 17 and claim(database) == []
    due(database)
    [(event_id, attempt)] = claim(database)
    assert attempt == 2 and not process(database, event_id, 1)
    assert process(database, event_id, attempt)
    assert not process(database, event_id, attempt)
    assert claim(database) == [] and status(database)["succeeded"] == 1
    with database.connect() as conn:
        assert conn.execute(text("SELECT delivery_delay_ms FROM event_jobs")).scalar_one() >= 0


def test_handler_rollback_backoff_and_dead_letter(database: Engine) -> None:
    assert emit(database, project(database), "poison") == 1

    def fail(conn: Connection, event_id: UUID) -> int:
        conn.execute(
            text("UPDATE event_jobs SET delivery_delay_ms=99 WHERE event_id=:id"), {"id": event_id}
        )
        raise ValueError("private synthetic marker")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        [(event_id, generation)] = claim(database)
        assert generation == attempt and not process(database, event_id, attempt, fail)
        with database.connect() as conn:
            delay, result, code = conn.execute(
                text(
                    "SELECT extract(epoch FROM available_at-now()), delivery_delay_ms, last_error_code FROM event_jobs"
                )
            ).one()
            assert 2 ** (attempt - 1) - 1 < delay <= 2 ** (attempt - 1)
            assert result is None and code == "processing_failed"
        assert claim(database) == []
        due(database)
    assert claim(database) == [] and status(database)["dead"] == 1


def test_repeated_crashes_exhaust_budget(database: Engine) -> None:
    assert emit(database, project(database), "abandoned") == 1
    for attempt in range(1, MAX_ATTEMPTS + 1):
        [(_, generation)] = claim(database)
        assert generation == attempt
        due(database)
    assert claim(database) == [] and status(database)["dead"] == 1
    with database.connect() as conn:
        assert (
            conn.execute(text("SELECT last_error_code FROM event_jobs")).scalar_one()
            == "lease_expired"
        )
