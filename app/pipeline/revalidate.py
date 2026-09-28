"""Re-check sources before publishing anything that hasn't been verified recently."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.collectors.base import ParseError, SourceUnavailable
from app.logging_setup import record_event
from app.models import Opportunity, OppType, Status
from app.pipeline.opportunities import upsert_from_analysis
from app.pipeline.research import collect_and_analyze
from app.settings import get_settings


@dataclass
class RevalidationResult:
    outcome: str  # "fresh" | "ok" | "changed" | "blocked"
    message: str


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def needs_revalidation(opp: Opportunity, now: datetime) -> bool:
    limit = timedelta(hours=get_settings().revalidate_after_hours)
    return now - _aware(opp.last_verified_at) > limit


def revalidate(session: Session, opp: Opportunity, *, now: datetime | None = None,
               force: bool = False) -> RevalidationResult:
    now = now or datetime.now(timezone.utc)
    if opp.opportunity_type == OppType.VERIFIED:
        # verified needs are entered by an admin with a source; re-check = admin review
        if force or needs_revalidation(opp, now):
            return RevalidationResult("blocked", "Verified needs older than the revalidation window must be "
                                                 "re-confirmed by an admin (open the source and re-save).")
        return RevalidationResult("fresh", "recently verified")
    if not force and not needs_revalidation(opp, now):
        return RevalidationResult("fresh", "recently verified")

    status_before = opp.status
    try:
        analyses, sources = collect_and_analyze(session, opp.team, now=now)
    except (SourceUnavailable, ParseError) as e:
        msg = getattr(e, "reason", str(e))
        record_event(session, "revalidation_blocked", f"#{opp.id}: {msg}", level="WARNING", sport=opp.sport,
                     entity_type="opportunity", entity_id=opp.id)
        return RevalidationResult("blocked", f"Could not re-check sources: {msg}")

    match = next((a for a in analyses if a.position_group == opp.position_group), None)
    if match is None or match.target_season != opp.target_season:
        if opp.status != Status.PUBLISHED:
            opp.status = Status.EXPIRED
            opp.status_note = ("Superseded: the roster/stats season changed; a fresh analysis was created."
                               if match else "Position group no longer present in the roster analysis.")
        for a in analyses:  # store fresh analyses (may create the newer-season opportunity)
            upsert_from_analysis(session, opp.team, a, sources, now=now)
        record_event(session, "revalidation_changed", f"#{opp.id}: {opp.status_note}", level="WARNING",
                     sport=opp.sport, entity_type="opportunity", entity_id=opp.id)
        return RevalidationResult("changed", opp.status_note or "changed")

    for a in analyses:
        upsert_from_analysis(session, opp.team, a, sources, now=now)
    session.flush()
    if opp.status != status_before and status_before != Status.PUBLISHED:
        return RevalidationResult("changed", opp.status_note or f"status changed to {opp.status}")
    return RevalidationResult("ok", "sources re-checked; no material change")
