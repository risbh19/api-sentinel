from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from test_detection_rules import drain
from test_event_jobs import emit, project

from api_sentinel.retention import expire_batch


def test_preview_and_bounded_expiry_preserve_other_projects_and_unfinished_jobs(
    database: Engine,
) -> None:
    target, other = project(database), project(database)
    emit(database, target, "locked", "old", "recent", "pending", "running", "dead")
    emit(database, other, "foreign")
    drain(database)
    with database.begin() as conn:
        conn.execute(
            text("""
            UPDATE security_events SET received_at=now()-interval '31 days'
            WHERE external_event_id <> 'recent'
        """)
        )
        conn.execute(
            text("""
            UPDATE event_jobs j SET state=e.external_event_id FROM security_events e
            WHERE j.event_id=e.id AND e.external_event_id IN ('pending','running','dead')
        """)
        )
    assert expire_batch(database, target, 30, 1, apply=False) == 1
    assert expire_batch(database, target, 30, 100, apply=False) == 2
    with database.begin() as busy:
        busy.execute(
            text("SELECT id FROM security_events WHERE external_event_id='locked' FOR UPDATE")
        )
        assert expire_batch(database, target, 30, 1, apply=True) == 1
        assert expire_batch(database, target, 30, 1, apply=True) == 0
    assert expire_batch(database, target, 30, 1, apply=True) == 1
    assert expire_batch(database, target, 30, 1, apply=True) == 0
    with database.connect() as conn:
        assert set(conn.scalars(text("SELECT external_event_id FROM security_events"))) == {
            "foreign",
            "recent",
            "pending",
            "running",
            "dead",
        }
        assert conn.scalar(text("SELECT count(*) FROM event_jobs")) == 5


def test_retention_rejects_unknown_scope_and_invalid_limits(database: Engine) -> None:
    with pytest.raises(ValueError, match="Project does not exist"):
        expire_batch(database, uuid4(), 30, 500, apply=True)
    for days, limit in ((0, 1), (3651, 1), (30, 0), (30, 1001)):
        with pytest.raises(ValueError, match="retention days"):
            expire_batch(database, uuid4(), days, limit, apply=True)
