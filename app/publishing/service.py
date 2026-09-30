"""Publishing: one post per sport per day, idempotent, fail-safe.

Modes:
  live     TEST_MODE=false and DRY_RUN=false → sends to the real channel
  test     TEST_MODE=true  → logs the post, marks it published (mode=test) so you can preview the whole flow
  dry_run  DRY_RUN=true    → logs the post, does NOT mark it published
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.content.guardrails import check_telegram, check_x, school_names
from app.logging_setup import record_event
from app.models import Opportunity, OppType, PublishedPost, PublishingQueue, Status
from app.pipeline.revalidate import revalidate
from app.publishing.queue import rank_candidates
from app.publishing.telegram import TelegramClient, TelegramError
from app.settings import get_settings
from app.sports.registry import get_sport


@dataclass
class PublishOutcome:
    ok: bool
    status: str  # published | logged | skipped | blocked | failed
    message: str
    opportunity_id: int | None = None
    telegram_message_id: int | None = None


def current_mode() -> str:
    s = get_settings()
    if s.test_mode:
        return "test"
    if s.dry_run:
        return "dry_run"
    return "live"


def local_today(now: datetime | None = None) -> date:
    s = get_settings()
    return (now or datetime.now(timezone.utc)).astimezone(s.tz).date()


# Post statuses that use up the sport's daily slot. "sending"/"unknown" count too: if Telegram
# may have received a post, sending a *different* one the same day could mean two posts.
SLOT_USED_STATUSES = ("sent", "logged", "sending", "unknown")


def _already_sent_today(session: Session, sport: str, day: date, mode: str) -> bool:
    s = get_settings()
    for p in session.scalars(select(PublishedPost).where(PublishedPost.sport == sport, PublishedPost.mode == mode,
                                                         PublishedPost.status.in_(SLOT_USED_STATUSES))):
        sent = p.sent_at if p.sent_at.tzinfo else p.sent_at.replace(tzinfo=timezone.utc)
        if sent.astimezone(s.tz).date() == day:
            return True
    return False


def publish_opportunity(session: Session, opp: Opportunity, *, client: TelegramClient | None = None,
                        now: datetime | None = None, queue_row: PublishingQueue | None = None) -> PublishOutcome:
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    mode = current_mode()
    channel_ref = s.channel_env_var(opp.sport)

    if opp.status not in (Status.APPROVED, Status.SCHEDULED):
        return PublishOutcome(False, "blocked", f"#{opp.id} is {opp.status}; only approved items publish", opp.id)

    prior = session.scalar(select(PublishedPost).where(PublishedPost.opportunity_id == opp.id,
                                                       PublishedPost.channel_ref == channel_ref,
                                                       PublishedPost.mode == mode))
    if prior is not None:
        return PublishOutcome(False, "skipped", f"#{opp.id} was already posted ({mode})", opp.id)

    # one post per sport per day, even when an admin clicks "Publish now"
    day = local_today(now)
    if _already_sent_today(session, opp.sport, day, mode):
        return PublishOutcome(False, "blocked", f"{opp.sport} already has a post on {day} (max 1 per day). "
                                                "Schedule this one for another day.", opp.id)

    # sports the owner switched off (ENABLED_SPORTS) never post live
    if mode == "live" and not get_settings().sport_enabled(opp.sport):
        msg = f"{opp.sport} is switched off (add it to the ENABLED_SPORTS repository variable to turn it on)"
        record_event(session, "publish_blocked", f"#{opp.id}: {msg}", level="WARNING", sport=opp.sport,
                     entity_type="opportunity", entity_id=opp.id)
        return PublishOutcome(False, "blocked", msg, opp.id)

    # sports whose page reading isn't verified on live sites never post live
    if mode == "live" and opp.opportunity_type == OppType.ROSTER and not get_sport(opp.sport).live_verified:
        msg = (f"{opp.sport} page reading hasn't been verified on live pages yet, so it can't post live. "
               f"Run: python -m app.cli verify --sport {opp.sport}")
        if queue_row:
            queue_row.status, queue_row.note = "blocked", msg
        record_event(session, "publish_blocked", f"#{opp.id}: {msg}", level="WARNING", sport=opp.sport,
                     entity_type="opportunity", entity_id=opp.id)
        return PublishOutcome(False, "blocked", msg, opp.id)

    # 1) revalidate stale evidence (never knowingly publish stale analysis)
    rv = revalidate(session, opp, now=now)
    if rv.outcome in ("blocked", "changed"):
        if queue_row:
            queue_row.status = "blocked"
            queue_row.note = rv.message
        record_event(session, "publish_blocked", f"#{opp.id}: {rv.message}", level="WARNING", sport=opp.sport,
                     entity_type="opportunity", entity_id=opp.id)
        return PublishOutcome(False, "blocked", rv.message, opp.id)

    # refresh unedited roster copy from the stored numbers, so wording fixes reach items already in the queue
    if opp.opportunity_type == OppType.ROSTER and not opp.telegram_text_edited and opp.metrics:
        from app.pipeline.opportunities import render_content

        opp.telegram_text, opp.x_teaser = render_content(opp, list(opp.sources), opp.school.name,
                                                         opp.school.division)

    # 2) guardrails on the exact text we will send
    g = check_telegram(opp.telegram_text or "", opp.opportunity_type)
    gx = check_x(opp.x_teaser or "", opp.opportunity_type, school_names(opp.school))
    if not g.ok or not gx.ok:
        msg = "; ".join(g.problems + ["X: " + p for p in gx.problems])
        if queue_row:
            queue_row.status, queue_row.note = "blocked", msg
        record_event(session, "guardrail_blocked", f"#{opp.id}: {msg}", level="ERROR", sport=opp.sport,
                     entity_type="opportunity", entity_id=opp.id)
        return PublishOutcome(False, "blocked", "Guardrails: " + msg, opp.id)

    # 3) send or log
    msg_id = None
    if mode == "live":
        chat_id = s.channel_id_for(opp.sport)
        if not chat_id:
            msg = f"{channel_ref} is not set in .env — can't publish {opp.sport}"
            if queue_row:
                queue_row.status, queue_row.note = "blocked", msg
            record_event(session, "telegram_failed", msg, level="ERROR", sport=opp.sport,
                         entity_type="opportunity", entity_id=opp.id)
            return PublishOutcome(False, "blocked", msg, opp.id)
        # claim first so a crash/retry can't double-send
        post = PublishedPost(opportunity_id=opp.id, sport=opp.sport, channel_ref=channel_ref, mode=mode,
                             text=opp.telegram_text, x_teaser=opp.x_teaser, status="sending", sent_at=now)
        session.add(post)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return PublishOutcome(False, "skipped", f"#{opp.id} is already being/been posted", opp.id)
        session.commit()  # claim is durable before the network call
        try:
            msg_id = (client or TelegramClient()).send_message(chat_id, opp.telegram_text or "")
        except TelegramError as e:
            if e.ambiguous:
                # We can't know whether Telegram received it. Keep the claim so it is never
                # re-sent automatically; an admin checks the channel.
                post.status, post.error = "unknown", str(e)
                if queue_row:
                    queue_row.status, queue_row.note = "failed", f"{e} — check the channel before retrying"
                record_event(session, "telegram_failed", f"#{opp.id}: {e} (delivery unknown)", level="ERROR",
                             sport=opp.sport, entity_type="opportunity", entity_id=opp.id)
                session.commit()
                return PublishOutcome(False, "failed", f"{e} — delivery unknown; check the channel", opp.id)
            session.delete(post)
            if queue_row:
                queue_row.status, queue_row.note = "failed", str(e)
            record_event(session, "telegram_failed", f"#{opp.id}: {e}", level="ERROR", sport=opp.sport,
                         entity_type="opportunity", entity_id=opp.id)
            session.commit()
            return PublishOutcome(False, "failed", str(e), opp.id)
        post.telegram_message_id = msg_id
        post.status = "sent"
        record_event(session, "telegram_published", f"#{opp.id} sent (message {msg_id})", sport=opp.sport,
                     entity_type="opportunity", entity_id=opp.id)
    else:
        session.add(PublishedPost(opportunity_id=opp.id, sport=opp.sport, channel_ref=channel_ref, mode=mode,
                                  text=opp.telegram_text or "", x_teaser=opp.x_teaser, status="logged", sent_at=now))
        record_event(session, "telegram_logged", f"[{mode.upper()}] would post #{opp.id} to {channel_ref}",
                     sport=opp.sport, entity_type="opportunity", entity_id=opp.id, text=opp.telegram_text)

    if mode in ("live", "test"):
        opp.status = Status.PUBLISHED
        opp.published_at = now
        opp.status_note = None if mode == "live" else "Published in TEST_MODE (logged only, not sent)."
    if queue_row:
        queue_row.status = "published" if mode in ("live", "test") else "dry_run"
        queue_row.note = None
    session.flush()
    return PublishOutcome(True, "published" if mode == "live" else "logged",
                          "sent to Telegram" if mode == "live" else f"{mode}: logged, not sent", opp.id, msg_id)


def publish_daily(session: Session, sport: str, *, day: date | None = None, client: TelegramClient | None = None,
                  now: datetime | None = None, max_attempts: int = 3) -> PublishOutcome:
    """The scheduled job. At most one post per sport per local day."""
    now = now or datetime.now(timezone.utc)
    day = day or local_today(now)
    mode = current_mode()

    if get_settings().auto_approve:
        from app.pipeline.workflow import auto_approve

        auto_approve(session, sport)  # approved items wait in the queue; one goes out per day

    if _already_sent_today(session, sport, day, mode):
        return PublishOutcome(False, "skipped", f"{sport}: already posted on {day}")

    row = session.scalar(select(PublishingQueue).where(PublishingQueue.sport == sport,
                                                       PublishingQueue.publish_date == day))
    tried: set[int] = set()
    last_blocked: PublishOutcome | None = None
    for _ in range(max_attempts):
        if row is not None and row.status == "published":
            return PublishOutcome(False, "skipped", f"{sport}: {day} slot already published", row.opportunity_id)
        if row is not None and row.status == "scheduled" and row.opportunity_id not in tried:
            opp = session.get(Opportunity, row.opportunity_id)
        else:
            ranked = [r for r in rank_candidates(session, sport, day, now) if r.opp.id not in tried]
            if not ranked:
                return last_blocked or PublishOutcome(False, "skipped",
                                                      f"{sport}: nothing approved and ready to publish")
            if get_settings().pick_mode == "random":
                # same day + sport -> same shuffle, so a re-run picks the same item
                opp = random.Random(f"{sport}:{day}:{len(tried)}").choice(ranked).opp
            else:
                opp = ranked[0].opp
            if row is None:
                row = PublishingQueue(sport=sport, publish_date=day, opportunity_id=opp.id, status="scheduled")
                session.add(row)
            else:
                row.opportunity_id, row.status, row.note = opp.id, "scheduled", None
            session.flush()
        tried.add(opp.id)
        if opp.status == Status.SCHEDULED and opp.scheduled_for and opp.scheduled_for != day:
            opp.scheduled_for = day
        row.status = "publishing"
        session.flush()
        outcome = publish_opportunity(session, opp, client=client, now=now, queue_row=row)
        if outcome.ok or outcome.status == "failed":
            session.commit()
            return outcome
        if opp.status == Status.SCHEDULED:  # blocked: release it from this slot
            opp.status, opp.scheduled_for = Status.APPROVED, None
            opp.status_note = f"Publish blocked on {day}: {outcome.message}"
        last_blocked = outcome
        session.commit()  # keep the blocked note, then try the next candidate
    return last_blocked or PublishOutcome(False, "blocked", f"{sport}: no candidate passed revalidation/guardrails")
