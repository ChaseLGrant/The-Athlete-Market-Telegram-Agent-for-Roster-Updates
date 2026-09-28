"""Sport-agnostic building blocks. Each sport supplies a SportConfig and an analyzer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class PositionGroupSpec:
    key: str                  # "C"
    label: str                # "Catcher"
    kind: str                 # "hitter" | "pitcher" | "field" | "gk" ...
    target_depth: int         # healthy number of rostered players in this group
    target_experienced: int   # healthy number of experienced returners
    min_volume: float         # min group usage (starts, IP, minutes) to analyze at all


@dataclass(frozen=True)
class SignalWeights:
    """Weights for the 0-100 Opportunity Signal. Positive weights should sum to ~1."""
    turnover: float
    usage_departing: float
    production_departing: float
    depth_gap: float
    experience_gap: float
    incoming_penalty: float
    transfer_penalty: float = 0.0


@dataclass(frozen=True)
class QualityWeights:
    source_tier: float = 0.20
    match_rate: float = 0.20
    class_known: float = 0.15
    position_confidence: float = 0.20
    recency: float = 0.15
    basis: float = 0.10


@dataclass(frozen=True)
class StoredPosition:
    """What gets saved on a roster entry, for any sport."""
    primary: str | None
    secondary: str | None
    confidence: float
    is_two_way: bool = False


@dataclass(frozen=True)
class SportModule:
    """The sport-specific pieces the shared pipeline calls."""
    # (position_raw, position_long, throws) -> StoredPosition
    classify: Callable[[str | None, str | None, str | None], StoredPosition]
    # (table kind, raw column->cell dict) -> parsed numbers (unknown = None)
    normalize_stats: Callable[[str, dict], dict]
    # builds the analyzer's input from raw rosters + stats (see baseball/team_input.py)
    build_team_input: Callable[..., Any]
    # group key -> (singular, plural) used in posts, e.g. "G": ("guard", "guards")
    nouns: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class SportConfig:
    key: str
    display_name: str               # "Baseball"
    channel_title: str              # "The Athlete Market | Baseball"
    positions: tuple[PositionGroupSpec, ...]
    stat_types: tuple[str, ...]     # e.g. ("batting", "pitching")
    key_stats: dict[str, tuple[str, ...]]
    weights: SignalWeights
    quality_weights: QualityWeights = field(default_factory=QualityWeights)
    min_candidate_signal: float = 45.0
    material_signal_change: float = 10.0
    implemented: bool = False
    analyzer: Callable[..., Any] | None = None
    x_hashtag: str = ""
    season_style: str = "spring"    # spring | fall | winter (see app/sports/seasons.py)
    # Sidearm stats tables: kind -> caption fragments that identify it (lower case)
    stat_captions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    module: SportModule | None = None
    # True only after the page parsing has been checked against real live pages for this sport
    # (python -m app.cli verify). Unverified sports can research and be reviewed, but never post live.
    live_verified: bool = False

    def position(self, key: str) -> PositionGroupSpec:
        for p in self.positions:
            if p.key == key:
                return p
        raise KeyError(key)

    def noun(self, group: str, plural: bool = True) -> str:
        pair = (self.module.nouns if self.module else {}).get(group)
        if pair:
            return pair[1] if plural else pair[0]
        label = self.position(group).label.lower() if any(p.key == group for p in self.positions) else group
        return label + ("s" if plural else "")


class TeamAnalyzer(Protocol):
    def __call__(self, team_data: Any, config: SportConfig) -> list[Any]: ...
