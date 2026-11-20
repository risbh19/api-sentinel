"""Generate missing local Compose credentials, preserving existing secrets and settings."""

import os
import secrets
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    lock = root / ".env.init-lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SystemExit(
            "Another initialization holds .env.init-lock. Check before retrying."
        ) from None
    os.close(fd)
    try:
        generated = {
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "SENTINEL_PROBE_PASSWORD": secrets.token_urlsafe(32),
            "SENTINEL_APP_PASSWORD": secrets.token_urlsafe(32),
            "SENTINEL_EVENT_HMAC_KEY": secrets.token_hex(32),
        }
        if path.exists():
            current = path.read_text(encoding="utf-8")
            present = {
                line.strip().removeprefix("export ").split("=", 1)[0]
                for line in current.splitlines()
            }
            missing = [key for key in generated if key not in present]
            if missing:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write("\n" + "".join(f"{key}={generated[key]}\n" for key in missing))
            print("Local configuration checked; existing secrets preserved.")
            return
        template = (root / ".env.example").read_text(encoding="utf-8")
        for key, value in generated.items():
            template = template.replace(f"{key}=\n", f"{key}={value}\n")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(template)
        print("Created .env for the local Compose stack.")
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
