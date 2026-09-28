"""Baseball positional turnover analysis. Pure, deterministic, no I/O.

See docs/BASEBALL_METHODOLOGY.md for the reasoning behind every number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

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
from app.sports.baseball import config as bb
from app.sports.baseball.stats import outs_to_ip
from app.sports.baseball.team_input import DEPARTING, FINAL_YEAR, INCOMING, NOT_ON_ROSTER, BBPlayer, TeamInput

INFIELD = {"MIF", "CIF", "INF"}

PLURAL = {
    "C": "catchers", "INF": "infielders", "MIF": "middle infielders", "CIF": "corner infielders",
    "OF": "outfielders", "RHP": "right-handed pitchers", "LHP": "left-handed pitchers",
}


@dataclass
class PositionAnalysis:
    sport: str
    school_slug: str
    position_group: str
    position_label: str
    kind: str
    target_season: str
    stats_season: str
    roster_season: str
    basis: str
    signal: float
    raw: float
    confidence: str
    data_quality: float
    quality_parts: dict
    components: dict
    metrics: dict
    reason: str
    player_rows: list[dict]
    evidence_hash: str
    passes_gates: bool
    gate_failures: list[str] = field(default_factory=list)


def _sum(players: list[BBPlayer], attr: str, key: str) -> float:
    tot = 0.0
    for p in players:
        d = getattr(p, attr)
        if d and d.get(key) is not None:
            tot += d[key]
    return tot


def _hitter_groups(team: TeamInput) -> dict[str, list[BBPlayer]]:
    groups: dict[str, list[BBPlayer]] = {"C": [], "OF": [], "MIF": [], "CIF": [], "INF": []}
    infielders = [p for p in team.players if p.pos.hitter_group in INFIELD]
    generic = any(p.pos.hitter_group == "INF" for p in infielders)
    for p in team.players:
        g = p.pos.hitter_group
        if g in ("C", "OF"):
            groups[g].append(p)
        elif g in INFIELD:
            groups["INF" if generic else g].append(p)
    if generic:
        groups.pop("MIF")
        groups.pop("CIF")
    else:
        groups.pop("INF")
    return groups


def _pitcher_groups(team: TeamInput) -> dict[str, list[BBPlayer]]:
    groups: dict[str, list[BBPlayer]] = {"RHP": [], "LHP": []}
    for p in team.players:
        if p.pos.pitcher_group in groups:
            groups[p.pos.pitcher_group].append(p)
    return groups


def _is_experienced(p: BBPlayer, kind: str) -> bool:
    if kind == "hitter":
        b = p.batting or {}
        return (b.get("gs") or 0) >= bb.HITTER_EXPERIENCED_GS or (b.get("pa") or 0) >= bb.HITTER_EXPERIENCED_PA
    pt = p.pitching or {}
    return (pt.get("outs") or 0) >= bb.PITCHER_EXPERIENCED_IP * 3 or (pt.get("gs") or 0) >= bb.PITCHER_EXPERIENCED_GS


def _pct(x: float | None) -> int | None:
    return None if x is None else round(100 * x)


def _analyze_group(
    team: TeamInput, spec: PositionGroupSpec, members: list[BBPlayer], cfg: SportConfig, now: datetime
) -> PositionAnalysis:
    kind = spec.kind
    base = [p for p in members if p.status != INCOMING]
    incoming = [p for p in members if p.status == INCOMING]
    departing = [p for p in base if p.status in DEPARTING]
    returning = [p for p in base if p.status not in DEPARTING]

    m: dict = {
        "roster_count": len(base),
        "departing_count": len(departing),
        "returning_count": len(returning),
        "final_year_listed_count": sum(1 for p in departing if p.status == FINAL_YEAR),
        "not_on_current_roster_count": sum(1 for p in departing if p.status == NOT_ON_ROSTER),
        "known_incoming_count": len(incoming),
        "returning_experienced_count": sum(1 for p in returning if _is_experienced(p, kind)),
    }

    if kind == "hitter":
        starts_t, starts_d = _sum(base, "batting", "gs"), _sum(departing, "batting", "gs")
        pa_t, pa_d = _sum(base, "batting", "pa"), _sum(departing, "batting", "pa")
        pr_t, pr_d = _sum(base, "batting", "production"), _sum(departing, "batting", "production")
        m.update(
            starts_total=int(starts_t), starts_departing=int(starts_d),
            pa_total=int(pa_t), pa_departing=int(pa_d),
            production_total=int(pr_t), production_departing=int(pr_d),
            starts_departing_share=share(starts_d, starts_t),
            pa_departing_share=share(pa_d, pa_t),
            production_departing_share=share(pr_d, pr_t),
            hr_departing=int(_sum(departing, "batting", "hr")), hr_total=int(_sum(base, "batting", "hr")),
        )
        usage = mean_known(m["starts_departing_share"], m["pa_departing_share"])
        production = m["production_departing_share"]
        volume = starts_t
    else:
        outs_t, outs_d = _sum(base, "pitching", "outs"), _sum(departing, "pitching", "outs")
        gs_t, gs_d = _sum(base, "pitching", "gs"), _sum(departing, "pitching", "gs")
        starters = [p for p in base if (p.pitching or {}).get("app") and
                    (p.pitching["gs"] or 0) / p.pitching["app"] >= bb.STARTER_GS_RATIO]
        st_outs_t = _sum(starters, "pitching", "outs")
        st_outs_d = _sum([p for p in starters if p.status in DEPARTING], "pitching", "outs")
        m.update(
            ip_total=outs_to_ip(int(outs_t)), ip_departing=outs_to_ip(int(outs_d)),
            outs_total=int(outs_t), outs_departing=int(outs_d),
            ip_departing_share=share(outs_d, outs_t),
            gs_total=int(gs_t), gs_departing=int(gs_d), gs_departing_share=share(gs_d, gs_t),
            starter_ip_departing_share=share(st_outs_d, st_outs_t),
            so_departing_share=share(_sum(departing, "pitching", "so"), _sum(base, "pitching", "so")),
            sv_departing=int(_sum(departing, "pitching", "sv")), sv_total=int(_sum(base, "pitching", "sv")),
            appearances_total=int(_sum(base, "pitching", "app")),
        )
        usage = mean_known(m["ip_departing_share"], m["gs_departing_share"] if gs_t else None)
        production = m["ip_departing_share"]
        volume = outs_t / 3

    components = {
        "turnover": share(len(departing), len(base)),
        "usage_departing": usage,
        "production_departing": production,
        "depth_gap": 1 - min(len(returning) / spec.target_depth, 1.0),
        "experience_gap": 1 - min(m["returning_experienced_count"] / spec.target_experienced, 1.0),
        "incoming": min(len(incoming) / spec.target_depth, 1.0) if incoming else 0.0,
    }

    # ---- data quality & confidence
    class_known = share(sum(1 for p in base if p.class_year != "UNKNOWN"), len(base))
    pos_conf = mean_known(*[p.pos.confidence for p in base]) if base else None
    try:
        gap = int(team.roster_season[:4]) - int(team.stats_season[:4])
    except ValueError:
        gap = 99
    recency = recency_score(min(team.roster_fetched_at, team.stats_fetched_at), now, gap)
    basis = "observed" if team.basis == "observed" else "class_year_projection"
    dq, parts = compute_data_quality(
        tiers=[team.roster_tier, team.stats_tier], match_rate=team.match_rate, class_known=class_known,
        position_confidence=pos_conf, recency=recency, basis=basis, w=cfg.quality_weights,
    )
    conf = confidence_label(dq, team.match_rate, basis)
    sig = compute_signal(components, cfg.weights, dq)

    # ---- gates
    failures = []
    if volume < spec.min_volume:
        failures.append(f"low volume ({volume:.0f} < {spec.min_volume})")
    if not departing:
        failures.append("no departing players")
    if sig.signal < cfg.min_candidate_signal:
        failures.append(f"signal {sig.signal} < {cfg.min_candidate_signal}")
    if "A" not in (team.roster_tier,) or "A" not in (team.stats_tier,):
        failures.append("needs Tier A roster and stats")

    rows = [_player_row(p, kind) for p in sorted(members, key=lambda p: _usage_of(p, kind), reverse=True)]
    reason = _reason(spec, kind, m, team)
    target = str(int(team.stats_season[:4]) + 1) if team.stats_season[:4].isdigit() else team.stats_season

    ehash = evidence_hash({
        "players": sorted((r["key"], r["status"]) for r in rows),
        "m": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()},
        "basis": team.basis, "stats": team.stats_season, "roster": team.roster_season,
    })
    return PositionAnalysis(
        sport=cfg.key, school_slug=team.school_slug, position_group=spec.key, position_label=spec.label,
        kind=kind, target_season=target, stats_season=team.stats_season, roster_season=team.roster_season,
        basis=team.basis, signal=sig.signal, raw=sig.raw, confidence=conf, data_quality=dq,
        quality_parts=parts, components={k: (round(v, 4) if v is not None else None) for k, v in components.items()},
        metrics={k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()},
        reason=reason, player_rows=rows, evidence_hash=ehash, passes_gates=not failures, gate_failures=failures,
    )


def _usage_of(p: BBPlayer, kind: str) -> float:
    if kind == "hitter":
        return float((p.batting or {}).get("pa") or 0)
    return float((p.pitching or {}).get("outs") or 0)


def _player_row(p: BBPlayer, kind: str) -> dict:
    row = {
        "key": p.key, "name": p.name, "jersey": p.jersey, "position_raw": p.position_raw,
        "class_year_raw": p.class_year_raw, "class_year": p.class_year, "status": p.status,
        "two_way": p.pos.is_two_way, "match_method": p.match_method,
    }
    if kind == "hitter":
        b = p.batting or {}
        row.update(gp=b.get("gp"), gs=b.get("gs"), pa=b.get("pa"), ab=b.get("ab"), avg=b.get("avg"),
                   obp=b.get("obp"), slg=b.get("slg"), ops=b.get("ops"), hr=b.get("hr"), production=b.get("production"))
    else:
        pt = p.pitching or {}
        row.update(app=pt.get("app"), gs=pt.get("gs"), ip=pt.get("ip"), outs=pt.get("outs"), era=pt.get("era"),
                   whip=pt.get("whip"), so=pt.get("so"), sv=pt.get("sv"))
    return row


def departing_phrase(basis: str) -> str:
    return ("are no longer listed on the current roster" if basis == "observed"
            else "are listed as seniors or graduate students")


def _reason(spec: PositionGroupSpec, kind: str, m: dict, team: TeamInput) -> str:
    noun = PLURAL.get(spec.key, spec.label.lower())
    dep = m["departing_count"]
    if kind == "hitter":
        s = _pct(m.get("starts_departing_share"))
        p = _pct(m.get("production_departing_share"))
        core = (f"{dep} of {m['roster_count']} listed {noun} {departing_phrase(team.basis)}; they accounted for "
                f"~{s}% of starts and ~{p}% of production (TB+BB+HBP) by listed {noun} in {team.stats_season}.")
    else:
        ip = _pct(m.get("ip_departing_share"))
        core = (f"{dep} of {m['roster_count']} listed {noun} {departing_phrase(team.basis)}; they threw "
                f"~{ip}% of innings by listed {noun} in {team.stats_season}.")
    still = "are on the current roster" if team.basis == "observed" else "are not listed as seniors/grads"
    tail = (f" {m['returning_count']} {still}, {m['returning_experienced_count']} with significant "
            f"{team.stats_season} experience.")
    if m["known_incoming_count"]:
        tail += f" {m['known_incoming_count']} newcomer(s) listed at the position."
    return core + tail


def analyze_team(team: TeamInput, cfg: SportConfig, now: datetime | None = None) -> list[PositionAnalysis]:
    now = now or datetime.now(timezone.utc)
    out: list[PositionAnalysis] = []
    for groups in (_hitter_groups(team), _pitcher_groups(team)):
        for key, members in groups.items():
            if not members:
                continue
            out.append(_analyze_group(team, cfg.position(key), members, cfg, now))
    return out
