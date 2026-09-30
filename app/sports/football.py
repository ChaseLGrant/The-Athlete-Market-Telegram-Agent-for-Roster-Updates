"""Football: each position group is measured by the stat that shows its playing time.

  QB passing yards · RB rushing yards · WR/TE receiving yards · DL/LB/DB tackles ·
  K field-goal attempts · P punts

Offensive linemen have no individual stats, so OL is analyzed for depth only and never passes the
volume gate (we don't guess OL playing time). Rosters list many labels (OT, DE, CB, FS...) that fold
into these groups."""
from __future__ import annotations

from functools import partial

from app.sports.base import PositionGroupSpec as P
from app.sports.base import SignalWeights, SportModule
from app.sports.generic import positions as gpos
from app.sports.generic.analyzer import GroupMeasure, make_analyzer
from app.sports.generic.stats import games, get, lead, num, pair
from app.sports.generic.team_input import build_team_input

POSITIONS = (
    P("QB", "Quarterback", "offense", target_depth=4, target_experienced=1, min_volume=500),
    P("RB", "Running Back", "offense", target_depth=4, target_experienced=2, min_volume=300),
    P("WR", "Wide Receiver", "offense", target_depth=8, target_experienced=3, min_volume=400),
    P("TE", "Tight End", "offense", target_depth=4, target_experienced=1, min_volume=100),
    P("OL", "Offensive Line", "offense", target_depth=12, target_experienced=5, min_volume=1),
    P("DL", "Defensive Line", "defense", target_depth=8, target_experienced=3, min_volume=60),
    P("LB", "Linebacker", "defense", target_depth=6, target_experienced=3, min_volume=60),
    P("DB", "Defensive Back", "defense", target_depth=8, target_experienced=4, min_volume=60),
    P("K", "Kicker", "special", target_depth=2, target_experienced=1, min_volume=5),
    P("P", "Punter", "special", target_depth=2, target_experienced=1, min_volume=15),
)
TOKENS = {
    "QB": "QB", "QUARTERBACK": "QB",
    "RB": "RB", "TB": "RB", "HB": "RB", "FB": "RB", "RUNNINGBACK": "RB", "TAILBACK": "RB", "FULLBACK": "RB",
    "WR": "WR", "WIDERECEIVER": "WR", "WIDEOUT": "WR", "SLOT": "WR",
    "TE": "TE", "TIGHTEND": "TE",
    "OL": "OL", "OT": "OL", "OG": "OL", "C": "OL", "T": "OL", "G": "OL", "LT": "OL", "RT": "OL", "LG": "OL",
    "RG": "OL", "OFFENSIVELINE": "OL", "OFFENSIVELINEMAN": "OL", "OFFENSIVETACKLE": "OL", "OFFENSIVEGUARD": "OL",
    "CENTER": "OL",
    "DL": "DL", "DT": "DL", "DE": "DL", "NT": "DL", "NG": "DL", "EDGE": "DL", "DEFENSIVELINE": "DL",
    "DEFENSIVELINEMAN": "DL", "DEFENSIVETACKLE": "DL", "DEFENSIVEEND": "DL", "NOSETACKLE": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB", "WLB": "LB", "SLB": "LB", "LINEBACKER": "LB",
    "DB": "DB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "SAF": "DB", "NICKEL": "DB", "STAR": "DB",
    "SAFETY": "DB", "CORNERBACK": "DB", "CORNER": "DB", "DEFENSIVEBACK": "DB",
    "K": "K", "PK": "K", "KICKER": "K", "PLACEKICKER": "K",
    "P": "P", "PUNTER": "P",
}
NOUNS = {"QB": ("quarterback", "quarterbacks"), "RB": ("running back", "running backs"),
         "WR": ("wide receiver", "wide receivers"), "TE": ("tight end", "tight ends"),
         "OL": ("offensive lineman", "offensive linemen"), "DL": ("defensive lineman", "defensive linemen"),
         "LB": ("linebacker", "linebackers"), "DB": ("defensive back", "defensive backs"),
         "K": ("kicker", "kickers"), "P": ("punter", "punters")}
WEIGHTS = SignalWeights(turnover=0.10, usage_departing=0.35, production_departing=0.15, depth_gap=0.20,
                        experience_gap=0.20, incoming_penalty=0.15, transfer_penalty=0.0)
STAT_CAPTIONS = {
    "passing": ("passing",),
    "rushing": ("rushing",),
    "receiving": ("receiving",),
    "defense": ("defensive leaders", "defensive statistics", "defense", "tackles"),
    "kicking": ("field goals", "place kicking", "placekicking"),
    "punting": ("punting",),
}
EXPERIENCED_GP = 6


def classify(raw, long=None, throws=None):
    return gpos.classify(TOKENS, raw, long)


def normalize(kind: str, values: dict) -> dict:
    gp, gs = games(values)
    d: dict = {"gp": gp, "gs": gs}
    if kind in ("passing", "rushing", "receiving"):
        # rushing tables publish Gain / Loss / Net: "Net" is the rushing yards total (real pages, 2026-09-30)
        d.update(yds=num(get(values, "YDS", "YARDS", "NET", "NET YDS")), td=num(get(values, "TD", "TDS")))
    elif kind == "defense":
        d.update(tackles=num(get(values, "TOT", "TOTAL", "TT", "TKL", "TACKLES")),
                 tfl=lead(get(values, "TFL", "TFL-YDS", "TFL/YDS")),
                 sacks=lead(get(values, "SACKS", "SACK", "SACK-YDS", "SACKS/YDS")))
    elif kind == "kicking":
        fgm, fga = pair(get(values, "FGM-FGA", "FG", "FG-FGA"))
        d.update(fga=fga if fga is not None else num(get(values, "FGA", "ATT")))
    elif kind == "punting":
        d.update(punts=num(get(values, "NO", "PUNTS", "PUNT")))
    return d


def _v(kind, key):
    return lambda st: (st.get(kind) or {}).get(key)


def _gp(st):
    vals = [t.get("gp") for t in st.values() if t.get("gp") is not None]
    return max(vals) if vals else None


def _exp(usage, threshold):
    return lambda st: (_gp(st) or 0) >= EXPERIENCED_GP or (usage(st) or 0) >= threshold


def _def_prod(st):
    d = st.get("defense") or {}
    parts = [d.get("tfl"), d.get("sacks")]
    return sum(parts) if all(x is not None for x in parts) else None


def _measure(label, kind, key, threshold, production=None, production_label=None):
    usage = _v(kind, key)
    return GroupMeasure(usage_label=label, usage=usage, experienced=_exp(usage, threshold),
                        production=production, production_label=production_label)


MEASURES = {
    "QB": _measure("passing yards", "passing", "yds", 500, _v("passing", "td"), "passing touchdowns"),
    "RB": _measure("rushing yards", "rushing", "yds", 300, _v("rushing", "td"), "rushing touchdowns"),
    "WR": _measure("receiving yards", "receiving", "yds", 250, _v("receiving", "td"), "receiving touchdowns"),
    "TE": _measure("receiving yards", "receiving", "yds", 150, _v("receiving", "td"), "receiving touchdowns"),
    "OL": GroupMeasure(usage_label="games played", usage=lambda st: None,
                       experienced=lambda st: (_gp(st) or 0) >= EXPERIENCED_GP),
    "DL": _measure("tackles", "defense", "tackles", 20, _def_prod, "tackles for loss + sacks"),
    "LB": _measure("tackles", "defense", "tackles", 25, _def_prod, "tackles for loss + sacks"),
    "DB": _measure("tackles", "defense", "tackles", 20),
    "K": _measure("field-goal attempts", "kicking", "fga", 5),
    "P": _measure("punts", "punting", "punts", 15),
}

MODULE = SportModule(classify=classify, normalize_stats=normalize, nouns=NOUNS,
                     build_team_input=partial(build_team_input, classify=classify, normalize=normalize))
analyze_team = make_analyzer(lambda group: MEASURES[group])
