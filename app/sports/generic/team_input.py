"""Roster(s) + stats -> one record per current-roster player, for usage-based sports.

Departures are always *projected from class year* on the current roster (seniors/grads may leave
after this season). When the current roster is newer than the stats season (the normal case in the
off-season), the stats-season roster is used to match stats reliably, and each player's last-season
numbers are carried to the current roster. Players who already left are excluded from the shares:
they aren't part of the upcoming turnover."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.analysis.common import name_key
from app.collectors.base import RawRoster, RawRosterPlayer, RawStats
from app.sports.base import StoredPosition
from app.sports.baseball.positions import FINAL_YEAR_CLASSES, normalize_class_year
from app.sports.baseball.team_input import _Index

RETURNING = "returning"
FINAL_YEAR = "final_year_listed"


@dataclass
class GPlayer:
    key: str
    name: str
    site_player_id: str | None
    jersey: str | None
    position_raw: str | None
    pos: StoredPosition
    class_year_raw: str | None
    class_year: str
    redshirt: bool | None
    status: str = RETURNING
    stats: dict[str, dict] = field(default_factory=dict)  # table kind -> normalized numbers
    match_method: str | None = None


@dataclass
class GTeamInput:
    school_slug: str
    school_name: str
    division: str | None
    conference: str | None
    stats_season: str
    roster_season: str
    basis: str  # always "class_year_projection" for these sports
    players: list[GPlayer]
    stats_rows_total: int
    stats_rows_matched: int
    unmatched_stats: list[str]
    roster_fetched_at: datetime
    stats_fetched_at: datetime
    roster_tier: str
    stats_tier: str
    already_departed: int = 0  # on the stats-season roster but not the current one
    source_urls: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def match_rate(self) -> float | None:
        return (self.stats_rows_matched / self.stats_rows_total) if self.stats_rows_total else None


def _player(rp: RawRosterPlayer, classify: Callable[..., StoredPosition]) -> GPlayer:
    cy, rs = normalize_class_year(rp.class_year_raw)
    return GPlayer(key=rp.site_player_id or name_key(rp.name), name=rp.name, site_player_id=rp.site_player_id,
                   jersey=rp.jersey, position_raw=rp.position_raw, pos=classify(rp.position_raw, rp.position_long, None),
                   class_year_raw=rp.class_year_raw, class_year=cy, redshirt=rs)


def build_team_input(*, school_slug: str, school_name: str, division: str | None, conference: str | None,
                     current_roster: RawRoster, stats: RawStats, stats_season_roster: RawRoster | None = None,
                     classify: Callable[..., StoredPosition], normalize: Callable[[str, dict], dict]) -> GTeamInput:
    current = [_player(rp, classify) for rp in current_roster.players]
    base = [_player(rp, classify) for rp in stats_season_roster.players] if stats_season_roster else current
    idx = _Index(base)  # type: ignore[arg-type]  # same name/site_player_id/jersey attributes

    total = matched = 0
    unmatched: list[str] = []
    for kind, rows in stats.tables.items():
        for row in rows:
            total += 1
            p, method = idx.find(row.name, row.site_player_id, row.jersey)
            if p is None:
                unmatched.append(f"{kind}: {row.name} #{row.jersey or '?'}")
                continue
            matched += 1
            p.match_method = p.match_method or method
            p.stats[kind] = normalize(kind, row.values)

    departed = 0
    if stats_season_roster is not None:
        cur_idx = _Index(current)  # type: ignore[arg-type]
        for bp in base:
            cp, _ = cur_idx.find(bp.name, bp.site_player_id, bp.jersey)
            if cp is None:
                departed += bool(bp.stats)
                continue
            cp.stats, cp.match_method = bp.stats, bp.match_method

    for p in current:
        p.status = FINAL_YEAR if p.class_year in FINAL_YEAR_CLASSES else RETURNING

    return GTeamInput(
        school_slug=school_slug, school_name=school_name, division=division, conference=conference,
        stats_season=stats.season_label, roster_season=current_roster.season_label or stats.season_label,
        basis="class_year_projection", players=current, stats_rows_total=total, stats_rows_matched=matched,
        unmatched_stats=unmatched, roster_fetched_at=current_roster.source.fetched_at,
        stats_fetched_at=stats.source.fetched_at, roster_tier=current_roster.source.tier,
        stats_tier=stats.source.tier, already_departed=departed,
        source_urls={"roster": current_roster.source.url, "stats": stats.source.url,
                     **({"previous_roster": stats_season_roster.source.url} if stats_season_roster else {})},
        warnings=list(current_roster.warnings) + list(stats.warnings),
    )
