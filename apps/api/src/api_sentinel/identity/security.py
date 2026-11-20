import hashlib
import os
import re
from enum import StrEnum
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.low_level import Type
from sqlalchemy import Engine, case, func
from sqlalchemy.dialects.postgresql import insert

from api_sentinel.database import transaction

from .models import LoginWindow

HASHER = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=1, type=Type.ID)
DUMMY_HASH = HASHER.hash(os.urandom(32))
COOKIE = "sentinel_session"
COOKIE_PATH = "/api/v1"
SESSION_SECONDS = 8 * 60 * 60


class Role(StrEnum):
    OWNER = "owner"
    ANALYST = "analyst"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Permission(StrEnum):
    READ = "read"
    IMPORT = "import_inventory"
    READ_INVENTORY = "read_inventory"
    READ_KEYS = "read_keys"
    READ_EVENTS = "read_events"
    READ_EVENT_DETAILS = "read_event_details"
    MANAGE_KEYS = "manage_keys"
    READ_AUDIT = "read_audit"
    EDIT_PROJECT = "edit_project"
    DELETE_PROJECT = "delete_project"
    MANAGE_MEMBERS = "manage_members"


GRANTS = {
    Role.OWNER: frozenset(Permission),
    Role.DEVELOPER: frozenset(
        {
            Permission.READ,
            Permission.MANAGE_KEYS,
            Permission.READ_KEYS,
            Permission.READ_EVENTS,
            Permission.READ_EVENT_DETAILS,
            Permission.EDIT_PROJECT,
            Permission.READ_INVENTORY,
            Permission.IMPORT,
        }
    ),
    Role.ANALYST: frozenset(
        {
            Permission.READ,
            Permission.READ_KEYS,
            Permission.READ_EVENTS,
            Permission.READ_EVENT_DETAILS,
            Permission.READ_AUDIT,
            Permission.READ_INVENTORY,
            Permission.IMPORT,
        }
    ),
    Role.VIEWER: frozenset({Permission.READ, Permission.READ_INVENTORY, Permission.READ_EVENTS}),
}


def normalized_email(value: str) -> str:
    email = value.strip().lower()
    if (
        not email.isascii()
        or not email.isprintable()
        or len(email) > 254
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
    ):
        raise ValueError("Enter a valid email address")
    return email


def web_origin() -> str:
    value = os.environ.get("SENTINEL_WEB_ORIGIN", "http://127.0.0.1:8080")
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})
        )
    ):
        raise ValueError("Configure an HTTPS web origin or an HTTP loopback origin")
    return value


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return digest("csrf:" + token)


def allow_login(engine: Engine, email: str) -> bool:
    slot = 1 + int(digest(email)[:4], 16) % 1024
    with transaction(engine) as db:
        window = func.floor(func.extract("epoch", func.now()) / 60)
        for key, limit in ((0, 100), (slot, 8)):
            statement = insert(LoginWindow).values(slot=key, window=window, attempts=1)
            count = db.scalar(
                statement.on_conflict_do_update(
                    index_elements=[LoginWindow.slot],
                    set_={
                        "window": window,
                        "attempts": case(
                            (LoginWindow.window == window, LoginWindow.attempts + 1), else_=1
                        ),
                    },
                ).returning(LoginWindow.attempts)
            )
            if count is None or count > limit:
                return False
    return True


def display_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 120 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Use 1 to 120 characters without control characters")
    return name
