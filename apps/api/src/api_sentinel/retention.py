"""Preview or expire one bounded batch of processed telemetry for a single project."""

import argparse
import json
from uuid import UUID

from sqlalchemy import Engine, text

from api_sentinel.database import open_engine

CANDIDATES = """
    SELECT e.id FROM security_events e JOIN event_jobs j ON j.event_id=e.id
    WHERE e.project_id=:project AND j.state='succeeded'
      AND e.received_at < now() - make_interval(days => :days)
    ORDER BY e.received_at, e.id LIMIT :limit
"""


def expire_batch(engine: Engine, project: UUID, days: int, limit: int, *, apply: bool) -> int:
    if not 1 <= days <= 3650 or not 1 <= limit <= 1000:
        raise ValueError("Use 1–3650 retention days and a batch size of 1–1000")
    params = {"project": project, "days": days, "limit": limit}
    with engine.begin() as conn:
        if not conn.scalar(text("SELECT 1 FROM projects WHERE id=:project"), params):
            raise ValueError("Project does not exist")
        if apply:
            statement = (
                "WITH batch AS (" + CANDIDATES + " FOR UPDATE OF e, j SKIP LOCKED), "
                "removed AS (DELETE FROM security_events e USING batch "
                "WHERE e.id=batch.id AND e.project_id=:project RETURNING e.id) "
                "SELECT count(*) FROM removed"
            )
        else:
            statement = "SELECT count(*) FROM (" + CANDIDATES + ") AS batch"
        return int(conn.execute(text(statement), params).scalar_one())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=UUID, required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = open_engine()
    try:
        count = expire_batch(engine, args.project, args.days, args.limit, apply=args.apply)
        print(json.dumps({"mode": "apply" if args.apply else "preview", "batch_count": count}))
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
