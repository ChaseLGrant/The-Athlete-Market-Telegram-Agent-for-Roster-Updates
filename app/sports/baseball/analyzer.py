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
RESTOCK_DAMPING = 0.4

PLURAL = {
    "C": "catchers", "INF": "infielders", "MIF": "middle infielders", "CIF": "corner infielders",
    "OF": "outfielders", "RHP": "right-handed pitchers", "LHP": "left-handed pitchers", "P": "pitchers",
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


def _sum(players, attr: str, key: str) -> float:
    """Usage-weighted sum over Members (a bare player list counts each at 1.0)."""
    tot = 0.0
    for item in players:
        p, w = (item[0], item[2]) if isinstance(item, tuple) else (item, 1.0)
        d = getattr(p, attr)
        if d and d.get(key) is not None:
            tot += w * d[key]
    return tot


def _wcount(items: Members, usage: bool = False) -> float:
    return sum(u if usage else w for _, w, u in items)


FLEX = 0.5  # weight of a player who may play the position but isn't listed there first (audit fix 2026-10-30)

_TOKEN_GROUP = {"C", "OF", "MIF", "CIF", "INF", "UT"}

# [(player, depth weight, usage weight)]. Listed there first: (1, 1). A plain INF on a team that splits its
# infield: (FLEX, FLEX) in both MIF and CIF, since their starts belong to one of the two. A second listed position,
# a UT player or a pitcher with no throwing hand: (FLEX, 0), partial depth only, because we can't tell where
# their playing time came from.
Members = list


def _listed_hitter_groups(p: BBPlayer) -> list[str]:
    """Every hitter group the roster lists for the player, in order ('1B/OF' -> CIF, OF)."""
    from app.sports.baseball.positions import _TOKEN_MAP

    out = []
    for t in p.pos.tokens:
        g = _TOKEN_MAP.get(t)
        if g in _TOKEN_GROUP and g not in out:
            out.append(g)
    return out


def _hitter_groups(team: TeamInput) -> dict[str, Members]:
    """Hitters by group. A school that splits its infield (SS/2B vs 1B/3B for anyone) keeps MIF and CIF apart;
    a plain 'INF' player there counts in both at FLEX weight instead of merging the team's whole infield into
    one group (audit fix 2026-10-30). Only when nobody is listed MIF/CIF does the team get a single INF group.
    A second listed position ('1B/OF') counts at FLEX weight; UT players count at FLEX in the infield and OF
    groups. DH-only players aren't in a fielding group."""
    listed = {id(p): _listed_hitter_groups(p) for p in team.players}
    specific = sum(1 for g in listed.values() if "MIF" in g or "CIF" in g)
    generic = sum(1 for g in listed.values() if "INF" in g and "MIF" not in g and "CIF" not in g)
    # split when the school really lists SS/2B vs 1B/3B (not when one two-way arm is "RHP/1B")
    split = specific >= 2 and specific >= generic
    infield = ("MIF", "CIF") if split else ("INF",)
    groups: dict[str, Members] = {"C": [], "OF": [], **{g: [] for g in infield}}

    def targets(g: str, first: bool) -> tuple[tuple[str, ...], float, float]:
        """(groups, depth weight, usage weight) for one listed position."""
        if g == "UT":
            return infield + ("OF",), FLEX, 0.0
        if g in ("C", "OF", "MIF", "CIF", "INF"):
            tg = (g,) if g in ("C", "OF") else ((g,) if split and g != "INF" else infield)
            if not first:
                return tg, FLEX, 0.0
            if g == "INF" and split:
                return tg, FLEX, FLEX
            return tg, 1.0, 1.0
        return (), 0.0, 0.0  # DH

    for p in team.players:
        for i, g in enumerate(listed[id(p)]):
            tgs, w, u = targets(g, i == 0)
            for t in tgs:
                if not any(q is p for q, _, _ in groups[t]):  # first listing wins
                    groups[t].append((p, w, u))
    return groups


def _pitcher_groups(team: TeamInput) -> dict[str, Members]:
    """RHP / LHP. A pitcher listed only as 'P' with no throwing hand counts in both at FLEX weight; when most
    of a staff has no hand listed, the whole staff is one 'P' group instead (audit fix 2026-10-30)."""
    pitchers = [p for p in team.players if p.pos.pitcher_group in ("RHP", "LHP", "P")]
    base = [p for p in pitchers if p.status != INCOMING]  # judge the staff that pitched, not the newcomers
    unknown = [p for p in base if p.pos.pitcher_group == "P"]
    if base and len(unknown) * 2 >= len(base):
        return {"P": [(p, 1.0, 1.0) for p in pitchers]}
    groups: dict[str, Members] = {"RHP": [], "LHP": []}
    for p in pitchers:
        if p.pos.pitcher_group == "P":
            groups["RHP"].append((p, FLEX, 0.0))
            groups["LHP"].append((p, FLEX, 0.0))
        else:
            groups[p.pos.pitcher_group].append((p, 1.0, 1.0))
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
    team: TeamInput, spec: PositionGroupSpec, members: Members, cfg: SportConfig, now: datetime
) -> PositionAnalysis:
    kind = spec.kind
    base = [x for x in members if x[0].status != INCOMING]
    incoming = [x for x in members if x[0].status == INCOMING]
    departing = [x for x in base if x[0].status in DEPARTING]
    returning = [x for x in base if x[0].status not in DEPARTING]
    full = lambda items: [p for p, w, _ in items if w >= 1.0]  # noqa: E731
    flex = lambda items: [p for p, w, _ in items if w < 1.0]  # noqa: E731

    # Counts shown in posts and reports are players LISTED at the position; flex players (a second listed
    # position, plain INF on a team that splits its infield, UT, P with no hand) are counted separately and
    # enter the shares and depth at FLEX weight.
    m: dict = {
        "roster_count": len(full(base)),
        "departing_count": len(full(departing)),
        "returning_count": len(full(returning)),
        "final_year_listed_count": sum(1 for p in full(departing) if p.status == FINAL_YEAR),
        "not_on_current_roster_count": sum(1 for p in full(departing) if p.status == NOT_ON_ROSTER),
        "known_incoming_count": len(full(incoming)),
        "returning_experienced_count": sum(1 for p in full(returning) if _is_experienced(p, kind)),
        "flex_roster_count": len(flex(base)),
        "flex_departing_count": len(flex(departing)),
        "flex_returning_count": len(flex(returning)),
        "flex_incoming_count": len(flex(incoming)),
        "flex_returning_experienced_count": sum(1 for p in flex(returning) if _is_experienced(p, kind)),
        # plain "INF" players on a team that splits its infield: their numbers enter at half weight
        "split_inf_count": sum(1 for p, w, u in base if w < 1.0 and u > 0),
        "split_inf_departing_count": sum(1 for p, w, u in departing if w < 1.0 and u > 0),
        "roster_complete": not team.roster_incomplete,
        "incoming_known": team.incoming_known,
        "unpositioned_newcomer_count": team.unpositioned_newcomers,
    }
    dep_w, ret_w, inc_w = _wcount(departing), _wcount(returning), _wcount(incoming)
    exp_w = sum(w for p, w, _ in returning if _is_experienced(p, kind))

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
        starters = [x for x in base if (x[0].pitching or {}).get("app") and
                    (x[0].pitching["gs"] or 0) / x[0].pitching["app"] >= bb.STARTER_GS_RATIO]
        st_outs_t = _sum(starters, "pitching", "outs")
        st_outs_d = _sum([x for x in starters if x[0].status in DEPARTING], "pitching", "outs")
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

    # Newcomers already listed at the position refill it (audit fix 2026-10-30, the NMSU RHP case): the
    # restock ratio (weighted newcomers / weighted departures, capped at 1) both raises the incoming penalty
    # and scales the final signal down by up to RESTOCK_DAMPING.
    dep_u, inc_u = _wcount(departing, usage=True), _wcount(incoming, usage=True)
    restock = min(inc_u / dep_u, 1.0) if dep_u and inc_u else 0.0
    m["restock_ratio"] = round(restock, 4)
    components = {
        "turnover": share(dep_u, _wcount(base, usage=True)),
        "usage_departing": usage,
        "production_departing": production,
        "depth_gap": 1 - min(ret_w / spec.target_depth, 1.0),
        "experience_gap": 1 - min(exp_w / spec.target_experienced, 1.0),
        "incoming": max(min(inc_u / spec.target_depth, 1.0), restock) if incoming else 0.0,
    }

    # ---- data quality & confidence
    class_known = share(sum(1 for p, _, _ in base if p.class_year != "UNKNOWN"), len(base))
    pos_conf = mean_known(*[p.pos.confidence for p, _, _ in base]) if base else None
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
    if conf == "HIGH" and (team.roster_incomplete or not team.incoming_known or team.unpositioned_newcomers):
        conf = "MEDIUM"  # newcomers can't be counted: never HIGH
    sig = compute_signal(components, cfg.weights, dq)
    signal = round(sig.signal * (1 - RESTOCK_DAMPING * restock), 1)

    # ---- gates
    failures = []
    if volume < spec.min_volume:
        failures.append(f"low volume ({volume:.0f} < {spec.min_volume})")
    if not full(departing):
        failures.append("no departing players listed at the position")
    if signal < cfg.min_candidate_signal:
        failures.append(f"signal {signal} < {cfg.min_candidate_signal}")
    if "A" not in (team.roster_tier,) or "A" not in (team.stats_tier,):
        failures.append("needs Tier A roster and stats")

    rows = [{**_player_row(p, kind), "weight": w, "usage_weight": u}
            for p, w, u in sorted(members, key=lambda x: _usage_of(x[0], kind), reverse=True)]
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
        basis=team.basis, signal=signal, raw=sig.raw, confidence=conf, data_quality=dq,
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
    if m.get("split_inf_count"):
        core += (f" Those shares also count {m['split_inf_count']} player(s) listed only as INF at half weight "
                 f"({m['split_inf_departing_count']} of them departing).")
    still = "are on the current roster" if team.basis == "observed" else "are not listed as seniors/grads"
    tail = (f" {m['returning_count']} {still}, {m['returning_experienced_count']} with significant "
            f"{team.stats_season} experience.")
    if m.get("flex_returning_count"):
        tail += (f" {m['flex_returning_count']} more returning player(s) also list the position or a utility "
                 f"role and are counted as partial depth.")
    if m["known_incoming_count"]:
        tail += f" {m['known_incoming_count']} newcomer(s) listed at the position."
    if not m.get("roster_complete", True):
        tail += (" The current roster looks incomplete, so departures are projected from class year on the "
                 f"{team.stats_season} roster and newcomers aren't counted.")
    elif not m.get("incoming_known", True):
        tail += " The current roster doesn't list positions for most newcomers, so they aren't counted."
    elif m.get("unpositioned_newcomer_count"):
        tail += (f" {m['unpositioned_newcomer_count']} newcomer(s) on the current roster have no position listed "
                 f"yet, so they aren't counted here.")
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
