import base64
import hashlib
import hmac
import json
import os
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException


def secret() -> bytes:
    value = os.environ.get("SENTINEL_EVENT_HMAC_KEY", "")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise HTTPException(
            503, "Configure the event pseudonymization key with scripts/init_env.py"
        )
    return bytes.fromhex(value)


def pseudonym(key: bytes, project: UUID, domain: str, value: str | None) -> str | None:
    if value is None:
        return None
    return hmac.new(key, f"event:{project}:{domain}:{value}".encode(), hashlib.sha256).hexdigest()


def key_version(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret(), b"event-cursor:" + raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + signature).decode().rstrip("=")


def decode_cursor(value: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        body, signature = raw[:-32], raw[-32:]
        expected = hmac.new(secret(), b"event-cursor:" + body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        result: object = json.loads(body)
        if not isinstance(result, dict):
            raise TypeError()
        return result
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(400, "Invalid event cursor") from None
