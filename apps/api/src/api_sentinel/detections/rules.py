"""Evaluate rolling event-time windows and retain the observations that crossed each threshold."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, Connection, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert

from api_sentinel.ingestion.models import SecurityEvent

from .models import RuleFinding


@dataclass(frozen=True)
class Rule:
    key: str
    threshold: int
    seconds: int
    version: int = 1


AUTH_FAILURES = Rule("authentication_failures", 8, 300)
AUTH_DENIALS = Rule("authorization_denials", 10, 600)
REQUEST_VOLUME = Rule("high_request_volume", 61, 60)


def record_windows(
    conn: Connection,
    rule: Rule,
    group: list[ColumnElement[bool]],
    occurred: datetime,
    external_id: str,
) -> None:
    event = SecurityEvent
    order = (event.occurred_at, event.external_event_id)
    position = tuple_(*order)
    anchor = tuple_(occurred, external_id)
    span = timedelta(seconds=rule.seconds)
    samples = select(event.id, event.occurred_at).where(*group)

    # A late arrival can change only its own evidence and that of its next threshold-1 peers.
    earlier = conn.execute(
        samples.where(position < anchor, event.occurred_at >= occurred - span)
        .order_by(*(column.desc() for column in order))
        .limit(rule.threshold - 1)
    ).all()
    later = conn.execute(
        samples.where(position >= anchor, event.occurred_at <= occurred + span)
        .order_by(*order)
        .limit(rule.threshold)
    ).all()
    ordered = [*reversed(earlier), *later]
    findings = []
    for index in range(rule.threshold - 1, len(ordered)):
        first = index + 1 - rule.threshold
        if ordered[index].occurred_at - ordered[first].occurred_at <= span:
            findings.append(
                {
                    "event_id": ordered[index].id,
                    "rule_key": rule.key,
                    "version": rule.version,
                    "threshold": rule.threshold,
                    "window_seconds": rule.seconds,
                    "evidence": [row.id for row in ordered[first : index + 1]],
                }
            )
    if findings:
        statement = insert(RuleFinding).values(findings)
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[RuleFinding.event_id, RuleFinding.rule_key, RuleFinding.version],
                set_={"evidence": statement.excluded.evidence},
                where=RuleFinding.evidence.is_distinct_from(statement.excluded.evidence),
            )
        )


def evaluate_event(conn: Connection, event_id: UUID) -> int:
    event = SecurityEvent
    row = conn.execute(
        select(
            event.project_id,
            event.source_id,
            event.external_event_id,
            event.occurred_at,
            event.received_at,
            event.actor_hash,
            event.client_hash,
            event.event_type,
            event.method,
            event.route_template,
        ).where(event.id == event_id)
    ).one()
    scope = [event.project_id == row.project_id, event.source_id == row.source_id]
    rules: list[tuple[Rule, list[ColumnElement[bool]]]] = []
    if row.actor_hash and row.event_type in ("authentication_failure", "authorization_denial"):
        actor = [*scope, event.actor_hash == row.actor_hash, event.event_type == row.event_type]
        if row.event_type == "authentication_failure":
            rules.append((AUTH_FAILURES, actor))
        else:
            rules.append(
                (
                    AUTH_DENIALS,
                    [
                        *actor,
                        event.method == row.method,
                        event.route_template == row.route_template,
                    ],
                )
            )
    if row.client_hash:
        rules.append((REQUEST_VOLUME, [*scope, event.client_hash == row.client_hash]))
    if rules:
        # Serialize overlapping recomputations. Under READ COMMITTED the following queries
        # see deliveries committed while this worker was waiting for the earlier evaluator.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 914))"),
            {"scope": f"{row.project_id}/{row.source_id}"},
        )
    for rule, group in rules:
        record_windows(conn, rule, group, row.occurred_at, row.external_event_id)
    return int((row.received_at - row.occurred_at) // timedelta(milliseconds=1))
