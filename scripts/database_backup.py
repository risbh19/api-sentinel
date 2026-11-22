"""Back up the local Compose database or rehearse a restore into a fresh database."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

DB = ["docker", "compose", "exec", "-T", "db"]
VERIFY = """
SELECT json_build_object(
  'events', (SELECT count(*) FROM security_events),
  'incidents', (SELECT count(*) FROM incidents),
  'audit_entries', (SELECT count(*) FROM audit_entries),
  'missing_jobs', (SELECT count(*) FROM security_events e
                   WHERE NOT EXISTS (SELECT 1 FROM event_jobs j WHERE j.event_id=e.id)),
  'missing_timeline', (SELECT count(*) FROM incidents i WHERE NOT EXISTS
                       (SELECT 1 FROM incident_activity a
                        WHERE a.incident_id=i.id AND a.version=i.version))
)
"""


def create(path: Path) -> None:
    # pg_dump emits binary data. Keep the archive out of the shell and refuse overwrites.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            subprocess.run(
                [*DB, "pg_dump", "-U", "postgres", "-Fc", "-d", "sentinel"],
                stdout=stream,
                check=True,
            )
    except BaseException:
        path.unlink()
        raise
    print("Database archive created.")


def verify(path: Path) -> None:
    scratch = "sentinel_restore_" + uuid4().hex
    psql = [*DB, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", scratch]
    with path.open("rb") as stream:
        subprocess.run([*DB, "createdb", "-U", "postgres", "-T", "template0", scratch], check=True)
        try:
            subprocess.run(
                [*psql, "-c", f"REVOKE CONNECT ON DATABASE {scratch} FROM PUBLIC"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            subprocess.run(
                [*DB, "pg_restore", "-U", "postgres", "--single-transaction", "-d", scratch],
                stdin=stream,
                check=True,
            )
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "-e",
                    f"PGDATABASE={scratch}",
                    "migrate",
                    "alembic",
                    "current",
                    "--check-heads",
                ],
                check=True,
            )
            result = subprocess.check_output([*psql, "-Atc", VERIFY], text=True)
            counts = json.loads(result)
            if counts["missing_jobs"] or counts["missing_timeline"]:
                raise RuntimeError("Restored events or incidents have incomplete history")
        finally:
            subprocess.run([*DB, "dropdb", "-U", "postgres", scratch], check=True)
    print(json.dumps(counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create", "verify"])
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        create(args.archive)
    else:
        verify(args.archive)


if __name__ == "__main__":
    main()
