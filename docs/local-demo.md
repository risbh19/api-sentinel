# Investigate a synthetic login alert

This walkthrough uses a local Docker Compose project, a password you choose, and nine synthetic observations. The dashboard reads persisted records. The sample describes an API contract and sends telemetry only to API Sentinel's loopback ingestion endpoint. The login failures are fixture data and establish no compromise.

## Start a fresh demo

Use Docker Compose v2.20+ and Python 3.10+ from the repository root. The Compose project name below gives the demo its own database volume. On a fresh clone the two published loopback ports are 8080 and 8000. If those ports are busy, choose unused `WEB_PORT` and `API_PORT` values in the generated `.env` before startup and use the chosen web port throughout.

```sh
python scripts/init_env.py
docker compose -p api-sentinel-demo up --build --wait
docker compose -p api-sentinel-demo run --rm migrate python -m api_sentinel.identity.operator create-user demo-owner@example.test --demo
```

Enter a new password of 12–256 characters at the hidden prompt. The explicit `--demo` option creates the owner, **Synthetic demo team** and **Synthetic login demo** project together. Normal startup creates no demo account. On a later visit, sign in with the same account. Provisioning the same email again leaves the original account intact.

## Import the contract and emit the observations

1. Open [the project workspace](http://127.0.0.1:8080/#workspace), sign in, and select **Synthetic login demo**.
2. In **Inventory**, upload [login-demo.yaml](../examples/login-demo.yaml) and choose **Import file**. Revision 1 declares a public `POST /api/login` and a bearer-protected `GET /api/users/{id}`. You can edit a local copy and import a new revision. The emitter uses these two original route templates.
3. In **Integrations**, enter `Synthetic demo emitter` and choose **Create key**. Run the command below in a local terminal. Paste the one-time key at its hidden prompt, then choose **Hide key** in the workspace.

```sh
python scripts/emit_event.py --demo
```

For a different web port, append `--port PORT`. The command submits the batch and then replays the same bytes. Expected output for a fresh project is:

```text
Synthetic events: 9 accepted, 0 duplicate, 0 rejected.
Synthetic events: 0 accepted, 9 duplicate, 0 rejected.
```

Rerunning the command in the same project uses the same nine event IDs. Both submissions then report nine duplicates while those events are retained. After a connection interruption, repeat the command with the same project key.

## Investigate in the workspace

1. In **Events**, filter **Event source** to `synthetic-login-demo`. Look for one successful user read and eight HTTP 401 login observations within eight seconds. Open an event to inspect its pseudonyms.
2. In **Alerts**, refresh until the worker produces the authentication failures alert. Open it to see rule version 1, its threshold of eight failures for the same actor in 300 seconds, and eight supporting events. The successful read is outside the evidence set.
3. Choose **Create incident from alert**, enter `Synthetic login investigation`, and save. Choose **Assign to me**, acknowledge it, add a synthetic note, move it to investigating, then resolve it. Check the incident timeline. You can reopen the same incident to continue investigating.
4. Refresh **Overview**. For a fresh demo within the 24-hour window, expect nine events. Resolution removes the incident from the active total. Open **View audit activity** for the organization's history.
5. In **Integrations**, revoke the demo key. Repeating the emitter command with the revoked key returns HTTP 401. You can create another key in the same project to verify the replay counts again.

If the events appear before the alert, check the worker with `docker compose -p api-sentinel-demo exec -T worker python -m api_sentinel.worker --status`. To stop and keep the demo, run `docker compose -p api-sentinel-demo down`. Keep the generated `.env` with its database volume. To run the walkthrough in a fresh project on the same stack, provision another local email with `--demo`.
