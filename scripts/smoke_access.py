"""Verify sign-in through the local web proxy using a new disposable Compose account."""

import argparse
import json
import secrets
import subprocess
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import uuid4


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", action="store_true", help="Also verify the workspace using local Chrome"
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
            "--new-organization",
            "Synthetic smoke team",
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
    assert request(collection)[0]["id"] == project["id"]
    audit = request(f"/organizations/{org['id']}/audit?project_id={project['id']}")["entries"]
    assert len(audit) == 1 and audit[0]["actor_id"] == account["id"]
    assert audit[0]["action"] == "project.created" and audit[0]["request_id"]
    assert request("/auth/activity")["entries"][0]["action"] == "session.login"
    request("/auth/logout", method="POST", csrf=account["csrf_token"], expected=204)
    request("/auth/me", expected=401)
    if args.browser:
        subprocess.run(
            ["node", "tests/workspace-browser.mjs"],
            cwd=Path(__file__).resolve().parents[1] / "apps/web",
            input=json.dumps({"email": email, "password": password}),
            text=True,
            check=True,
        )
    print("Sign-in, project creation, listing and logout passed through the web proxy.")


if __name__ == "__main__":
    main()
