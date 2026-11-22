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
| Detection configuration | Partial against the plan's configurable-threshold wording. The three v1 rules use fixed, versioned thresholds in source. Operator-editable rule settings and evaluation replay are deferred. |
| Security and documentation | Run the [security regressions and scans](security-checks.md), review the [threat model](threat-model.md), and follow the [local demo](local-demo.md) and [operations runbook](operations.md). Record findings or unavailable checks alongside the commit. |

### Recorded Ubuntu candidate run

[Ubuntu workflow run 45028097755](https://github.com/risbh19/api-sentinel/actions/runs/45028097755) passed on `8d846418393d8df2df0315eec0abe9e0cd3a37e8`. The job reported 93 PostgreSQL integration tests, 70 unit tests and 20 frontend tests passing. The browser verified incident reopening and tenant isolation, and three accessibility scans passed. After worker restart the smoke test found one alert with eight distinct observations. The restore check reported zero missing jobs and zero missing timeline entries. The final PR checks record results for subsequent revisions.

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

Set `CHROME_BIN` to the installed browser path if it differs. Save the commit, Windows and Docker versions, each command result and any failure. Keep the generated environment and demo credentials private. The original foundation received a Windows startup and outage check. The full current Windows candidate walkthrough still needs evidence.

## Release decision

- A maintainer reviews the exact candidate diff, dependency and secret scans, CI outcome, and unresolved findings. Record environment, SHA and run links. An unexplained critical or high finding blocks release.
- Keep the release-readiness PR open until the Windows candidate run succeeds and the threshold requirement is implemented or its deferral explicitly accepted by the owner. After those gates and review pass, verify the merge commit on main before making a tagging decision.
- Public ingress, multi-host failover and recovery onto replacement infrastructure fall outside this local release. The next optional work includes controlled fixture authorization tests, rule tuning, redacted exports and a consent-based GitHub integration.
