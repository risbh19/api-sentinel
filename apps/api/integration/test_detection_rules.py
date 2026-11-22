from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
from threading import Barrier
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from api_sentinel.database import transaction
from api_sentinel.detections.rules import (
    AUTH_DENIALS,
    AUTH_FAILURES,
    DEFAULT_RULES,
    REQUEST_VOLUME,
    Rule,
    RuleSet,
    evaluate_event,
)
from api_sentinel.ingestion.events import EventBatch
from api_sentinel.ingestion.records import ingest
from api_sentinel.organizations.records import OrganizationRecords, create_organization
from api_sentinel.worker import claim, process


def project(engine: Engine) -> UUID:
    with transaction(engine) as db:
        org = create_organization(db, "Synthetic organization")
        return OrganizationRecords(db, org.id).create_project("Example", "example").id


def sample(rule: Rule, label: str, stamp: datetime, **changes: object) -> dict[str, object]:
    kind, code = {
        AUTH_FAILURES: ("authentication_failure", 401),
        AUTH_DENIALS: ("authorization_denial", 403),
        REQUEST_VOLUME: ("request", 200),
    }[rule]
    return {
        "event_id": label,
        "occurred_at": stamp.isoformat(),
        "event_type": kind,
        "status_code": code,
        "method": "GET",
        "route_template": "/items",
        "actor_token": "reader",
        "client_token": "client" if rule == REQUEST_VOLUME else None,
        **changes,
    }


def send(engine: Engine, owner: UUID, rows: list[dict[str, object]], source: str = "demo") -> int:
    with transaction(engine) as db:
        batch = EventBatch.model_validate({"source_id": source, "events": rows})
        return ingest(db, owner, batch, bytes(32))


def drain(engine: Engine, settings: RuleSet = DEFAULT_RULES) -> None:
    handler = partial(evaluate_event, settings=settings)
    while jobs := claim(engine):
        for event_id, attempt in jobs:
            assert process(engine, event_id, attempt, handler)


def findings(engine: Engine) -> list[tuple[str, int, int, int, list[str]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT f.rule_key, f.version, f.threshold, f.window_seconds,
                   array(SELECT e.external_event_id FROM unnest(f.evidence) WITH ORDINALITY ids(id, pos)
                         JOIN security_events e ON e.id=ids.id ORDER BY ids.pos)
            FROM rule_findings f JOIN security_events a ON a.id=f.event_id
            ORDER BY f.rule_key, a.occurred_at, a.external_event_id
        """)
        )
        return [
            (key, version, threshold, seconds, evidence)
            for key, version, threshold, seconds, evidence in rows
        ]


@pytest.mark.parametrize("rule", [AUTH_FAILURES, AUTH_DENIALS, REQUEST_VOLUME])
def test_rolling_threshold_edges_replay_and_ties(database: Engine, rule: Rule) -> None:
    owner = project(database)
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    first = end - timedelta(seconds=rule.seconds)
    labels = [f"obs-{i:03}" for i in range(rule.threshold)]
    rows = [sample(rule, key, first if i == 0 else end) for i, key in enumerate(labels)]
    # The first and last observations span midnight, at the inclusive lower boundary.
    assert send(database, owner, rows[1:][::-1]) == rule.threshold - 1
    drain(database)
    assert findings(database) == []
    # A late event one microsecond outside the window cannot complete the threshold.
    assert send(database, owner, [sample(rule, "outside", first - timedelta(microseconds=1))]) == 1
    drain(database)
    assert findings(database) == []
    assert send(database, owner, [rows[0]]) == 1
    drain(database)
    matches = findings(database)
    assert matches[-1] == (rule.key, rule.version, rule.threshold, rule.seconds, labels)
    assert len(matches) == 1
    assert send(database, owner, rows) == 0
    with database.begin() as conn:
        conn.execute(text("UPDATE event_jobs SET state='pending', attempts=0, available_at=now()"))
    drain(database)
    assert findings(database) == matches


@pytest.mark.parametrize("rule", [AUTH_FAILURES, AUTH_DENIALS, REQUEST_VOLUME])
def test_configured_threshold_replay_and_default_history(
    database: Engine, monkeypatch: pytest.MonkeyPatch, rule: Rule
) -> None:
    owner = project(database)
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    rows = [sample(rule, f"obs-{i:03}", stamp) for i in range(rule.threshold)]
    send(database, owner, rows)
    drain(database)
    original = findings(database)
    assert len(original) == 1 and original[0][1] == 1

    monkeypatch.setenv(f"SENTINEL_{rule.key.upper()}_THRESHOLD", "2")
    settings = RuleSet.from_environment()
    # Same deployment, second source. One input is below the custom boundary.
    send(database, owner, rows[:1], source="configured")
    drain(database, settings)
    assert findings(database) == original
    send(database, owner, rows[1:2], source="configured")
    drain(database, settings)
    # Reprocess one of the original source's jobs under the new settings.
    # Its new alert must stay separate from the original in the same UTC bucket.
    with database.begin() as conn:
        retry = text("""UPDATE event_jobs SET state='pending', attempts=0, available_at=now()
                        WHERE event_id IN (SELECT id FROM security_events WHERE external_event_id='obs-001')""")
        conn.execute(retry)
    drain(database, settings)
    matches = findings(database)
    assert original[0] in matches
    with database.connect() as conn:
        alerts = conn.execute(
            text("""SELECT id, source_id, version, threshold, window_seconds, occurrence_count
                                     FROM alert_summaries ORDER BY source_id, version""")
        ).all()
    assert [(a.source_id, a.version, a.threshold, a.window_seconds) for a in alerts] == [
        ("configured", 1002, 2, rule.seconds),
        ("demo", 1, rule.threshold, rule.seconds),
        ("demo", 1002, 2, rule.seconds),
    ]
    assert alerts[0].occurrence_count == 1
    assert (rule.key, 1002, 2, rule.seconds, ["obs-000", "obs-001"]) in matches
    with database.begin() as conn:
        conn.execute(retry)
    drain(database, settings)
    assert findings(database) == matches
    with database.connect() as conn:
        assert conn.execute(
            text("SELECT id, occurrence_count FROM alert_summaries ORDER BY source_id, version")
        ).all() == [(a.id, a.occurrence_count) for a in alerts]


def test_unrelated_observations_stay_separate(database: Engine) -> None:
    owner, foreign = project(database), project(database)
    now = datetime.now(UTC)
    template = sample(AUTH_DENIALS, "extra", now)
    rows = [{**template, "event_id": f"near-{n}"} for n in range(9)]
    send(database, owner, rows)
    send(database, owner, [template], source="other")
    send(database, foreign, [template])
    variations: list[dict[str, object]] = [
        {"actor_token": None},
        {"actor_token": "other"},
        {"method": "POST"},
        {"route_template": "/other"},
        {"event_type": "request", "status_code": 403},
    ]
    for key, changes in enumerate(variations):
        send(database, owner, [{**template, "event_id": f"split-{key}", **changes}])
    send(
        database,
        owner,
        [sample(REQUEST_VOLUME, f"unknown-{i}", now, client_token=None) for i in range(65)],
    )
    drain(database)
    assert findings(database) == []


def test_late_evidence_converges_with_concurrent_workers(database: Engine) -> None:
    rule = AUTH_FAILURES
    owner = project(database)
    start = datetime.now(UTC) - timedelta(minutes=1)
    ids = [f"e-{i}" for i in range(10)]
    rows = [sample(rule, key, start + timedelta(seconds=i)) for i, key in enumerate(ids)]
    send(database, owner, rows[:7] + rows[9:])
    drain(database)
    assert findings(database)[0][-1] == ids[:7] + ids[9:]
    send(database, owner, rows[7:9])
    jobs = claim(database)
    assert len(jobs) == 2
    barrier = Barrier(2)

    def run(job: tuple[UUID, int]) -> bool:
        barrier.wait(timeout=10)
        return process(database, *job)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(run, jobs))
    assert [row[-1] for row in findings(database)] == [ids[i : i + 8] for i in range(3)]


def test_upgrade_evaluates_existing_successes_and_preserves_dead_jobs(
    database: Engine, config: Config
) -> None:
    command.downgrade(config, "0007_event_jobs")
    owner = project(database)
    now = datetime.now(UTC)
    send(database, owner, [sample(AUTH_FAILURES, f"legacy-{i}", now) for i in range(8)])
    with database.begin() as conn:
        conn.execute(text("UPDATE event_jobs SET state='succeeded', attempts=2"))
    send(database, owner, [sample(REQUEST_VOLUME, "dead", now)])
    with database.begin() as conn:
        conn.execute(text("UPDATE event_jobs SET state='dead', attempts=5 WHERE state='pending'"))
    command.upgrade(config, "head")
    drain(database)
    assert len(findings(database)) == 1
    with database.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM event_jobs WHERE state='dead'")).scalar_one()
            == 1
        )
    command.downgrade(config, "0007_event_jobs")
    with database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM security_events")).scalar_one() == 9
