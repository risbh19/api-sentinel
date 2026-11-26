import os
import subprocess
import sys
from pathlib import Path


def test_existing_secrets_and_pseudonym_key_survive_reinitialization(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "init_env.py"
    script.write_bytes((root / "scripts/init_env.py").read_bytes())
    (tmp_path / ".env.example").write_bytes((root / ".env.example").read_bytes())
    env = tmp_path / ".env"
    env.write_text(
        "POSTGRES_PASSWORD=preserved-admin\nSENTINEL_PROBE_PASSWORD=preserved-probe\nSENTINEL_APP_PASSWORD=preserved-app\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=True
    )
    first = env.read_text(encoding="utf-8")
    assert "preserved-admin" in first and "preserved-app" in first
    key = first.split("SENTINEL_EVENT_HMAC_KEY=", 1)[1].splitlines()[0]
    assert len(bytes.fromhex(key)) == 32
    assert key not in result.stdout
    subprocess.run([sys.executable, str(script)], capture_output=True, check=True)
    assert env.read_text(encoding="utf-8") == first


def test_spaced_assignments_survive_a_configuration_upgrade(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "init_env.py"
    script.write_bytes((Path(__file__).resolve().parents[3] / "scripts/init_env.py").read_bytes())
    env = tmp_path / ".env"
    existing = (
        "SENTINEL_EVENT_HMAC_KEY = previous-key\n"
        "export  POSTGRES_PASSWORD = previous-db\n"
        "SENTINEL_APP_PASSWORD: previous-app\n"
    )
    env.write_text(existing, encoding="utf-8")
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    updated = env.read_text(encoding="utf-8")
    assert updated.startswith(existing)
    assert updated.count("SENTINEL_EVENT_HMAC_KEY") == 1
    assert updated.count("POSTGRES_PASSWORD") == 1
    assert updated.count("SENTINEL_APP_PASSWORD") == 1
    assert "SENTINEL_WORKER_PASSWORD=" in updated
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    assert env.read_text(encoding="utf-8") == updated


def test_emitter_rejects_unsafe_credential_without_echoing_it() -> None:
    root = Path(__file__).resolve().parents[3]
    marker = "synthetic-credential-marker\nunsafe-header"
    result = subprocess.run(
        [sys.executable, str(root / "scripts/emit_event.py")],
        env={**os.environ, "SENTINEL_INGESTION_KEY": marker},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Invalid ingestion key format" in result.stderr
    assert "synthetic-credential-marker" not in result.stderr + result.stdout


def test_demo_cli_replays_identical_observations_without_printing_the_key() -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    from api_sentinel.ingestion.events import EventBatch

    root = Path(__file__).resolve().parents[3]
    credential = "asi_" + "0" * 16 + "." + "x" * 43
    batches: list[bytes] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/api/v1/ingest/events" or self.headers["Authorization"] != (
                "Bearer " + credential
            ):
                self.send_error(403)
                return
            batches.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            if len(batches) == 1:
                self.wfile.write(b'{"accepted":9,"duplicate":0,"rejected":0}')
            else:
                self.wfile.write(b'{"accepted":0,"duplicate":9,"rejected":0}')

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Receiver) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/emit_event.py"),
                    "--demo",
                    "--port",
                    str(server.server_port),
                ],
                env={**os.environ, "SENTINEL_INGESTION_KEY": credential},
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        finally:
            server.shutdown()
            worker.join()
    assert len(batches) == 2 and batches[0] == batches[1]
    batch = EventBatch.model_validate_json(batches[0])
    assert batch.source_id == "synthetic-login-demo"
    assert len({e.event_id for e in batch.events}) == 9
    normal, *failures = batch.events
    assert (normal.event_type, normal.route_template, normal.status_code) == (
        "request",
        "/api/users/{id}",
        200,
    )
    assert {(e.event_type, e.route_template, e.status_code, e.actor_token) for e in failures} == {
        ("authentication_failure", "/api/login", 401, "synthetic-demo-user")
    }
    assert credential not in result.stdout + result.stderr
