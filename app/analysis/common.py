"""Sport-agnostic, deterministic helpers: name matching, signal, data quality,
confidence, fingerprints. No I/O and no LLM here."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from app.sports.base import QualityWeights, SignalWeights

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def name_key(name: str) -> str:
    """'Samayoa, Zech' and 'Zech Samayoa' -> 'zech samayoa'."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.strip()
    if "," in s:
        last, first = s.split(",", 1)
        s = f"{first} {last}"
    s = re.sub(r"[^a-zA-Z\s'-]", " ", s).lower().replace("'", "").replace("-", " ")
    parts = [p for p in s.split() if p not in _SUFFIXES]
    return " ".join(parts)


def last_name(key: str) -> str:
    return key.split()[-1] if key else ""


def share(part: float, total: float) -> float | None:
    """Fraction or None when the denominator is zero (unknown, not 0%)."""
    if not total:
        return None
    return max(0.0, min(1.0, part / total))


def mean_known(*vals: float | None) -> float | None:
    known = [v for v in vals if v is not None]
    return sum(known) / len(known) if known else None


# ------------------------------------------------------------------ signal
@dataclass(frozen=True)
class SignalResult:
    signal: float
    raw: float
    components: dict[str, float | None]


def compute_signal(components: dict[str, float | None], w: SignalWeights, data_quality: float) -> SignalResult:
    """0-100 prioritization score. Unknown components contribute 0 (never assumed)."""
    c = {k: (v if v is not None else 0.0) for k, v in components.items()}
    raw = (
        w.turnover * c.get("turnover", 0)
        + w.usage_departing * c.get("usage_departing", 0)
        + w.production_departing * c.get("production_departing", 0)
        + w.depth_gap * c.get("depth_gap", 0)
        + w.experience_gap * c.get("experience_gap", 0)
        - w.incoming_penalty * c.get("incoming", 0)
        - w.transfer_penalty * c.get("transfers_in", 0)
    )
    multiplier = 0.5 + 0.5 * max(0.0, min(1.0, data_quality))
    signal = max(0.0, min(100.0, 100.0 * raw * multiplier))
    return SignalResult(round(signal, 1), round(raw, 4), components)


# ------------------------------------------------------------------ quality / confidence
TIER_SCORE = {"A": 1.0, "B": 0.8, "C": 0.5}


def recency_score(fetched_at: datetime, now: datetime, season_gap: int) -> float:
    age_days = (now - fetched_at).total_seconds() / 86400
    base = 1.0 if age_days <= 7 else 0.8 if age_days <= 30 else 0.5
    if season_gap not in (0, 1):
        base *= 0.7
    return base


def compute_data_quality(
    *,
    tiers: list[str],
    match_rate: float | None,
    class_known: float | None,
    position_confidence: float | None,
    recency: float,
    basis: str,
    w: QualityWeights,
) -> tuple[float, dict[str, float]]:
    parts = {
        "source_tier": min(TIER_SCORE.get(t, 0.0) for t in tiers) if tiers else 0.0,
        "match_rate": match_rate if match_rate is not None else 0.0,
        "class_known": class_known if class_known is not None else 0.0,
        "position_confidence": position_confidence if position_confidence is not None else 0.0,
        "recency": recency,
        "basis": 1.0 if basis == "observed" else 0.7,
    }
    total = (
        w.source_tier * parts["source_tier"] + w.match_rate * parts["match_rate"]
        + w.class_known * parts["class_known"] + w.position_confidence * parts["position_confidence"]
        + w.recency * parts["recency"] + w.basis * parts["basis"]
    )
    denom = w.source_tier + w.match_rate + w.class_known + w.position_confidence + w.recency + w.basis
    return round(total / denom, 4), {k: round(v, 4) for k, v in parts.items()}


def confidence_label(data_quality: float, match_rate: float | None, basis: str) -> str:
    if data_quality >= 0.90 and (match_rate or 0) >= 0.90 and basis == "observed":
        return "HIGH"
    if data_quality >= 0.70:
        return "MEDIUM"
    return "LOW"


CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


# ------------------------------------------------------------------ fingerprints
def fingerprint(sport: str, school_slug: str, position_group: str, target_season: str, opp_type: str) -> str:
    raw = "|".join(x.strip().lower() for x in (sport, school_slug, position_group, target_season, opp_type))
    return hashlib.sha256(raw.encode()).hexdigest()


def evidence_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
