"""Assert the public health contracts of a running local API and web server."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

local = build_opener(ProxyHandler({}))


def get(port: int, path: str) -> tuple[int, bytes]:
    try:
        response = local.open(f"http://127.0.0.1:{port}{path}", timeout=7)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read()


def check_health(port: int, path: str, code: int, status: str) -> None:
    actual, body = get(port, path)
    if actual != code or json.loads(body) != {"status": status}:
        raise SystemExit(f"Unexpected response from {path} on port {port} (HTTP {actual})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--db-down", action="store_true")
    args = parser.parse_args()
    check_health(args.api_port, "/health/live", 200, "ok")
    code, status = (503, "unavailable") if args.db_down else (200, "ready")
    for port in (args.api_port, args.web_port):
        check_health(port, "/health/ready", code, status)
    http_status, html = get(args.web_port, "/")
    if http_status != 200 or b"<title>Service status" not in html:
        raise SystemExit("Web server did not return the status page")
    print(f"API liveness, direct and proxied readiness ({code}), and web page passed.")
