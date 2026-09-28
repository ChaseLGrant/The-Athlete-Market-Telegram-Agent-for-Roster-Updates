"""Source adapter interface. Adapters turn a website into raw, un-interpreted rows.

Analyzers never see HTML; adapters never compute opportunities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class SourceUnavailable(Exception):
    """Raised when a source can't be accessed legitimately (robots, 403, 429,
    bot challenge, 404...). The pipeline records it and moves on."""

    def __init__(self, url: str, reason: str, http_status: int | None = None):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason
        self.http_status = http_status


class ParseError(Exception):
    """The page was fetched but didn't have the structure we expect."""


@dataclass(frozen=True)
class TeamRef:
    sport: str
    school_slug: str
    school_name: str
    base_url: str          # https://csusmcougars.com
    sport_path: str        # baseball


@dataclass
class SourceRecord:
    url: str
    kind: str              # roster | stats
    tier: str              # A | B | C
    fetched_at: datetime
    http_status: int | None
    content_hash: str | None
    title: str | None = None
    publisher: str | None = None
    season_label: str | None = None
    from_cache: bool = False


@dataclass
class RawRosterPlayer:
    name: str
    site_player_id: str | None = None
    jersey: str | None = None
    position_raw: str | None = None
    position_long: str | None = None
    class_year_raw: str | None = None
    height: str | None = None
    weight: str | None = None
    bats_throws: str | None = None
    hometown: str | None = None
    high_school: str | None = None
    previous_school: str | None = None
    profile_url: str | None = None


@dataclass
class RawRoster:
    season_label: str | None
    players: list[RawRosterPlayer]
    source: SourceRecord
    warnings: list[str] = field(default_factory=list)


@dataclass
class RawStatRow:
    name: str
    jersey: str | None
    site_player_id: str | None
    values: dict[str, str]  # column header -> raw cell text


@dataclass
class RawStats:
    season_label: str
    tables: dict[str, list[RawStatRow]]  # "batting" | "pitching" | "fielding"
    source: SourceRecord
    warnings: list[str] = field(default_factory=list)


class SourceAdapter(Protocol):
    name: str

    def fetch_roster(self, team: TeamRef, season: str | None = None) -> RawRoster: ...

    def fetch_stats(self, team: TeamRef, season: str) -> RawStats: ...
