"""Create private local Compose credentials without replacing an existing file."""

import os
import secrets
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / ".env.example").read_text(encoding="utf-8")
    for key in ("POSTGRES_PASSWORD", "SENTINEL_PROBE_PASSWORD"):
        template = template.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(32)}\n")
    try:
        fd = os.open(root / ".env", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SystemExit("An .env already exists. Keep it with its database volume.") from None
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(template)
    print("Created .env for the local Compose stack.")


if __name__ == "__main__":
    main()
