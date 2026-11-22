"""Verify sign-in through the local web proxy using a new disposable Compose account."""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import UUID, uuid4

from check_emitter import RejectRedirect, check


def check_detection(project: UUID, emitter_env: dict[str, str], request, csrf: str) -> None:
    # The emitter already submitted and replayed one observation for this fresh project.
    for _ in range(7):
        subprocess.run([sys.executable, "scripts/emit_event.py"], env=emitter_env, check=True)
    path = f"/projects/{project}/alerts"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        entries = request(path)["entries"]
        if entries:
            assert len(entries) == 1
            alert = request(path + "/" + entries[0]["id"])
            assert (
                alert["rule_key"],
                alert["version"],
                alert["threshold"],
                alert["window_seconds"],
            ) == ("authentication_failures", 1, 8, 300)
            assert alert["status"] == "open" and alert["occurrence_count"] == 1
            assert len(set(alert["evidence"])) == 8 and alert["next_evidence_cursor"] is None
            event_id = alert["evidence"][0]
            assert request(f"/projects/{project}/events/{event_id}")["id"] == event_id
            incidents = f"/projects/{project}/incidents"
            created = request(
                incidents,
                method="POST",
                csrf=csrf,
                expected=201,
                payload={"title": "Synthetic login investigation", "alert_id": alert["id"]},
            )
            incident_path = incidents + "/" + created["id"]
            updated = request(
                incident_path,
                method="PATCH",
                csrf=csrf,
                payload={"version": created["version"], "status": "acknowledged"},
            )
            request(
                incident_path + "/notes",
                method="POST",
                csrf=csrf,
                expected=201,
                payload={"version": updated["version"], "text": "Reviewed synthetic evidence"},
            )
            timeline = request(incident_path)["timeline"]
            assert [item["action"] for item in timeline] == [
                "opened",
                "alert_linked",
                "status_changed",
                "note_added",
            ]
            assert timeline[1]["new_value"] == alert["id"]
            print("Incident promotion, acknowledgement and note verified through nginx.")
            print(
                "Packaged worker and web API returned one alert with eight distinct observations."
            )
            return
        time.sleep(0.5)
    raise RuntimeError("The expected authentication finding did not appear within 30 seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Also verify the workspace using local Chrome",
    )
    parser.add_argument(
        "--rules", action="store_true", help="Check a finding from the running worker"
    )
    args = parser.parse_args()
    origin = "http://127.0.0.1:8080"
    email = f"smoke-{uuid4().hex}@example.test"
    password = secrets.token_urlsafe(32)
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "-T",
            "migrate",
            "python",
            "-m",
            "api_sentinel.identity.operator",
            "create-user",
            email,
            *(["--demo"] if args.browser else ["--new-organization", "Synthetic smoke team"]),
            "--password-stdin",
        ],
        input=password + "\n",
        text=True,
        check=True,
    )
    client = build_opener(ProxyHandler({}), RejectRedirect(), HTTPCookieProcessor(CookieJar()))

    def request(path, *, method="GET", payload=None, csrf=None, expected=200):
        headers = {"Origin": origin}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        req = Request(origin + "/api/v1" + path, data=data, headers=headers, method=method)
        try:
            response = client.open(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            if response.status != expected:
                raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status}")
            body = response.read()
            return json.loads(body) if body else None

    request("/auth/me", expected=401)
    account = request("/auth/login", method="POST", payload={"email": email, "password": password})
    org = account["organizations"][0]
    assert org["role"] == "owner"
    assert request("/auth/me")["email"] == email
    collection = f"/organizations/{org['id']}/projects"
    project = request(
        collection,
        method="POST",
        csrf=account["csrf_token"],
        expected=201,
        payload={"name": "Smoke API", "slug": "smoke"},
    )
    assert any(row["id"] == project["id"] for row in request(collection))
    audit = request(f"/organizations/{org['id']}/audit?project_id={project['id']}")["entries"]
    assert len(audit) == 1 and audit[0]["actor_id"] == account["id"]
    assert audit[0]["action"] == "project.created" and audit[0]["request_id"]
    keys = f"/projects/{project['id']}/ingestion-keys"
    made = request(
        keys,
        method="POST",
        payload={"label": "Proxy smoke"},
        csrf=account["csrf_token"],
        expected=201,
    )
    assert check(UUID(project["id"]), made["secret"]) == 204
    emitter_env = {**os.environ, "SENTINEL_INGESTION_KEY": made["secret"]}
    event_id = "synthetic-proxy-" + uuid4().hex
    command = [sys.executable, "scripts/emit_event.py", "--event-id", event_id]
    for accepted, duplicate in ((1, 0), (0, 1)):
        emitted = subprocess.run(
            command, env=emitter_env, capture_output=True, text=True, check=True
        )
        assert f"{accepted} accepted, {duplicate} duplicate, 0 rejected" in emitted.stdout
    from urllib.parse import urlencode

    now = datetime.now(UTC)
    window = urlencode({"since": (now - timedelta(hours=1)).isoformat(), "until": now.isoformat()})
    events_url = f"/projects/{project['id']}/events"
    events = request(events_url + "?" + window)["entries"]
    assert len(events) == 1 and events[0]["route_template"] == "/api/login"
    detail = request(events_url + "/" + events[0]["id"])
    assert detail["external_event_id"] == event_id and detail["actor_hash"]
    assert "actor_token" not in detail
    if args.rules:
        check_detection(UUID(project["id"]), emitter_env, request, account["csrf_token"])
    rotated = request(
        keys + "/" + made["key"]["id"] + "/rotate",
        method="POST",
        csrf=account["csrf_token"],
        expected=201,
    )
    assert check(UUID(project["id"]), made["secret"]) == 401
    assert check(UUID(project["id"]), rotated["secret"]) == 204
    request(
        keys + "/" + rotated["key"]["id"] + "/revoke",
        method="POST",
        csrf=account["csrf_token"],
        expected=204,
    )
    assert check(UUID(project["id"]), rotated["secret"]) == 401
    assert request("/auth/activity")["entries"][0]["action"] == "session.login"
    request("/auth/logout", method="POST", csrf=account["csrf_token"], expected=204)
    request("/auth/me", expected=401)
    if args.browser:
        subprocess.run(
            ["node", "tests/workspace-browser.mjs"],
            cwd=Path(__file__).resolve().parents[1] / "apps/web",
            env={**os.environ, "SMOKE_PYTHON": sys.executable},
            input=json.dumps({"email": email, "password": password}),
            text=True,
            check=True,
        )
    print(
        "Project access and emitter creation, rotation and revocation passed through the web proxy."
    )


if __name__ == "__main__":
    main()
