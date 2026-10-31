"""Men's and women's volleyball: turnover measured by sets played and matches started.

Added 2026-10-30 for Recruiting Insider Plus. NOT live-verified: it can research and be reviewed, but never
posts live until `verify` passes on real schools and live_verified is flipped in registry.py.

Rosters publish OH / OPP (RS) / MB / S / L / DS. Libero and DS are one group (LDS): rosters mix the labels.
Sidearm stats pages split players into "Individual Overall Offensive" and "... Defensive" tables with grouped
headers (ATTACK / SET / SERVE, DIG / RECEPT / BLOCK); columns are read by their final name (K, A, DIG, BLK).
"""
from __future__ import annotations

import re
from functools import partial

from app.sports.base import PositionGroupSpec as P
from app.sports.base import SignalWeights, SportModule
from app.sports.generic import positions as gpos
from app.sports.generic.analyzer import GroupMeasure, make_analyzer
from app.sports.generic.stats import num
from app.sports.generic.team_input import build_team_input

# min_volume = sets played by the whole group last season
POSITIONS = (
    P("OH", "Outside Hitter", "attack", target_depth=5, target_experienced=2, min_volume=150),
    P("OPP", "Opposite / Right Side", "attack", target_depth=3, target_experienced=1, min_volume=60),
    P("MB", "Middle Blocker", "attack", target_depth=4, target_experienced=2, min_volume=150),
    P("S", "Setter", "setter", target_depth=3, target_experienced=1, min_volume=80),
    P("LDS", "Libero / Defensive Specialist", "defense", target_depth=4, target_experienced=2, min_volume=100),
)
TOKENS = {
    "OH": "OH", "OUTSIDE": "OH", "OUTSIDEHITTER": "OH", "LEFTSIDE": "OH", "LS": "OH", "LSH": "OH", "PIN": "OH",
    "OPP": "OPP", "OP": "OPP", "OPPOSITE": "OPP", "OPPOSITEHITTER": "OPP", "RS": "OPP", "RIGHTSIDE": "OPP",
    "RSH": "OPP", "RIGHTSIDEHITTER": "OPP",
    "MB": "MB", "M": "MB", "MH": "MB", "MIDDLE": "MB", "MIDDLEBLOCKER": "MB", "MIDDLEHITTER": "MB",
    "S": "S", "SETTER": "S",
    "L": "LDS", "LIB": "LDS", "LIBERO": "LDS", "DS": "LDS", "DEFENSIVESPECIALIST": "LDS", "DEFENSIVESPE": "LDS",
    "DEFENSIVESPEC": "LDS", "LDS": "LDS",
}
NOUNS = {"OH": ("outside hitter", "outside hitters"), "OPP": ("opposite", "opposites"),
         "MB": ("middle blocker", "middle blockers"), "S": ("setter", "setters"),
         "LDS": ("libero/DS", "liberos/DSs")}
WEIGHTS = SignalWeights(turnover=0.10, usage_departing=0.35, production_departing=0.15, depth_gap=0.20,
                        experience_gap=0.20, incoming_penalty=0.15, transfer_penalty=0.0)
# most specific first; "overall" catches sites with a single individual table
STAT_CAPTIONS = {
    "offense": ("individual overall offensive", "offensive statistics"),
    "defense": ("individual overall defensive", "defensive statistics"),
    "overall": ("individual overall", "individual statistics"),
}


def classify(raw, long=None, throws=None):
    return gpos.classify(TOKENS, raw, long)


def _col(values: dict, *names: str) -> str | None:
    """Value of the column whose name, or last word of a grouped name ('ATTACK K'), matches."""
    norm = {re.sub(r"\s+", " ", k.strip().upper()): v for k, v in values.items()}
    for n in names:
        if n in norm:
            return norm[n]
    for n in names:
        for k, v in norm.items():
            if k.split(" ")[-1] == n:
                return v
    return None


def normalize(kind: str, values: dict) -> dict:
    return {
        "sp": num(_col(values, "SP", "SETS")),
        "mp": num(_col(values, "MP", "M")),
        "ms": num(_col(values, "MS", "GS")),
        "k": num(_col(values, "K", "KILLS")),
        "a": num(_col(values, "A", "AST", "ASSISTS")),
        "dig": num(_col(values, "DIG", "DIGS")),
        "blk": num(_col(values, "BLK", "TB", "BLOCKS")),
    }


def _pick(st, key):
    for kind in ("offense", "overall", "defense"):
        v = (st.get(kind) or {}).get(key)
        if v is not None:
            return v
    return None


def _defense(st, key):
    for kind in ("defense", "overall", "offense"):
        v = (st.get(kind) or {}).get(key)
        if v is not None:
            return v
    return None


def _sum(*vals):
    known = [v for v in vals if v is not None]
    return sum(known) if known else None


def _exp(st):
    return (_pick(st, "sp") or 0) >= 40 or (_pick(st, "ms") or 0) >= 8


def _measure(group: str) -> GroupMeasure:
    prod, label = {
        "OH": (lambda st: _pick(st, "k"), "kills"),
        "OPP": (lambda st: _pick(st, "k"), "kills"),
        "MB": (lambda st: _sum(_pick(st, "k"), _defense(st, "blk")), "kills + blocks"),
        "S": (lambda st: _pick(st, "a"), "assists"),
        "LDS": (lambda st: _defense(st, "dig"), "digs"),
    }[group]
    return GroupMeasure(usage_label="sets played", usage=lambda st: _pick(st, "sp"),
                        starts=lambda st: _pick(st, "ms"), production=prod, production_label=label,
                        experienced=_exp)


MODULE = SportModule(classify=classify, normalize_stats=normalize, nouns=NOUNS,
                     build_team_input=partial(build_team_input, classify=classify, normalize=normalize))
analyze_team = make_analyzer(_measure)
