"""Deterministic baseball position + class-year normalization."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_MAP = {
    # catchers
    "C": "C", "CATCHER": "C",
    # middle infield
    "SS": "MIF", "SHORTSTOP": "MIF", "2B": "MIF", "SECONDBASE": "MIF", "MIF": "MIF", "MI": "MIF",
    # corner infield
    "1B": "CIF", "FIRSTBASE": "CIF", "3B": "CIF", "THIRDBASE": "CIF", "CIF": "CIF", "CI": "CIF",
    # generic infield
    "INF": "INF", "IF": "INF", "INFIELD": "INF", "INFIELDER": "INF",
    # outfield
    "OF": "OF", "LF": "OF", "CF": "OF", "RF": "OF", "OUTFIELD": "OF", "OUTFIELDER": "OF",
    "LEFTFIELD": "OF", "CENTERFIELD": "OF", "RIGHTFIELD": "OF",
    # utility
    "UT": "UT", "UTL": "UT", "UTIL": "UT", "UTILITY": "UT",
    # designated hitter
    "DH": "DH", "DESIGNATEDHITTER": "DH",
    # pitchers
    "RHP": "RHP", "RIGHTHANDEDPITCHER": "RHP", "LHP": "LHP", "LEFTHANDEDPITCHER": "LHP",
    "P": "P", "PITCHER": "P",
}

PITCH_GROUPS = {"RHP", "LHP", "P"}
INFIELD_GROUPS = {"MIF", "CIF", "INF"}


@dataclass(frozen=True)
class PositionResult:
    primary: str | None          # hitter group or pitcher group
    hitter_group: str | None     # C / MIF / CIF / INF / OF / UT / DH
    pitcher_group: str | None    # RHP / LHP / P (unknown hand)
    is_two_way: bool
    confidence: float            # 0-1, how sure we are about the classification
    tokens: tuple[str, ...]


def _tokens(raw: str) -> list[str]:
    parts = re.split(r"[/,;|&]+|\bor\b", raw, flags=re.I)
    out = []
    for p in parts:
        key = re.sub(r"[^A-Z0-9]", "", p.upper())
        if key:
            out.append(key)
    return out


def classify_position(raw: str | None, throws: str | None = None) -> PositionResult:
    if not raw or not raw.strip():
        return PositionResult(None, None, None, False, 0.0, ())
    toks = _tokens(raw)
    groups = [_TOKEN_MAP.get(t) for t in toks]
    known = [g for g in groups if g]
    if not known:
        return PositionResult(None, None, None, False, 0.0, tuple(toks))

    hitter = next((g for g in known if g not in PITCH_GROUPS), None)
    pitcher = next((g for g in known if g in PITCH_GROUPS), None)
    if pitcher == "P":
        t = (throws or "").upper()
        if t == "R":
            pitcher = "RHP"
        elif t == "L":
            pitcher = "LHP"

    # confidence
    unknown_tokens = len(groups) - len(known)
    if len(known) > 1:
        conf = 0.7
    elif known[0] in ("INF",):
        conf = 0.8
    elif known[0] == "P":
        conf = 0.8 if pitcher in ("RHP", "LHP") else 0.5
    elif known[0] in ("UT", "DH"):
        conf = 0.5
    else:
        conf = 1.0
    if unknown_tokens:
        conf = min(conf, 0.5)

    two_way = hitter is not None and pitcher is not None
    return PositionResult(known[0] if known[0] != "P" else pitcher, hitter, pitcher, two_way, conf, tuple(toks))


# --- class year ------------------------------------------------------------
_CLASS_PATTERNS = [
    (r"\b(GRAD(UATE)?( STUDENT)?|GR|GS|5TH|FIFTH|6TH)\b", "GR"),
    (r"\b(SENIOR|SR)\b", "SR"),
    (r"\b(JUNIOR|JR)\b", "JR"),
    (r"\b(SOPHOMORE|SO|SOPH)\b", "SO"),
    (r"\b(FRESHMAN|FR|FRESHMEN)\b", "FR"),
]


def normalize_class_year(raw: str | None) -> tuple[str, bool | None]:
    """Return (class_year, redshirt). Unknown -> ("UNKNOWN", None). Never guesses."""
    if not raw or not raw.strip():
        return "UNKNOWN", None
    s = raw.upper().replace(".", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    redshirt = bool(re.search(r"\b(REDSHIRT|R|RS)\b", s))
    for pat, val in _CLASS_PATTERNS:
        if re.search(pat, s):
            return val, redshirt
    return "UNKNOWN", None


FINAL_YEAR_CLASSES = {"SR", "GR"}


def parse_bats_throws(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    m = re.match(r"^\s*([RLSB])\s*/\s*([RL])\s*$", raw.upper())
    if not m:
        return None, None
    return m.group(1), m.group(2)
