"""Run the locked API and web checks from either Windows or POSIX."""

from pathlib import Path
from shutil import which
from subprocess import run

ROOT = Path(__file__).resolve().parents[1]


def check(directory: str, program: str, *args: str) -> None:
    executable = which(program)
    if executable is None:
        raise SystemExit(f"Install {program} before running the checks.")
    run([executable, *args], cwd=ROOT / directory, check=True)


if __name__ == "__main__":
    api = "apps/api"
    web = "apps/web"
    check(api, "uv", "sync", "--locked")
    for args in [
        ["ruff", "format", "--check", "src", "tests", "../../scripts"],
        ["ruff", "check", "src", "tests", "../../scripts"],
        ["mypy"],
        ["pytest", "-q"],
    ]:
        check(api, "uv", "run", "--locked", *args)
    check(web, "npm", "ci", "--no-audit", "--no-fund")
    for script in ["lint", "test", "build"]:
        check(web, "npm", "run", script)
