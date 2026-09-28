"""Parse raw Sidearm baseball stat cells into numbers. Missing -> None (never 0 by guess)."""
from __future__ import annotations

import re


def _int(v: str | None) -> int | None:
    if v is None:
        return None
    v = v.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", v):
        return None
    return int(v)


def _float(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip()
    if v in ("", "-", "--", "INF", "inf", "∞"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _pair(v: str | None) -> tuple[int | None, int | None]:
    if not v or "-" not in v:
        return None, None
    a, b = v.split("-", 1)
    return _int(a), _int(b)


def ip_to_outs(v: str | None) -> int | None:
    """'61.1' -> 184 outs. Baseball notation: .1 = one out, .2 = two outs."""
    if v is None:
        return None
    m = re.fullmatch(r"\s*(\d+)(?:\.(\d))?\s*", v)
    if not m:
        return None
    whole, frac = int(m.group(1)), int(m.group(2) or 0)
    if frac > 2:
        return None
    return whole * 3 + frac


def outs_to_ip(outs: int) -> str:
    return f"{outs // 3}.{outs % 3}"


def _get(values: dict[str, str], *names: str) -> str | None:
    lower = {k.strip().lower(): v for k, v in values.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def normalize_batting(values: dict[str, str]) -> dict:
    gp, gs = _pair(_get(values, "GP-GS"))
    if gp is None:
        gp, gs = _int(_get(values, "GP", "G")), _int(_get(values, "GS"))
    sb, sb_att = _pair(_get(values, "SB-ATT"))
    d = {
        "gp": gp, "gs": gs,
        "ab": _int(_get(values, "AB")), "r": _int(_get(values, "R")), "h": _int(_get(values, "H")),
        "doubles": _int(_get(values, "2B")), "triples": _int(_get(values, "3B")), "hr": _int(_get(values, "HR")),
        "rbi": _int(_get(values, "RBI")), "tb": _int(_get(values, "TB")), "bb": _int(_get(values, "BB")),
        "hbp": _int(_get(values, "HBP")), "so": _int(_get(values, "SO", "K")), "sf": _int(_get(values, "SF")),
        "sh": _int(_get(values, "SH")), "sb": sb if sb is not None else _int(_get(values, "SB")), "sb_att": sb_att,
        "avg": _float(_get(values, "AVG")), "obp": _float(_get(values, "OB%", "OBP")),
        "slg": _float(_get(values, "SLG%", "SLG")), "ops": _float(_get(values, "OPS")),
    }
    pa_parts = [d["ab"], d["bb"], d["hbp"], d["sf"], d["sh"]]
    d["pa"] = _int(_get(values, "PA"))
    if d["pa"] is None and all(x is not None for x in pa_parts):
        d["pa"] = sum(pa_parts)  # type: ignore[arg-type]
    prod_parts = [d["tb"], d["bb"], d["hbp"]]
    d["production"] = sum(prod_parts) if all(x is not None for x in prod_parts) else None  # type: ignore[arg-type]
    return d


def normalize_pitching(values: dict[str, str]) -> dict:
    app, gs = _pair(_get(values, "APP-GS"))
    if app is None:
        app, gs = _int(_get(values, "APP", "G")), _int(_get(values, "GS"))
    w, l = _pair(_get(values, "W-L"))
    ip_raw = _get(values, "IP")
    outs = ip_to_outs(ip_raw)
    return {
        "app": app, "gs": gs, "w": w, "l": l,
        "sv": _int(_get(values, "SV")), "ip": ip_raw, "outs": outs,
        "era": _float(_get(values, "ERA")), "whip": _float(_get(values, "WHIP")),
        "h": _int(_get(values, "H")), "er": _int(_get(values, "ER")), "bb": _int(_get(values, "BB")),
        "so": _int(_get(values, "SO", "K")),
    }
