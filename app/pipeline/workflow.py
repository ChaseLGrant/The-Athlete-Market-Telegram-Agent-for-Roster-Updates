"""Admin state transitions. All rules live here so the dashboard and CLI behave identically."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.content.guardrails import check_telegram, check_x
from app.logging_setup import record_event
from app.models import Opportunity, PublishingQueue, Status


class WorkflowError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def approve(session: Session, opp: Opportunity, *, override_low_confidence: bool = False) -> None:
    if opp.status not in (Status.PENDING, Status.REJECTED):
        raise WorkflowError(f"can't approve an item that is {opp.status}")
    if opp.confidence == "LOW" and not override_low_confidence:
        raise WorkflowError("LOW confidence: tick the override box if you still want to approve it")
    if opp.expires_at and _aware(opp.expires_at) < _now():
        raise WorkflowError("expired — reanalyze first")
    g = check_telegram(opp.telegram_text or "", opp.opportunity_type)
    if not g.ok:
        raise WorkflowError("Telegram copy fails guardrails: " + "; ".join(g.problems))
    opp.status = Status.APPROVED
    opp.low_confidence_override = override_low_confidence and opp.confidence == "LOW"
    opp.approved_at = _now()
    opp.status_note = None
    record_event(session, "opportunity_approved", f"#{opp.id} approved", sport=opp.sport,
                 entity_type="opportunity", entity_id=opp.id)


def reject(session: Session, opp: Opportunity, note: str | None = None) -> None:
    if opp.status == Status.PUBLISHED:
        raise WorkflowError("already published")
    opp.status = Status.REJECTED
    opp.status_note = note or None
    unschedule(session, opp)
    record_event(session, "opportunity_rejected", f"#{opp.id} rejected", sport=opp.sport,
                 entity_type="opportunity", entity_id=opp.id)


def edit_copy(session: Session, opp: Opportunity, telegram_text: str, x_teaser: str) -> list[str]:
    """Saves the edit. Returns guardrail problems (empty list = clean). Problems block approval/publish."""
    if opp.status == Status.PUBLISHED:
        raise WorkflowError("already published — edits wouldn't change the sent post")
    telegram_text = telegram_text.replace("\r\n", "\n").strip()
    x_teaser = x_teaser.replace("\r\n", "\n").strip()
    opp.telegram_text = telegram_text
    opp.x_teaser = x_teaser
    opp.telegram_text_edited = True
    problems = check_telegram(telegram_text, opp.opportunity_type).problems
    problems += ["X: " + p for p in check_x(x_teaser, opp.opportunity_type, [opp.school.name]).problems]
    if problems and opp.status in (Status.APPROVED, Status.SCHEDULED):
        opp.status = Status.PENDING
        opp.status_note = "Edited copy fails guardrails; fix before approving."
        unschedule(session, opp)
    return problems


def schedule(session: Session, opp: Opportunity, day: date) -> PublishingQueue:
    if opp.status not in (Status.APPROVED, Status.SCHEDULED):
        raise WorkflowError("approve it first")
    existing = session.scalar(select(PublishingQueue).where(PublishingQueue.sport == opp.sport,
                                                            PublishingQueue.publish_date == day))
    if existing and existing.opportunity_id != opp.id:
        raise WorkflowError(f"{day} already has a {opp.sport} post scheduled (#{existing.opportunity_id})")
    unschedule(session, opp)
    q = existing or PublishingQueue(sport=opp.sport, publish_date=day, opportunity_id=opp.id)
    q.status = "scheduled"
    session.add(q)
    opp.status = Status.SCHEDULED
    opp.scheduled_for = day
    session.flush()
    return q


def unschedule(session: Session, opp: Opportunity) -> None:
    for q in session.scalars(select(PublishingQueue).where(PublishingQueue.opportunity_id == opp.id,
                                                           PublishingQueue.status == "scheduled")):
        session.delete(q)
    if opp.status == Status.SCHEDULED:
        opp.status = Status.APPROVED
    opp.scheduled_for = None
    session.flush()


def expire_stale(session: Session, now: datetime | None = None) -> int:
    now = now or _now()
    n = 0
    for opp in session.scalars(select(Opportunity).where(
            Opportunity.status.in_((Status.PENDING, Status.APPROVED, Status.SCHEDULED)))):
        if opp.expires_at and _aware(opp.expires_at) < now:
            opp.status = Status.EXPIRED
            opp.status_note = "Expired: sources not re-verified within the TTL."
            unschedule(session, opp) if opp.scheduled_for else None
            opp.status = Status.EXPIRED
            record_event(session, "stale_detected", f"#{opp.id} expired", sport=opp.sport,
                         entity_type="opportunity", entity_id=opp.id)
            n += 1
    return n
