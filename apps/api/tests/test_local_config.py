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
