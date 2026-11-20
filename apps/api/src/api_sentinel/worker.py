"""Process durable event jobs and report aggregate queue health."""

import argparse
import json
import signal
from collections.abc import Callable
from datetime import timedelta
from threading import Event
from uuid import UUID

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError

from api_sentinel.database import open_engine
from api_sentinel.detections.rules import evaluate_event

BATCH_SIZE = 16
LEASE = timedelta(seconds=30)
MAX_ATTEMPTS = 5


def claim(engine: Engine) -> list[tuple[UUID, int]]:
    # available_at is the retry time while pending and the lease deadline while running.
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
            WITH due AS (
                SELECT event_id FROM event_jobs
                WHERE state IN ('pending','running') AND available_at <= now()
                ORDER BY available_at, event_id LIMIT :limit FOR UPDATE SKIP LOCKED
            )
            UPDATE event_jobs AS j
            SET state = CASE WHEN attempts >= :maximum THEN 'dead' ELSE 'running' END,
                attempts = least(attempts + 1, :maximum), available_at = now() + :lease,
                last_error_code = CASE WHEN j.state = 'running' THEN 'lease_expired' ELSE last_error_code END
            FROM due WHERE j.event_id = due.event_id
            RETURNING j.event_id, j.attempts, j.state
        """),
            {"limit": BATCH_SIZE, "maximum": MAX_ATTEMPTS, "lease": LEASE},
        )
        return [(event_id, attempt) for event_id, attempt, state in rows if state == "running"]


def process(
    engine: Engine,
    event_id: UUID,
    attempt: int,
    handler: Callable[[Connection, UUID], int] = evaluate_event,
) -> bool:
    with engine.begin() as conn:
        # The generation and row lock fence a stale owner, including during result persistence.
        owned = conn.execute(
            text("""
            SELECT event_id FROM event_jobs WHERE event_id = :id AND attempts = :attempt
              AND state = 'running' AND available_at > clock_timestamp() FOR UPDATE
        """),
            {"id": event_id, "attempt": attempt},
        ).first()
        if owned is None:
            return False
        try:
            with conn.begin_nested():
                delay = handler(conn, event_id)
        except OperationalError:
            raise
        except Exception:  # noqa: BLE001 - isolate a failed job and spend its finite retry budget
            # The savepoint rolls back handler writes. Persist only the fixed error code.
            conn.execute(
                text("""
                UPDATE event_jobs SET state = :state, last_error_code = 'processing_failed',
                    available_at = clock_timestamp() + :backoff WHERE event_id = :id
            """),
                {
                    "state": "dead" if attempt >= MAX_ATTEMPTS else "pending",
                    "backoff": timedelta(seconds=2 ** (attempt - 1)),
                    "id": event_id,
                },
            )
            return False
        conn.execute(
            text("""
            UPDATE event_jobs SET state = 'succeeded', delivery_delay_ms = :delay,
                last_error_code = NULL WHERE event_id = :id
        """),
            {"delay": delay, "id": event_id},
        )
        return True


def status(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("""
            SELECT count(*) FILTER (WHERE state='pending') AS pending,
                   count(*) FILTER (WHERE state='running') AS running,
                   count(*) FILTER (WHERE state='succeeded') AS succeeded,
                   count(*) FILTER (WHERE state='dead') AS dead,
                   coalesce(extract(epoch FROM now() - min(queued_at)
                       FILTER (WHERE state IN ('pending','running')))::bigint, 0) AS oldest_open_seconds
            FROM event_jobs
        """)
            )
            .mappings()
            .one()
        )
        return {str(key): int(value) for key, value in row.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--status", action="store_true", help="Print aggregate queue counts and lag"
    )
    args = parser.parse_args()
    stopped = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    engine = open_engine()
    try:
        if args.status:
            print(json.dumps(status(engine)))
            return
        print('{"service":"worker","state":"started"}', flush=True)
        while not stopped.is_set():
            try:
                jobs = claim(engine)
                for event_id, attempt in jobs:
                    if stopped.is_set():
                        break
                    process(engine, event_id, attempt)
                if not jobs:
                    stopped.wait(1)
            except OperationalError:
                print('{"service":"worker","state":"database_unavailable"}', flush=True)
                stopped.wait(3)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
