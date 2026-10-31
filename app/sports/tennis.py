"""Men's and women's tennis: turnover in the dual-match lineup, singles and doubles.

Added 2026-10-30 for Recruiting Insider Plus (research + export only; never posts). Checked on real Sidearm
pages (gohofstra.com, woosterathletics.com): the stats page has "Individual Singles Overall Statistics" and
"Individual Doubles Overall Statistics" tables with a row per player and the player's dual-match record at each
lineup spot (columns 1-6 for singles, 1-3 for doubles, cells "W-L" or "—"). Rosters list no positions, so every
player is in both groups:

  SGL  singles lineup: usage = dual singles matches played (sum of the spot records), production = matches at
       #1-#3 singles
  DBL  doubles lineup: usage = dual doubles matches played, production = matches at #1 doubles

Departures are projected from class year (seniors/grads), like the other usage sports. A program whose stats
page has no individual singles table is skipped (ParseError), never guessed.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import partial

from app.sports.base import PositionGroupSpec as P
from app.sports.base import SignalWeights, SportModule, StoredPosition
from app.sports.generic.analyzer import GroupMeasure, _analyze_group
from app.sports.generic.team_input import build_team_input

POSITIONS = (
    P("SGL", "Singles Lineup", "lineup", target_depth=6, target_experienced=4, min_volume=30),
    P("DBL", "Doubles Lineup", "lineup", target_depth=6, target_experienced=4, min_volume=15),
)
NOUNS = {"SGL": ("singles player", "singles players"), "DBL": ("doubles player", "doubles players")}
WEIGHTS = SignalWeights(turnover=0.10, usage_departing=0.35, production_departing=0.15, depth_gap=0.20,
                        experience_gap=0.20, incoming_penalty=0.15, transfer_penalty=0.0)
STAT_CAPTIONS = {
    "singles": ("individual singles overall",),
    "doubles": ("individual doubles overall",),
}
EXPERIENCED_MATCHES = 8


def classify(raw, long=None, throws=None) -> StoredPosition:
    # tennis rosters publish no positions: everyone can play singles and doubles
    return StoredPosition("SGL", "DBL", 1.0, False)


def _wl(v: str | None) -> tuple[int, int] | None:
    """'4-14' -> (4, 14); '—' / '' -> (0, 0) (didn't play that spot); anything else -> None (unreadable)."""
    if v is None:
        return None
    v = v.strip()
    if v in ("", "—", "-", "–", "--"):
        return 0, 0
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", v)
    return (int(m.group(1)), int(m.group(2))) if m else None


def normalize(kind: str, values: dict) -> dict:
    spots = range(1, 7) if kind == "singles" else range(1, 4)
    by_spot = {}
    for n in spots:
        if str(n) in values:
            by_spot[n] = _wl(values.get(str(n)))
    readable = [x for x in by_spot.values() if x is not None]
    dual = _wl(values.get("Dual"))
    matches = sum(w + l for w, l in readable) if readable and len(readable) == len(by_spot) else None
    if matches is None and dual is not None:
        matches = dual[0] + dual[1]
    top_n = 3 if kind == "singles" else 1
    top = (sum(w + l for s, (w, l) in ((s, x) for s, x in by_spot.items() if x is not None) if s <= top_n)
           if readable and len(readable) == len(by_spot) else None)
    return {"matches": float(matches) if matches is not None else None,
            "top": float(top) if top is not None else None,
            "wins": float(sum(w for w, _ in readable)) if readable and len(readable) == len(by_spot) else None}


def _v(kind: str, key: str):
    return lambda st: (st.get(kind) or {}).get(key)


MEASURES = {
    "SGL": GroupMeasure(usage_label="dual-match singles matches", usage=_v("singles", "matches"),
                        experienced=lambda st: (_v("singles", "matches")(st) or 0) >= EXPERIENCED_MATCHES,
                        production=_v("singles", "top"), production_label="matches at #1-#3 singles"),
    "DBL": GroupMeasure(usage_label="dual-match doubles matches", usage=_v("doubles", "matches"),
                        experienced=lambda st: (_v("doubles", "matches")(st) or 0) >= EXPERIENCED_MATCHES,
                        production=_v("doubles", "top"), production_label="matches at #1 doubles"),
}


def analyze_team(team, cfg, now: datetime | None = None):
    """Every rostered player belongs to both lineup groups."""
    now = now or datetime.now(timezone.utc)
    if not team.players:
        return []
    return [_analyze_group(team, spec, list(team.players), MEASURES[spec.key], cfg, now) for spec in cfg.positions]


MODULE = SportModule(classify=classify, normalize_stats=normalize, nouns=NOUNS,
                     build_team_input=partial(build_team_input, classify=classify, normalize=normalize))
