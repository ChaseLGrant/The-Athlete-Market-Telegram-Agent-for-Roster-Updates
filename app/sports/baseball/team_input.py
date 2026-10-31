"""Turn raw roster(s) + raw stats into the analyzer's input: one record per player
with normalized position, class year, matched stats and departure status."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.analysis.common import last_name, name_key
from app.collectors.base import RawRoster, RawRosterPlayer, RawStatRow, RawStats
from app.sports.baseball.positions import (
    FINAL_YEAR_CLASSES,
    PositionResult,
    classify_position,
    normalize_class_year,
    parse_bats_throws,
)
from app.sports.baseball.stats import normalize_batting, normalize_pitching

RETURNING = "returning"
FINAL_YEAR = "final_year_listed"
NOT_ON_ROSTER = "not_on_current_roster"
INCOMING = "incoming"
DEPARTING = {FINAL_YEAR, NOT_ON_ROSTER}


@dataclass
class BBPlayer:
    key: str
    name: str
    site_player_id: str | None
    jersey: str | None
    position_raw: str | None
    pos: PositionResult
    class_year_raw: str | None
    class_year: str
    redshirt: bool | None
    throws: str | None
    previous_school: str | None
    status: str
    batting: dict | None = None
    pitching: dict | None = None
    batting_row_name: str | None = None
    match_method: str | None = None
    eligibility_remaining: int | None = None  # never inferred


@dataclass
class TeamInput:
    school_slug: str
    school_name: str
    division: str | None
    conference: str | None
    stats_season: str
    roster_season: str
    basis: str                      # "class_year_projection" | "observed"
    players: list[BBPlayer]         # base-season players (+ incoming)
    stats_rows_total: int
    stats_rows_matched: int
    unmatched_stats: list[str]
    roster_fetched_at: datetime
    stats_fetched_at: datetime
    roster_tier: str
    stats_tier: str
    source_urls: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    roster_incomplete: bool = False   # current roster looks like a partial upload (see roster_check)
    incoming_known: bool = True       # current roster lists positions, so newcomers can be counted
    # newcomers on the current roster listed without a position (UMW 2027 lists 7 such players): they may be at
    # any position, so no group can call itself fully known (added 2026-10-31)
    unpositioned_newcomers: int = 0

    @property
    def match_rate(self) -> float | None:
        return (self.stats_rows_matched / self.stats_rows_total) if self.stats_rows_total else None


def _jersey_num(j: str | None) -> int | None:
    return int(j) if j and j.strip().isdigit() and int(j) < 100 else None


def roster_check(prev: list, cur: list, norm_min: int = 0) -> list[str]:
    """Why the current roster looks incomplete compared with the stats-season roster (empty list = looks
    complete). Audit fix 2026-10-30, the Pacific case: a partial upload (18 players, no jerseys 0-9) read as
    seven of eight infielders gone. Checks: size vs last season (< 70%), size vs the sport's norm, and whole
    jersey ranges that were well used last season but are empty now."""
    why: list[str] = []
    if prev and len(cur) < 0.7 * len(prev):
        why.append(f"{len(cur)} players listed vs {len(prev)} last season")
    if norm_min and len(cur) < norm_min:
        why.append(f"{len(cur)} players listed, below the usual minimum of {norm_min}")
    pj = [n for n in (_jersey_num(p.jersey) for p in prev) if n is not None]
    cj = [n for n in (_jersey_num(p.jersey) for p in cur) if n is not None]
    if len(cj) >= 0.5 * len(cur) and pj:  # only judge jersey gaps when the roster shows jerseys
        for band in range(10):
            before = sum(1 for n in pj if n // 10 == band)
            if before >= 3 and not any(n // 10 == band for n in cj):
                why.append(f"no jerseys {band * 10}-{band * 10 + 9} (had {before} last season)")
    return why


def _player_from_raw(rp: RawRosterPlayer, status: str) -> BBPlayer:
    _, throws = parse_bats_throws(rp.bats_throws)
    pos = classify_position(rp.position_raw, throws)
    if pos.primary is None and rp.position_long:
        pos = classify_position(rp.position_long, throws)
    if pos.primary is None and rp.position_raw:
        from app.content.llm import classify_baseball_position

        g = classify_baseball_position(rp.position_raw)  # None unless LLM_ENABLED
        if g:
            pos = classify_position(g, throws)
            pos = PositionResult(pos.primary, pos.hitter_group, pos.pitcher_group, pos.is_two_way,
                                 min(pos.confidence, 0.6), pos.tokens)
    cy, rs = normalize_class_year(rp.class_year_raw)
    return BBPlayer(
        key=rp.site_player_id or name_key(rp.name),
        name=rp.name,
        site_player_id=rp.site_player_id,
        jersey=rp.jersey,
        position_raw=rp.position_raw,
        pos=pos,
        class_year_raw=rp.class_year_raw,
        class_year=cy,
        redshirt=rs,
        throws=throws,
        previous_school=rp.previous_school,
        status=status,
    )


class _Index:
    def __init__(self, players: list[BBPlayer]):
        self.by_id = {p.site_player_id: p for p in players if p.site_player_id}
        self.by_name: dict[str, list[BBPlayer]] = {}
        for p in players:
            self.by_name.setdefault(name_key(p.name), []).append(p)

    def find(self, name: str, site_id: str | None, jersey: str | None) -> tuple[BBPlayer | None, str | None]:
        if site_id and site_id in self.by_id:
            return self.by_id[site_id], "site_id"
        cands = self.by_name.get(name_key(name), [])
        if len(cands) == 1:
            return cands[0], "name"
        if len(cands) > 1 and jersey:
            j = [c for c in cands if c.jersey == jersey]
            if len(j) == 1:
                return j[0], "name+jersey"
        # last-name + jersey fallback (handles nicknames: "Mike" vs "Michael")
        if jersey:
            ln = last_name(name_key(name))
            j = [p for ps in self.by_name.values() for p in ps
                 if p.jersey == jersey and last_name(name_key(p.name)) == ln]
            if len(j) == 1:
                return j[0], "last+jersey"
        return None, None


def build_team_input(
    *,
    school_slug: str,
    school_name: str,
    division: str | None,
    conference: str | None,
    current_roster: RawRoster,
    stats: RawStats,
    stats_season_roster: RawRoster | None = None,
    roster_norm_min: int = 0,
) -> TeamInput:
    """If the current roster is newer than the stats season, pass the stats-season
    roster as `stats_season_roster` so departures are *observed* instead of projected."""
    observed = stats_season_roster is not None
    base_roster = stats_season_roster if observed else current_roster
    warnings = list(current_roster.warnings) + list(stats.warnings)

    players = [_player_from_raw(rp, RETURNING) for rp in base_roster.players]
    idx = _Index(players)

    # attach stats
    total = matched = 0
    unmatched: list[str] = []
    for kind in ("batting", "pitching"):
        rows: list[RawStatRow] = stats.tables.get(kind, [])
        for row in rows:
            total += 1
            p, method = idx.find(row.name, row.site_player_id, row.jersey)
            if p is None:
                unmatched.append(f"{kind}: {row.name} #{row.jersey or '?'}")
                continue
            matched += 1
            p.match_method = p.match_method or method
            if kind == "batting":
                p.batting = normalize_batting(row.values)
                p.batting_row_name = row.name
            else:
                p.pitching = normalize_pitching(row.values)

    # departure status
    incomplete_why: list[str] = []
    incoming_known = True
    unpositioned_newcomers = 0
    if observed:
        incomplete_why = roster_check(base_roster.players, current_roster.players, roster_norm_min)
        listed_pos = sum(1 for rp in current_roster.players if (rp.position_raw or rp.position_long or "").strip())
        incoming_known = listed_pos >= 0.5 * max(len(current_roster.players), 1)
    if incomplete_why:
        # a partial current roster can't show who left: project from class year on the stats-season roster
        # instead (seniors/grads leave), and don't count newcomers
        warnings.append("current roster looks incomplete: " + "; ".join(incomplete_why))
        observed = False
        incoming_known = False
        cur_idx = _Index([_player_from_raw(rp, INCOMING) for rp in current_roster.players])
        for p in players:
            cp, _ = cur_idx.find(p.name, p.site_player_id, p.jersey)
            if cp is not None:  # listed on the partial roster: back next season
                p.status = RETURNING
                p.class_year_raw, p.class_year, p.redshirt = cp.class_year_raw, cp.class_year, cp.redshirt
            else:
                p.status = FINAL_YEAR if p.class_year in FINAL_YEAR_CLASSES else RETURNING
    elif observed:
        cur_players = [_player_from_raw(rp, INCOMING) for rp in current_roster.players]
        cur_idx = _Index(cur_players)
        seen_current: set[int] = set()
        for p in players:
            cp, _ = cur_idx.find(p.name, p.site_player_id, p.jersey)
            if cp is None:
                p.status = NOT_ON_ROSTER
            else:
                p.status = RETURNING
                seen_current.add(id(cp))
                # newer class year for returning players; keep the stats-season position,
                # since usage is measured at the position they actually played
                p.class_year_raw, p.class_year, p.redshirt = cp.class_year_raw, cp.class_year, cp.redshirt
        if incoming_known:
            players.extend(cp for cp in cur_players if id(cp) not in seen_current)
        pos_of = {id(cp): (rp.position_raw or rp.position_long or "").strip()
                  for cp, rp in zip(cur_players, current_roster.players)}
        unpositioned_newcomers = sum(1 for cp in cur_players if id(cp) not in seen_current and not pos_of.get(id(cp)))
    else:
        for p in players:
            p.status = FINAL_YEAR if p.class_year in FINAL_YEAR_CLASSES else RETURNING

    return TeamInput(
        school_slug=school_slug,
        school_name=school_name,
        division=division,
        conference=conference,
        stats_season=stats.season_label,
        roster_season=current_roster.season_label or stats.season_label,
        basis="observed" if observed else "class_year_projection",
        players=players,
        stats_rows_total=total,
        stats_rows_matched=matched,
        unmatched_stats=unmatched,
        roster_fetched_at=current_roster.source.fetched_at,
        stats_fetched_at=stats.source.fetched_at,
        roster_tier=current_roster.source.tier,
        stats_tier=stats.source.tier,
        source_urls={"roster": current_roster.source.url, "stats": stats.source.url,
                     **({"previous_roster": stats_season_roster.source.url} if stats_season_roster else {})},
        warnings=warnings,
        roster_incomplete=bool(incomplete_why),
        incoming_known=incoming_known,
        unpositioned_newcomers=unpositioned_newcomers,
    )
