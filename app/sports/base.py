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

    def position(self, key: str) -> PositionGroupSpec:
        for p in self.positions:
            if p.key == key:
                return p
        raise KeyError(key)


class TeamAnalyzer(Protocol):
    def __call__(self, team_data: Any, config: SportConfig) -> list[Any]: ...
