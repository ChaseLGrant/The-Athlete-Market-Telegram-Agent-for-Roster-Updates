"""Deterministic roster-position classification from a per-sport token map.

Only groups the roster actually publishes are used (e.g. basketball G/F/C, soccer GK/D/M/F);
we never split a listed "G" into point vs shooting guard."""
from __future__ import annotations

import re

from app.sports.base import StoredPosition


def tokens(raw: str) -> list[str]:
    parts = re.split(r"[/,;|&+]+|\s-\s|(?<=[A-Za-z])-(?=[A-Za-z])|\bor\b|\band\b", raw, flags=re.I)
    out = []
    for p in parts:
        key = re.sub(r"[^A-Z0-9]", "", p.upper())
        if key:
            out.append(key)
    return out


def classify(token_map: dict[str, str], raw: str | None, long: str | None = None) -> StoredPosition:
    """First recognised token is the primary group; a different second group is secondary.
    Confidence: single exact token 1.0, multi-position 0.7, any unrecognised token caps at 0.5."""
    for text in (raw, long):
        if not text or not text.strip():
            continue
        toks = tokens(text)
        groups = [token_map.get(t) for t in toks]
        known = [g for g in groups if g]
        if not known:
            continue
        distinct = list(dict.fromkeys(known))
        conf = 1.0 if len(distinct) == 1 else 0.7
        if len(known) < len(groups):
            conf = min(conf, 0.5)
        return StoredPosition(distinct[0], distinct[1] if len(distinct) > 1 else None, conf, False)
    return StoredPosition(None, None, 0.0, False)
