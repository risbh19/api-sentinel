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
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if any(
                line.strip().removeprefix("export ").startswith("SENTINEL_APP_PASSWORD=")
                for line in current.splitlines()
            ):
                print("Local configuration already contains the application credential.")
                return
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\nSENTINEL_APP_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
            print("Added the application credential to the existing .env.")
            return
        template = (root / ".env.example").read_text(encoding="utf-8")
        for key in ("POSTGRES_PASSWORD", "SENTINEL_PROBE_PASSWORD", "SENTINEL_APP_PASSWORD"):
            template = template.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(32)}\n")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(template)
        print("Created .env for the local Compose stack.")
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
