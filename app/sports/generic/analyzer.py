"""Positional turnover analysis for usage-based sports. Pure, deterministic, no I/O.

Same signal / data-quality / confidence math as baseball (app/analysis/common.py); what changes per
sport is *how playing time is measured* (minutes, starts, yards, tackles), given by GroupMeasure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.analysis.common import (
    compute_data_quality,
    compute_signal,
    confidence_label,
    evidence_hash,
    mean_known,
    recency_score,
    share,
)
from app.sports.base import PositionGroupSpec, SportConfig
from app.sports.baseball.analyzer import PositionAnalysis
from app.sports.generic.team_input import FINAL_YEAR, GPlayer, GTeamInput
from app.sports.seasons import next_season, start_year

Stats = dict[str, dict]  # table kind -> normalized numbers


@dataclass(frozen=True)
class GroupMeasure:
    usage_label: str                                   # "minutes", "rushing yards", "tackles"
    usage: Callable[[Stats], float | None]             # the playing-time measure
    experienced: Callable[[Stats], bool]               # "significant experience" last season
    starts: Callable[[Stats], float | None] | None = None
    production: Callable[[Stats], float | None] | None = None
    production_label: str | None = None


def _sum(players: list[GPlayer], fn: Callable[[Stats], float | None] | None) -> tuple[float, int]:
    """(sum of known values, how many players had a known value)."""
    if fn is None:
        return 0.0, 0
    tot, n = 0.0, 0
    for p in players:
        v = fn(p.stats) if p.stats else None
        if v is not None:
            tot += v
            n += 1
    return tot, n


def _analyze_group(team: GTeamInput, spec: PositionGroupSpec, members: list[GPlayer], measure: GroupMeasure,
                   cfg: SportConfig, now: datetime) -> PositionAnalysis:
    departing = [p for p in members if p.status == FINAL_YEAR]
    returning = [p for p in members if p.status != FINAL_YEAR]

    use_t, use_n = _sum(members, measure.usage)
    use_d, _ = _sum(departing, measure.usage)
    st_t, st_n = _sum(members, measure.starts)
    st_d, _ = _sum(departing, measure.starts)
    pr_t, pr_n = _sum(members, measure.production)
    pr_d, _ = _sum(departing, measure.production)

    m: dict = {
        "roster_count": len(members),
        "departing_count": len(departing),
        "returning_count": len(returning),
        "final_year_listed_count": len(departing),
        "not_on_current_roster_count": 0,
        "known_incoming_count": 0,
        "returning_experienced_count": sum(1 for p in returning if p.stats and measure.experienced(p.stats)),
        "already_departed_team_count": team.already_departed,
        "usage_label": measure.usage_label,
        "usage_total": round(use_t, 1) if use_n else None,
        "usage_departing": round(use_d, 1) if use_n else None,
        "usage_departing_share": share(use_d, use_t) if use_n else None,
        "starts_total": int(st_t) if st_n else None,
        "starts_departing": int(st_d) if st_n else None,
        "starts_departing_share": share(st_d, st_t) if st_n else None,
        "production_label": measure.production_label,
        "production_departing_share": share(pr_d, pr_t) if pr_n else None,
    }
    components = {
        "turnover": share(len(departing), len(members)),
        "usage_departing": mean_known(m["usage_departing_share"], m["starts_departing_share"]),
        "production_departing": m["production_departing_share"],
        "depth_gap": 1 - min(len(returning) / spec.target_depth, 1.0),
        "experience_gap": 1 - min(m["returning_experienced_count"] / spec.target_experienced, 1.0),
        "incoming": 0.0,
    }

    class_known = share(sum(1 for p in members if p.class_year != "UNKNOWN"), len(members))
    pos_conf = mean_known(*[p.pos.confidence for p in members]) if members else None
    rs, ss = start_year(team.roster_season), start_year(team.stats_season)
    gap = (rs - ss) if rs is not None and ss is not None else 99
    recency = recency_score(min(team.roster_fetched_at, team.stats_fetched_at), now, gap)
    dq, parts = compute_data_quality(
        tiers=[team.roster_tier, team.stats_tier], match_rate=team.match_rate, class_known=class_known,
        position_confidence=pos_conf, recency=recency, basis=team.basis, w=cfg.quality_weights,
    )
    conf = confidence_label(dq, team.match_rate, team.basis)
    sig = compute_signal(components, cfg.weights, dq)

    failures = []
    if use_t < spec.min_volume:
        failures.append(f"low volume ({use_t:.0f} {measure.usage_label} < {spec.min_volume})")
    if not departing:
        failures.append("no players in their final listed year")
    if sig.signal < cfg.min_candidate_signal:
        failures.append(f"signal {sig.signal} < {cfg.min_candidate_signal}")
    if team.roster_tier != "A" or team.stats_tier != "A":
        failures.append("needs Tier A roster and stats")

    rows = [_row(p, measure) for p in sorted(members, key=lambda p: (measure.usage(p.stats) or 0) if p.stats else 0,
                                                 reverse=True)]
    reason = _reason(cfg, spec, m, team)
    ehash = evidence_hash({
        "players": sorted((r["key"], r["status"]) for r in rows),
        "m": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()},
        "basis": team.basis, "stats": team.stats_season, "roster": team.roster_season,
    })
    return PositionAnalysis(
        sport=cfg.key, school_slug=team.school_slug, position_group=spec.key, position_label=spec.label,
        kind=spec.kind, target_season=next_season(team.roster_season, cfg.season_style),
        stats_season=team.stats_season, roster_season=team.roster_season, basis=team.basis, signal=sig.signal,
        raw=sig.raw, confidence=conf, data_quality=dq, quality_parts=parts,
        components={k: (round(v, 4) if v is not None else None) for k, v in components.items()},
        metrics={k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()},
        reason=reason, player_rows=rows, evidence_hash=ehash, passes_gates=not failures, gate_failures=failures,
    )


def _row(p: GPlayer, measure: GroupMeasure) -> dict:
    st = p.stats or {}
    return {
        "key": p.key, "name": p.name, "jersey": p.jersey, "position_raw": p.position_raw,
        "class_year_raw": p.class_year_raw, "class_year": p.class_year, "status": p.status,
        "match_method": p.match_method, "has_stats": bool(st),
        "usage": measure.usage(st) if st else None,
        "starts": measure.starts(st) if st and measure.starts else None,
        "production": measure.production(st) if st and measure.production else None,
    }


def _pct(x: float | None) -> str:
    return "unknown" if x is None else f"{round(100 * x)}%"


def _reason(cfg: SportConfig, spec: PositionGroupSpec, m: dict, team: GTeamInput) -> str:
    noun = cfg.noun(spec.key)
    core = (f"{m['departing_count']} of {m['roster_count']} {noun} on the {team.roster_season} roster are listed as "
            f"seniors or graduate students; they recorded ~{_pct(m['usage_departing_share'])} of the "
            f"{m['usage_label']} by this roster's {noun} in {team.stats_season}")
    if m["starts_departing_share"] is not None:
        core += f" and ~{_pct(m['starts_departing_share'])} of their starts"
    tail = (f". {m['returning_count']} are not listed as seniors/grads, {m['returning_experienced_count']} with "
            f"significant {team.stats_season} experience.")
    return core + tail


def make_analyzer(measure_for: Callable[[str], GroupMeasure]):
    def analyze_team(team: GTeamInput, cfg: SportConfig, now: datetime | None = None) -> list[PositionAnalysis]:
        now = now or datetime.now(timezone.utc)
        out = []
        for spec in cfg.positions:
            members = [p for p in team.players if p.pos.primary == spec.key]
            if members:
                out.append(_analyze_group(team, spec, members, measure_for(spec.key), cfg, now))
        return out

    return analyze_team
