"""Men's and women's soccer: turnover measured by minutes and starts.

Rosters publish GK / D / M / F (detailed labels like CB or CDM fold into those)."""
from __future__ import annotations

from functools import partial

from app.sports.base import PositionGroupSpec as P
from app.sports.base import SignalWeights, SportModule
from app.sports.generic import positions as gpos
from app.sports.generic.analyzer import GroupMeasure, make_analyzer
from app.sports.generic.stats import games, get, minutes, num
from app.sports.generic.team_input import build_team_input

POSITIONS = (
    P("GK", "Goalkeeper", "gk", target_depth=3, target_experienced=1, min_volume=450),
    P("D", "Defender", "field", target_depth=7, target_experienced=3, min_volume=900),
    P("M", "Midfielder", "field", target_depth=7, target_experienced=3, min_volume=900),
    P("F", "Forward", "field", target_depth=5, target_experienced=2, min_volume=600),
)
TOKENS = {
    "GK": "GK", "G": "GK", "GOALKEEPER": "GK", "KEEPER": "GK", "GOALIE": "GK",
    "D": "D", "DF": "D", "DEF": "D", "DEFENDER": "D", "DEFENSE": "D", "B": "D", "BACK": "D", "CB": "D",
    "CENTERBACK": "D", "CENTREBACK": "D", "FB": "D", "FULLBACK": "D", "LB": "D", "RB": "D", "WB": "D",
    "OUTSIDEBACK": "D",
    "M": "M", "MF": "M", "MID": "M", "MIDFIELD": "M", "MIDFIELDER": "M", "CM": "M", "DM": "M", "CDM": "M",
    "AM": "M", "CAM": "M", "LM": "M", "RM": "M",
    "F": "F", "FW": "F", "FWD": "F", "FORWARD": "F", "ST": "F", "STRIKER": "F", "W": "F", "WING": "F",
    "WINGER": "F", "CF": "F",
}
NOUNS = {"GK": ("goalkeeper", "goalkeepers"), "D": ("defender", "defenders"), "M": ("midfielder", "midfielders"),
         "F": ("forward", "forwards")}
WEIGHTS = SignalWeights(turnover=0.10, usage_departing=0.35, production_departing=0.10, depth_gap=0.25,
                        experience_gap=0.20, incoming_penalty=0.15, transfer_penalty=0.0)
# most specific first: a goalkeeping table's caption can also contain "individual overall"
STAT_CAPTIONS = {
    "goalkeeping": ("goalkeep", "goalie"),
    "field": ("individual overall", "field players", "individual statistics", "player statistics"),
}


def classify(raw, long=None, throws=None):
    return gpos.classify(TOKENS, raw, long)


def normalize(kind: str, values: dict) -> dict:
    gp, gs = games(values)
    d = {"gp": gp, "gs": gs, "min": minutes(get(values, "MIN", "MINS", "MINUTES"))}
    if kind == "goalkeeping":
        d.update(saves=num(get(values, "SV", "SAVES")), ga=num(get(values, "GA")))
    else:
        g, a = num(get(values, "G", "GOALS")), num(get(values, "A", "AST", "ASSISTS"))
        pts = num(get(values, "PTS", "POINTS"))
        d.update(g=g, a=a, pts=pts if pts is not None else (2 * g + a if g is not None and a is not None else None))
    return d


def _gk(st):
    return st.get("goalkeeping") or st.get("field") or {}


def _f(st):
    return st.get("field") or {}


GK = GroupMeasure(
    usage_label="minutes",
    usage=lambda st: _gk(st).get("min"),
    starts=lambda st: _gk(st).get("gs"),
    experienced=lambda st: (_gk(st).get("min") or 0) >= 450 or (_gk(st).get("gs") or 0) >= 5,
)
FIELD = GroupMeasure(
    usage_label="minutes",
    usage=lambda st: _f(st).get("min"),
    starts=lambda st: _f(st).get("gs"),
    production=lambda st: _f(st).get("pts"),
    production_label="points (2 × goals + assists)",
    experienced=lambda st: (_f(st).get("min") or 0) >= 600 or (_f(st).get("gs") or 0) >= 8,
)

MODULE = SportModule(classify=classify, normalize_stats=normalize, nouns=NOUNS,
                     build_team_input=partial(build_team_input, classify=classify, normalize=normalize))
analyze_team = make_analyzer(lambda group: GK if group == "GK" else FIELD)
