# Run the security regression checks

Run these checks against a disposable local checkout. The browser smoke test provisions two synthetic accounts and leaves their projects, events and audit records in its Compose database. It uses the default loopback web port 8080.

## API, database and browser

From the repository root, run the locked unit, component, proxy and build checks, then the PostgreSQL integration suite. Use Python 3.11+ for the browser helper and the pinned uv and Node versions in the development instructions.

```sh
python scripts/check.py
python scripts/init_env.py
docker compose run --rm --build record-tests
docker compose up --build --wait
```

The integration runner creates and removes a temporary database for each test. Its assertions cover:

| Boundary | Evidence |
| --- | --- |
| Project isolation and replay | Two organizations submit identical event IDs and actor tokens. Each project gets its own record, pseudonyms and job. Each replay is counted as a duplicate. |
| Session and key permissions | Rotation with another session's CSRF token is rejected. The original key still works, then stops working after an authorized rotation. |
| Contract import | Parser tests disable DNS and socket connections while checking server metadata and rejecting an external schema reference. |
| Invalid event batches | A bad second observation yields a validation error, introduces no event or worker job, and leaves both IDs available for a corrected batch. |

With Chrome or Chromium installed, set `CHROME_BIN` to its executable and use the web dependencies installed by `scripts/check.py`. For example, on Linux with Google Chrome:

```sh
CHROME_BIN="$(command -v google-chrome)" python3 scripts/smoke_access.py --browser --rules
```

The browser signs into two isolated contexts on the local stack. A second organization owner first has no access to the demo project. After a viewer grant, the same user can read an incident summary, with investigation fields omitted from the response. Removing that membership takes effect on the next read. A reload also removes the project from the selector. The same run exercises key rotation and revocation, event replay, alert evidence, incident resolution and accessibility checks.

## Secret and dependency scans

With Gitleaks 8.24.3 installed, run the following locally from the repository root on a feature branch. Ensure the local `origin/main` ref matches the PR base. For a merged change, substitute its actual base and head commit IDs for the range.

```sh
gitleaks git --redact --log-opts="origin/main..HEAD"
```

This scans the committed patch history offline. The dependency audits query advisory services and require network access:

```sh
(cd apps/api && uv audit --locked)
(cd apps/web && npm audit)
```

Once dependencies and images are installed, these commands exercise the parser, frontend and existing PostgreSQL test image offline:

```sh
(cd apps/api && uv run --offline --locked pytest -q tests/test_inventory_parser.py)
(cd apps/web && npm test)
docker compose run --rm --pull never record-tests
```

The browser workflow uses a local Chrome installation and the running Compose stack. Record any unavailable advisory lookup as unverified. In the PR, record each tool and result against the tested commit. For a finding, include the rule or advisory ID, affected path or package, impact and fix or remaining risk. Keep secret values redacted. Rerun the affected scan after a fix.
