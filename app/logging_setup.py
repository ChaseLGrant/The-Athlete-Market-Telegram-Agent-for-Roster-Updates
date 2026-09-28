"""Structured logging. Every important event goes to stdout AND the event_log table,
so failures are visible in the admin dashboard."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from sqlalchemy.orm import Session

log = logging.getLogger("roster_intel")


def configure_logging(level: str = "INFO") -> None:
    if log.handlers:
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(h)
    log.setLevel(level)


def record_event(
    session: Session | None,
    event: str,
    message: str,
    *,
    level: str = "INFO",
    sport: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    **data: Any,
) -> None:
    """Log to stdout and (if a session is given) persist to event_log.

    Event names used across the app:
      source_fetch_failed, source_unavailable, parse_failed, opportunity_created,
      opportunity_updated, score_changed, duplicate_detected, stale_detected,
      revalidation_blocked, revalidation_changed, telegram_published, telegram_logged,
      telegram_failed, guardrail_blocked, llm_failed
    """
    configure_logging()
    payload = json.dumps(data, default=str)[:4000]
    getattr(log, level.lower(), log.info)(f"[{event}] {message} {payload if data else ''}")
    if session is None:
        return
    from app.models import EventLog

    session.add(
        EventLog(
            level=level,
            event=event,
            sport=sport,
            entity_type=entity_type,
            entity_id=entity_id,
            message=message[:2000],
            data=json.loads(payload) if data else {},
        )
    )
