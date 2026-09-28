"""Baseball's hooks for the shared pipeline (also used by softball, which has the same structure)."""
from __future__ import annotations

from app.sports.base import SportModule, StoredPosition
from app.sports.baseball.positions import classify_position
from app.sports.baseball.stats import normalize_batting, normalize_pitching
from app.sports.baseball.team_input import build_team_input

NOUNS = {
    "C": ("catcher", "catchers"), "INF": ("infield", "infielders"), "MIF": ("middle infield", "middle infielders"),
    "CIF": ("corner infield", "corner infielders"), "OF": ("outfield", "outfielders"),
    "RHP": ("right-handed pitcher", "right-handed pitchers"), "LHP": ("left-handed pitcher", "left-handed pitchers"),
}
STAT_CAPTIONS = {
    "batting": ("individual overall batting",),
    "pitching": ("individual overall pitching",),
    "fielding": ("individual overall fielding",),
}


def classify(raw, long=None, throws=None) -> StoredPosition:
    pos = classify_position(raw, throws)
    if pos.primary is None and long:
        pos = classify_position(long, throws)
    secondary = pos.pitcher_group if pos.primary == pos.hitter_group else pos.hitter_group
    return StoredPosition(pos.primary, secondary, pos.confidence, pos.is_two_way)


def normalize(kind: str, values: dict) -> dict:
    if kind == "batting":
        return normalize_batting(values)
    if kind == "pitching":
        return normalize_pitching(values)
    return {}


MODULE = SportModule(classify=classify, normalize_stats=normalize, build_team_input=build_team_input, nouns=NOUNS)
