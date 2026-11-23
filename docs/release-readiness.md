# v0.1 local release candidate

## Candidate notes

The candidate covers the local path from a declared API contract to a recorded incident. An operator can provision an owner, import OpenAPI 3.0/3.1 inventory, issue a project key, replay a synthetic event batch, inspect correlated evidence, and assign, resolve and reopen an investigation. The retention job and restore rehearsal target one project and one fresh database respectively. The [implementation history](implementation-status.md) records the merged feature revisions.

## Acceptance evidence

The [operations baseline](https://github.com/risbh19/api-sentinel/actions/runs/45003520689) exercised the packaged stack on Ubuntu, including schema checks, 93 PostgreSQL tests, Chrome, outage recovery and restoration. For a candidate, use the results on its own commit. The existing `Project records` workflow uses one Ubuntu job with read-only repository access. It checks out the PR head, builds the images from a fresh environment, starts the stack using the README sequence and exercises the checks below. On the PR, compare the head SHA to the workflow run SHA before recording a pass. If Actions or advisory services are unavailable, record which commands actually ran locally and which remain unverified. Retain the current Actions spending controls. Review included runner usage before changing the workflow or runner class.

| Requirement | Verification and scope |
| --- | --- |
| Clean checkout, pinned dependencies and schema | `scripts/init_env.py`, Compose startup, direct and proxied health checks, `alembic current --check-heads` and `alembic check`. PostgreSQL tests exercise migration round trips. Verify the Windows gate below independently. |
| Identity, tenant policy and ingestion credentials | Integration tests for access, audit and keys. Chrome signs in as two fixture users, verifies redaction, and verifies loss of project access after membership removal. The smoke runner submits an event after revocation and requires HTTP 401. |
| Contract inventory and private, idempotent events | Parser and inventory tests cover bounded imports and rejected references. Chrome imports the two-route contract and exercises the actual demo emitter. Nine observations are accepted once and counted as duplicates on replay. |
| Durable processing and explainable alerts | Event-job and detection-rule tests cover leases, retries, fencing, rolling thresholds, late arrivals and correlation. On the disposable stack, the rules smoke queues seven inputs with the worker stopped and requires a single finding and eight distinct evidence events after restart. |
| Incident lifecycle, dashboard and audit | PostgreSQL tests cover transitions, assignment, audit and concurrency. Chrome checks evidence, assignment, a note, resolution and reopening. Mobile layout and three accessibility scans cover the selected investigation screens. |
| Retention, diagnostics and recovery | The retention tests protect pending work and other projects. The restore rehearsal checks a fresh database at migration head for missing jobs and timeline entries. The outage test exercises the surviving worker as well as a restarted worker. |
| Detection configuration | All three [static thresholds](detection-rules.md#configure-the-static-thresholds) can be set per deployment. Tests exercise startup validation, custom threshold boundaries, alert detail, retries and preservation of existing alerts. Per-project tuning and historical replay remain v0.2 work. |
| Security and documentation | Run the [security regressions and scans](security-checks.md), review the [threat model](threat-model.md), and follow the [local demo](local-demo.md) and [operations runbook](operations.md). Record findings or unavailable checks alongside the commit. |

### Recorded verification

| Platform | Tested commit | Result |
| --- | --- | --- |
| Ubuntu, after the worker lease and dashboard fixes | `f9a3ae495ee02b80482075e84228699e62f53d7e` | Fresh Compose startup, migrations, 98 PostgreSQL tests, 79 API unit tests, 21 frontend tests and 3 Node checks passed, along with Chrome, worker restart, outage recovery and restore. The merge commit `96c4126fae65bbe3063e7fae89b750b99f935773` has the same Git tree. [Ubuntu run](https://github.com/risbh19/api-sentinel/actions/runs/45061279522) |
| Windows Docker Desktop, before those two fixes | `a6a936f70011059052b9b9480d75fafa4618b913` | The owner verified fresh startup, migration head `0011_event_retention`, worker restart with eight observations producing one alert, incident reopening, tenant isolation and three accessibility scans. Windows build 10.0.26300.0 used Docker Engine 29.8.2 and Compose 5.5.1. Host Node 26.12.0 produced an engine warning. Use the documented Node 24.22.3 for a new run. [Windows evidence on PR #19](https://github.com/risbh19/api-sentinel/pull/19) |

For a formal release of the post-fix candidate, record a Windows run on the selected revision using the steps below. The Windows result above applies to the earlier revision.

## Windows clean-install gate

Use a fresh checkout, a new Compose project name and unused default ports 8000 and 8080. Choose the candidate commit recorded on the PR. The clone command in the README defaults to main. For an open PR, fetch its branch and check out the recorded candidate SHA before initializing the environment. Docker Desktop must be running Linux containers. Install Python 3.11+, the Node version from the README and Google Chrome to include browser coverage. Run from PowerShell in the checkout, stopping on any nonzero exit code:

```powershell
$ErrorActionPreference = "Stop"
function Invoke-Checked {
    param([string]$program, [string[]]$arguments)
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "$program failed with exit code $LASTEXITCODE" }
}
Invoke-Checked git @("rev-parse", "HEAD")
Invoke-Checked docker @("compose", "version")
$env:COMPOSE_PROJECT_NAME = "sentinel-check-" + [guid]::NewGuid().ToString("N")
if (-not $env:CHROME_BIN) {
    $env:CHROME_BIN = Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"
}
if (!(Test-Path -LiteralPath $env:CHROME_BIN)) { throw "Set CHROME_BIN to the installed browser" }
Invoke-Checked python @("scripts/init_env.py")
try {
    Invoke-Checked docker @("compose", "up", "--build", "--wait")
    Invoke-Checked python @("scripts/smoke.py")
    Invoke-Checked docker @("compose", "run", "--rm", "migrate", "alembic", "current", "--check-heads")
    Invoke-Checked npm.cmd @("ci", "--prefix", "apps/web", "--no-audit", "--no-fund")
    Invoke-Checked python @("scripts/smoke_access.py", "--browser", "--rules", "--restart-worker")
} finally {
    Invoke-Checked docker @("compose", "down")
}
```

Set `CHROME_BIN` to the installed browser path if it differs. Save the commit, Windows and Docker versions, each command result and any failure. Keep the generated environment and demo credentials private.

## Release decision

- A maintainer reviews the exact candidate diff, dependency and secret scans, CI outcome, and unresolved findings. Record environment, SHA and run links. An unexplained critical or high finding blocks release.
- Before tagging a formal release, verify the Windows walkthrough on the selected revision, review its Ubuntu checks, and confirm the reviewed changes are on main. Local use and demos can run directly from a checkout.
- Public ingress, multi-host failover and recovery onto replacement infrastructure fall outside this local release. The next optional work includes controlled fixture authorization tests, rule tuning, redacted exports and a consent-based GitHub integration.
