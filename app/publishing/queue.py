"""Pick the best approved opportunity for a sport's daily slot (quality, freshness, variety)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Opportunity, School, Status

CONF_MULT = {"HIGH": 1.0, "MEDIUM": 0.9, "LOW": 0.6}


@dataclass
class Ranked:
    opp: Opportunity
    rank: float
    notes: list[str]


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rank_candidates(session: Session, sport: str, day: date, now: datetime | None = None) -> list[Ranked]:
    now = now or datetime.now(timezone.utc)
    cands = session.scalars(select(Opportunity).where(
        Opportunity.sport == sport, Opportunity.status == Status.APPROVED)).all()
    recent = session.scalars(select(Opportunity).where(
        Opportunity.sport == sport, Opportunity.status == Status.PUBLISHED,
        Opportunity.published_at >= now - timedelta(days=30))).all()
    recent_sorted = sorted(recent, key=lambda o: _aware(o.published_at), reverse=True)
    last3_positions = [o.position_group for o in recent_sorted[:3]]
    recent_schools = {o.school_id for o in recent_sorted}
    last_division = recent_sorted[0].school.division if recent_sorted else None

    out = []
    for o in cands:
        if o.expires_at and _aware(o.expires_at) < now:
            continue
        if o.confidence == "LOW" and not o.low_confidence_override:
            continue
        notes = []
        r = o.signal * CONF_MULT.get(o.confidence, 0.6)
        age_days = (now - _aware(o.last_verified_at)).total_seconds() / 86400
        if age_days > 2:
            r -= 0.5 * (age_days - 2)
            notes.append(f"-{0.5 * (age_days - 2):.1f} freshness")
        if o.position_group in last3_positions:
            pen = 15 * last3_positions.count(o.position_group)
            r -= pen
            notes.append(f"-{pen} same position recently")
        if o.school_id in recent_schools:
            r -= 25
            notes.append("-25 school posted in last 30d")
        if last_division and o.school.division == last_division:
            r -= 5
            notes.append("-5 same division as last post")
        out.append(Ranked(o, round(r, 2), notes))
    out.sort(key=lambda x: (-x.rank, x.opp.id))
    return out
