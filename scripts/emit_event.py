"""Submit a synthetic loopback event, without exposing credentials in command arguments."""

import argparse
import getpass
import json
import os
import re
import sys
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from check_emitter import RejectRedirect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--event-id", default=None, help="Reuse this opaque ID to check duplicates"
    )
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
    event_id = args.event_id or uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", event_id):
        raise SystemExit(
            "Use an opaque event ID with at most 96 letters, digits, underscores or hyphens"
        )
    payload = {
        "source_id": "synthetic-local-demo",
        "events": [
            {
                "event_id": event_id,
                "occurred_at": datetime.now(UTC).isoformat(),
                "event_type": "authentication_failure",
                "method": "POST",
                "route_template": "/api/login",
                "status_code": 401,
                "actor_token": "synthetic-demo-user",
                "client_token": "synthetic-demo-client",
            }
        ],
    }
    request = Request(
        f"http://127.0.0.1:{args.port}/api/v1/ingest/events",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    client = build_opener(ProxyHandler({}), RejectRedirect())
    try:
        with client.open(request, timeout=10) as response:
            counts = json.load(response)
            print(
                f"Synthetic events: {counts['accepted']} accepted, {counts['duplicate']} duplicate, {counts['rejected']} rejected."
            )
    except HTTPError as exc:
        raise SystemExit(
            f"Event submission rejected (HTTP {exc.code}); no batch was accepted."
        ) from None
    except OSError:
        raise SystemExit(
            "Could not confirm event delivery. Retry with the same event ID."
        ) from None


if __name__ == "__main__":
    main()
