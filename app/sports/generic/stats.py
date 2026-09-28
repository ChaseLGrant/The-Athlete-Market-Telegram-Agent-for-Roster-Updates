"""Turn raw stat cells into numbers. Missing or unreadable -> None, never 0 by guess."""
from __future__ import annotations

import re


def num(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", v):
        return None
    return float(v)


def pair(v: str | None) -> tuple[float | None, float | None]:
    """'31-28' -> (31, 28). Used for GP-GS style columns."""
    if not v or "-" not in v:
        return None, None
    a, b = v.split("-", 1)
    return num(a), num(b)


def get(values: dict[str, str], *names: str) -> str | None:
    lower = {re.sub(r"\s+", " ", k.strip().lower()): v for k, v in values.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def lead(v: str | None) -> float | None:
    """First number of a combined cell: '8.5-35' (TFL-yards) -> 8.5, '12' -> 12."""
    if v is None:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)", v.replace(",", ""))
    return float(m.group(1)) if m else None


def games(values: dict[str, str]) -> tuple[float | None, float | None]:
    """(games played, games started) from GP-GS, or separate GP / GS columns.
    A bare "G" column is NOT read as games: in soccer it means goals."""
    gp, gs = pair(get(values, "GP-GS", "GP-S", "G-GS"))
    if gp is None:
        gp, gs = num(get(values, "GP", "GAMES")), num(get(values, "GS", "STARTS"))
    return gp, gs


def minutes(v: str | None) -> float | None:
    """'1,234' or '1234' or '812:30' (mm:ss) -> minutes."""
    if v is None:
        return None
    v = v.strip().replace(",", "")
    m = re.fullmatch(r"(\d+):([0-5]\d)", v)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    return num(v)
