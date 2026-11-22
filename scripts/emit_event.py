"""Submit a synthetic loopback event, without exposing credentials in command arguments."""

import argparse
import getpass
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from check_emitter import RejectRedirect


def observation(event_id: str, at: datetime, *, normal: bool = False) -> dict[str, object]:
    return {
        "event_id": event_id,
        "occurred_at": at.isoformat(),
        "event_type": "request" if normal else "authentication_failure",
        "method": "GET" if normal else "POST",
        "route_template": "/api/users/{id}" if normal else "/api/login",
        "status_code": 200 if normal else 401,
        "actor_token": "synthetic-demo-user",
        "client_token": "synthetic-demo-client",
    }


def demo_batch(now: datetime) -> dict[str, object]:
    events = [observation("demo-normal", now - timedelta(seconds=8), normal=True)]
    for index in range(1, 9):
        events.append(observation(f"demo-login-{index}", now - timedelta(seconds=8 - index)))
    return {"source_id": "synthetic-login-demo", "events": events}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--demo", action="store_true", help="Submit and replay the synthetic login demo"
    )
    mode.add_argument("--event-id", default=None, help="Reuse this opaque ID to check duplicates")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("Choose a port from 1 to 65535")
    key = os.environ.get("SENTINEL_INGESTION_KEY")
    if key is None:
        if not sys.stdin.isatty():
            raise SystemExit("Provide SENTINEL_INGESTION_KEY from your emitter's secret store.")
        key = getpass.getpass("Ingestion key: ")
    if not re.fullmatch(r"asi_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}", key):
        raise SystemExit("Invalid ingestion key format")
    if args.event_id is not None and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", args.event_id
    ):
        raise SystemExit(
            "Use an opaque event ID with at most 96 letters, digits, underscores or hyphens"
        )
    now = datetime.now(timezone.utc)  # noqa: UP017 - the standalone emitter supports Python 3.10
    if args.demo:
        payload = demo_batch(now)
    else:
        event_id = args.event_id or uuid4().hex
        payload = {"source_id": "synthetic-local-demo", "events": [observation(event_id, now)]}
    request = Request(
        f"http://127.0.0.1:{args.port}/api/v1/ingest/events",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    client = build_opener(ProxyHandler({}), RejectRedirect())
    try:
        for attempt in range(2 if args.demo else 1):
            with client.open(request, timeout=10) as response:
                counts = json.load(response)
            print(
                f"Synthetic events: {counts['accepted']} accepted, {counts['duplicate']} duplicate, {counts['rejected']} rejected."
            )
            if args.demo and (
                counts["rejected"] != 0
                or counts["accepted"] + counts["duplicate"] != 9
                or (attempt == 1 and counts["duplicate"] != 9)
            ):
                raise SystemExit("The demo batch or its replay returned unexpected counts.")
    except HTTPError as exc:
        raise SystemExit(f"Event submission returned HTTP {exc.code}.") from None
    except OSError:
        raise SystemExit(
            "Could not confirm event delivery. Rerun --demo or retry with the same event ID."
        ) from None


if __name__ == "__main__":
    main()
