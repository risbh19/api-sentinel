"""Bounded wire contract. Raw identifiers are never part of persisted event models."""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

MAX_BATCH_BYTES = 128 * 1024
MAX_EVENTS = 100
MAX_SOURCES = 32
MAX_BATCHES_PER_MINUTE = 60
MAX_AGE = timedelta(days=30)
METHODS = "'GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD','TRACE'"
TYPES = "'request','authentication_failure','authorization_denial'"
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"]
EventType = Literal["request", "authentication_failure", "authorization_denial"]
Source = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
EventID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")]
OpaqueToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Route = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    event_id: EventID
    occurred_at: AwareDatetime
    event_type: EventType
    method: Method
    route_template: Route
    status_code: int = Field(strict=True, ge=100, le=599)
    actor_token: OpaqueToken | None = None
    client_token: OpaqueToken | None = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def timestamp_string(cls, value: object) -> object:
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        ):
            raise ValueError("Use an RFC 3339 timestamp with a timezone")
        return value

    @field_validator("occurred_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("route_template")
    @classmethod
    def route(cls, value: str) -> str:
        # Literal route names or named placeholders, never URLs or query strings.
        segment = r"(?:[A-Za-z_][A-Za-z0-9_-]*|\{[A-Za-z][A-Za-z0-9_]*\})"
        if value != "/" and not re.fullmatch(r"/" + segment + r"(?:/" + segment + r")*/?", value):
            raise ValueError("Use a route template with named parameters")
        return value


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source_id: Source
    events: list[EventInput] = Field(min_length=1, max_length=MAX_EVENTS)

    def check_times(self, now: datetime) -> None:
        if any(
            not now - MAX_AGE <= e.occurred_at <= now + timedelta(minutes=5) for e in self.events
        ):
            raise ValueError("Events must be within the last 30 days and at most 5 minutes ahead")
        if any(
            (e.event_type == "authentication_failure" and e.status_code != 401)
            or (e.event_type == "authorization_denial" and e.status_code != 403)
            for e in self.events
        ):
            raise ValueError("Failure events require their corresponding 401 or 403 status")
