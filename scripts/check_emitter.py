"""Check an ingestion credential against the local API Sentinel web proxy."""

import argparse
import getpass
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(project_id: UUID, key: str, port: int = 8080) -> int:
    if not 1 <= port <= 65535:
        raise ValueError("Invalid local web port")
    if not re.fullmatch(r"asi_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}", key):
        raise ValueError("Invalid ingestion key format")
    opener = build_opener(ProxyHandler({}), RejectRedirect())
    url = f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/ingestion-keys/check"
    request = Request(url, method="POST", headers={"Authorization": "Bearer " + key})
    try:
        with opener.open(request, timeout=10) as response:
            return response.status
    except HTTPError as error:
        with error:
            return error.code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=UUID)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    credential = os.environ.get("SENTINEL_INGESTION_KEY")
    if credential is None:
        if not sys.stdin.isatty():
            raise SystemExit("Provide SENTINEL_INGESTION_KEY from your emitter's secret store.")
        credential = getpass.getpass("Ingestion key: ")
    try:
        status = check(args.project, credential, args.port)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except (URLError, OSError):
        raise SystemExit("Local API Sentinel connection failed.") from None
    if status != 204:
        raise SystemExit(f"Credential check returned HTTP {status}.")
    print("Emitter credential accepted for this project.")
