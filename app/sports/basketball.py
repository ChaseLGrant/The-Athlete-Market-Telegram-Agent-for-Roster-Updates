"""Men's and women's basketball: turnover measured by minutes and starts.

Rosters publish G / F / C (sometimes PG, SG, SF, PF, which fold into those). Combo strings like
"G/F" count in their first group only, so no player is counted twice.
"""
from __future__ import annotations

from functools import partial

from app.sports.base import PositionGroupSpec as P
from app.sports.base import SignalWeights, SportModule
from app.sports.generic import positions as gpos
from app.sports.generic.analyzer import GroupMeasure, make_analyzer
from app.sports.generic.stats import games, get, minutes, num
from app.sports.generic.team_input import build_team_input

POSITIONS = (
    P("G", "Guard", "court", target_depth=5, target_experienced=2, min_volume=400),
    P("F", "Forward", "court", target_depth=5, target_experienced=2, min_volume=400),
    P("C", "Center", "court", target_depth=2, target_experienced=1, min_volume=200),
)
TOKENS = {
    "G": "G", "GUARD": "G", "PG": "G", "POINTGUARD": "G", "SG": "G", "SHOOTINGGUARD": "G", "COMBOGUARD": "G",
    "F": "F", "FORWARD": "F", "SF": "F", "SMALLFORWARD": "F", "PF": "F", "POWERFORWARD": "F",
    "C": "C", "CENTER": "C", "CENTRE": "C", "POST": "C",
}
NOUNS = {"G": ("guard", "guards"), "F": ("forward", "forwards"), "C": ("center", "centers")}
WEIGHTS = SignalWeights(turnover=0.10, usage_departing=0.40, production_departing=0.15, depth_gap=0.20,
                        experience_gap=0.15, incoming_penalty=0.15, transfer_penalty=0.0)
STAT_CAPTIONS = {"overall": ("individual overall", "individual statistics", "player statistics",
                             "overall statistics")}
EXPERIENCED_MIN, EXPERIENCED_GS = 300, 10


def classify(raw, long=None, throws=None):
    return gpos.classify(TOKENS, raw, long)


def normalize(kind: str, values: dict) -> dict:
    gp, gs = games(values)
    mins = minutes(get(values, "MIN", "MINS", "MP", "TOT MIN"))
    if mins is not None and gp and gp >= 5 and mins <= 48:
        # looks like minutes *per game*, not a season total. Don't multiply it out (that's a guess);
        # at worst this drops a deep-bench player's tiny real total, which barely moves any share.
        mins = None
    pts, reb, ast = num(get(values, "PTS", "TP", "POINTS")), num(get(values, "REB", "TOT", "TOT REB")), \
        num(get(values, "AST", "A"))
    return {"gp": gp, "gs": gs, "min": mins, "pts": pts, "reb": reb, "ast": ast}


def _o(st):
    return st.get("overall") or {}


def _prod(st):
    o = _o(st)
    parts = [o.get("pts"), o.get("reb"), o.get("ast")]
    return sum(parts) if all(x is not None for x in parts) else None


MEASURE = GroupMeasure(
    usage_label="minutes",
    usage=lambda st: _o(st).get("min"),
    starts=lambda st: _o(st).get("gs"),
    production=_prod,
    production_label="points + rebounds + assists",
    experienced=lambda st: (_o(st).get("min") or 0) >= EXPERIENCED_MIN or (_o(st).get("gs") or 0) >= EXPERIENCED_GS,
)

MODULE = SportModule(classify=classify, normalize_stats=normalize, nouns=NOUNS,
                     build_team_input=partial(build_team_input, classify=classify, normalize=normalize))
analyze_team = make_analyzer(lambda group: MEASURE)
