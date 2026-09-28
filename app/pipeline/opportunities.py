"""Create/update opportunities with fingerprint dedupe, evidence storage,
score history and material-change handling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.common import CONFIDENCE_RANK, fingerprint
from app.content.telegram_post import build_roster_post, build_x_teaser
from app.logging_setup import record_event
from app.models import (
    Opportunity,
    OpportunityEvidence,
    OppType,
    PublishingQueue,
    ScoreHistory,
    Source,
    Status,
    Team,
)
from app.settings import get_settings
from app.sports.registry import get_sport

SOURCE_LABELS = {"roster": "Official Roster", "stats": "Official Statistics",
                 "previous_roster": "Official Roster (last season)"}


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def render_content(opp: Opportunity, sources: list[Source], school_name: str, division: str | None) -> tuple[str, str]:
    cfg = get_sport(opp.sport)
    labelled = []
    for s in sources:
        kind = "previous_roster" if (s.kind == "roster" and s.season_label and opp.roster_season
                                     and s.season_label != opp.roster_season) else s.kind
        labelled.append((SOURCE_LABELS.get(kind, s.title or "Source"), s.url))
    tg = build_roster_post(
        school_name=school_name, division=division, sport_name=cfg.display_name, group=opp.position_group,
        position_label=opp.position_label, basis=opp.departure_basis or "class_year_projection",
        stats_season=opp.stats_season or "", target_season=opp.target_season, metrics=opp.metrics,
        components=opp.components, sources=labelled,
    )
    x = build_x_teaser(
        sport_name=cfg.display_name, division=division, group=opp.position_group,
        basis=opp.departure_basis or "class_year_projection", stats_season=opp.stats_season or "",
        metrics=opp.metrics, join_link=get_settings().join_link_for(opp.sport),
    )
    return tg, x


def _write_evidence(session: Session, opp: Opportunity, analysis, sources: dict[str, Source]) -> None:
    session.execute(delete(OpportunityEvidence).where(OpportunityEvidence.opportunity_id == opp.id))
    stats_src = sources.get("stats")
    roster_src = sources.get("roster")
    session.add(OpportunityEvidence(
        opportunity_id=opp.id, kind="summary", label=analysis.reason,
        data={"metrics": analysis.metrics, "components": analysis.components,
              "quality": analysis.quality_parts, "data_quality": analysis.data_quality,
              "basis": analysis.basis, "raw_signal": analysis.raw},
        source_id=stats_src.id if stats_src else None,
    ))
    for row in analysis.player_rows:
        session.add(OpportunityEvidence(
            opportunity_id=opp.id, kind="player",
            label=f"{row['name']} (#{row.get('jersey') or '?'}, {row.get('position_raw') or '?'}, "
                  f"{row.get('class_year_raw') or 'class unknown'}) — {row['status']}",
            data=row, source_id=stats_src.id if stats_src else (roster_src.id if roster_src else None),
        ))


def upsert_from_analysis(session: Session, team: Team, analysis, sources: dict[str, Source],
                         *, now: datetime | None = None) -> Opportunity | None:
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    cfg = get_sport(team.sport)
    fp = fingerprint(team.sport, team.school.slug, analysis.position_group, analysis.target_season, OppType.ROSTER)
    opp = session.scalar(select(Opportunity).where(Opportunity.fingerprint == fp))
    src_list = list(sources.values())
    source_time = min((x.fetched_at for x in src_list), default=now)

    if opp is None:
        if not analysis.passes_gates:
            return None
        opp = Opportunity(
            fingerprint=fp, sport=team.sport, school_id=team.school_id, team_id=team.id,
            opportunity_type=OppType.ROSTER, position_group=analysis.position_group,
            position_label=analysis.position_label, target_season=analysis.target_season,
            stats_season=analysis.stats_season, roster_season=analysis.roster_season,
            departure_basis=analysis.basis, signal=analysis.signal, confidence=analysis.confidence,
            data_quality=analysis.data_quality, components=analysis.components, metrics=analysis.metrics,
            reason=analysis.reason, evidence_hash=analysis.evidence_hash, status=Status.PENDING,
            first_detected_at=now, last_analyzed_at=now, last_verified_at=now, source_updated_at=source_time,
            expires_at=now + timedelta(days=s.opportunity_ttl_days),
        )
        session.add(opp)
        session.flush()
        opp.sources = src_list
        _write_evidence(session, opp, analysis, sources)
        opp.telegram_text, opp.x_teaser = render_content(opp, src_list, team.school.name, team.school.division)
        session.add(ScoreHistory(opportunity_id=opp.id, old_signal=None, new_signal=opp.signal,
                                 old_confidence=None, new_confidence=opp.confidence, reason="created"))
        record_event(session, "opportunity_created",
                     f"{team.school.name} {analysis.position_label}: signal {opp.signal} ({opp.confidence})",
                     sport=team.sport, entity_type="opportunity", entity_id=opp.id)
        return opp

    # ---- existing opportunity: dedupe + update
    record_event(session, "duplicate_detected", f"fingerprint exists (#{opp.id}); updating instead of creating",
                 sport=team.sport, entity_type="opportunity", entity_id=opp.id)
    old_signal, old_conf = opp.signal, opp.confidence
    material = (
        analysis.evidence_hash != opp.evidence_hash
        or abs(analysis.signal - (opp.signal or 0)) >= cfg.material_signal_change
        or CONFIDENCE_RANK.get(analysis.confidence, 0) < CONFIDENCE_RANK.get(opp.confidence, 0)
        or not analysis.passes_gates
    )
    opp.signal, opp.confidence, opp.data_quality = analysis.signal, analysis.confidence, analysis.data_quality
    opp.components, opp.metrics, opp.reason = analysis.components, analysis.metrics, analysis.reason
    opp.stats_season, opp.roster_season, opp.departure_basis = (analysis.stats_season, analysis.roster_season,
                                                                analysis.basis)
    opp.evidence_hash = analysis.evidence_hash
    opp.last_analyzed_at = opp.last_verified_at = now
    opp.source_updated_at = source_time
    opp.sources = src_list
    _write_evidence(session, opp, analysis, sources)

    if old_signal != opp.signal or old_conf != opp.confidence:
        session.add(ScoreHistory(opportunity_id=opp.id, old_signal=old_signal, new_signal=opp.signal,
                                 old_confidence=old_conf, new_confidence=opp.confidence,
                                 reason="material change" if material else "re-analysis"))
        record_event(session, "score_changed", f"#{opp.id} {old_signal}→{opp.signal} {old_conf}→{opp.confidence}",
                     sport=opp.sport, entity_type="opportunity", entity_id=opp.id)

    if opp.status == Status.PUBLISHED:
        # never re-queue something already published; keep the text that was sent
        return opp

    opp.expires_at = now + timedelta(days=s.opportunity_ttl_days)
    tg, x = render_content(opp, src_list, team.school.name, team.school.division)
    if not opp.telegram_text_edited:
        opp.telegram_text = tg
    opp.x_teaser = x if not opp.telegram_text_edited else opp.x_teaser

    if not analysis.passes_gates:
        opp.status = Status.EXPIRED
        opp.status_note = "No longer meets thresholds after re-analysis: " + "; ".join(analysis.gate_failures)
        _unqueue(session, opp)
    elif opp.status == Status.EXPIRED:
        opp.status = Status.PENDING
        opp.status_note = "Re-verified after expiring — please review."
    elif material and opp.status in (Status.APPROVED, Status.SCHEDULED):
        opp.status = Status.PENDING
        opp.status_note = "Sources changed materially — please review again." + (
            " Your edited copy was kept; check the numbers." if opp.telegram_text_edited else "")
        _unqueue(session, opp)
        record_event(session, "revalidation_changed", f"#{opp.id} returned to pending after material change",
                     level="WARNING", sport=opp.sport, entity_type="opportunity", entity_id=opp.id)
    return opp


def _unqueue(session: Session, opp: Opportunity) -> None:
    session.execute(delete(PublishingQueue).where(PublishingQueue.opportunity_id == opp.id,
                                                  PublishingQueue.status.in_(("scheduled", "blocked", "failed"))))
    opp.scheduled_for = None


def create_verified_need(session: Session, team: Team, *, position_group: str, position_label: str,
                         target_season: str, summary: str, source_url: str, source_label: str, tier: str,
                         publisher: str | None, author_account: str | None, quote: str,
                         now: datetime | None = None) -> Opportunity:
    """🟢 VERIFIED NEED — only from an explicit statement by the program/coach/official source.
    Entered by an admin with the source URL and the exact quote. Never produced by inference."""
    from app.content.telegram_post import build_verified_post

    now = now or datetime.now(timezone.utc)
    if tier not in ("A", "B"):
        raise ValueError("Verified needs require a Tier A (official) or Tier B source")
    if not source_url.startswith(("http://", "https://")):
        raise ValueError("source URL is required")
    if not quote.strip():
        raise ValueError("paste the exact statement from the source")
    if any(d in source_url for d in ("twitter.com", "x.com", "instagram.com", "facebook.com", "tiktok.com")) \
            and not (author_account or "").strip():
        raise ValueError("social media sources must record the original account")
    fp = fingerprint(team.sport, team.school.slug, position_group, target_season, OppType.VERIFIED)
    if session.scalar(select(Opportunity).where(Opportunity.fingerprint == fp)):
        raise ValueError("a verified need for this school/position/season already exists")
    src = Source(team_id=team.id, url=source_url, kind="official_statement", tier=tier, title=source_label,
                 publisher=publisher, author_account=author_account or None, fetched_at=now, available=True)
    session.add(src)
    session.flush()
    cfg = get_sport(team.sport)
    opp = Opportunity(
        fingerprint=fp, sport=team.sport, school_id=team.school_id, team_id=team.id,
        opportunity_type=OppType.VERIFIED, position_group=position_group, position_label=position_label,
        target_season=target_season, departure_basis="verified", signal=100.0,
        confidence="HIGH" if tier == "A" else "MEDIUM", data_quality=1.0 if tier == "A" else 0.8,
        components={}, metrics={}, reason=summary, status=Status.PENDING, first_detected_at=now,
        last_analyzed_at=now, last_verified_at=now, source_updated_at=now,
        expires_at=now + timedelta(days=get_settings().opportunity_ttl_days),
    )
    session.add(opp)
    session.flush()
    opp.sources = [src]
    session.add(OpportunityEvidence(opportunity_id=opp.id, kind="statement", label=source_label,
                                    data={"quote": quote, "author_account": author_account}, source_id=src.id))
    opp.telegram_text = build_verified_post(school_name=team.school.name, division=team.school.division,
                                            sport_name=cfg.display_name, position_label=position_label,
                                            summary=summary, source_label=source_label, source_url=source_url)
    link = get_settings().join_link_for(team.sport) or "[TELEGRAM LINK]"
    opp.x_teaser = (f"🚨 COLLEGE {cfg.display_name.upper()} — VERIFIED NEED\n\nA program has publicly said it is "
                    f"recruiting at {position_label.lower()}.\n\nSchool + source free in Telegram ↓\n{link}")
    record_event(session, "opportunity_created", f"verified need #{opp.id} entered by admin", sport=team.sport,
                 entity_type="opportunity", entity_id=opp.id)
    return opp
