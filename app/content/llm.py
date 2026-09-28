"""Optional Claude helpers (LLM_ENABLED=true). Used ONLY for classification help
where deterministic rules fail. Never for math, never to add claims.

The answer is constrained with structured outputs to a closed set of labels, so the
model can't return anything else; any failure or refusal just means "unknown" (None)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from app.logging_setup import record_event
from app.settings import get_settings

BaseballGroup = Literal["C", "MIF", "CIF", "INF", "OF", "UT", "RHP", "LHP", "P", "UNKNOWN"]
ALLOWED_BASEBALL = set(BaseballGroup.__args__)  # type: ignore[attr-defined]

SYSTEM = (
    "You classify position strings from official college baseball rosters into one group. "
    "C = catcher; MIF = shortstop/second base; CIF = first/third base; INF = infield, side unknown; "
    "OF = outfield; UT = utility; RHP / LHP = right- or left-handed pitcher; P = pitcher, hand unknown. "
    "Answer UNKNOWN unless the string clearly names a baseball position. Never guess."
)


class _PositionAnswer(BaseModel):
    group: BaseballGroup


@lru_cache(maxsize=512)
def classify_baseball_position(raw: str) -> str | None:
    """Map an unusual roster position string to a baseball group, or None."""
    s = get_settings()
    if not (s.llm_enabled and s.anthropic_api_key) or not raw.strip():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=60.0)
        msg = client.beta.messages.parse(
            model=s.anthropic_model,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Position string: {raw[:80]!r}"}],
            output_format=_PositionAnswer,
            output_config={"effort": "low"},  # a lookup, not a reasoning task
            # if a safety classifier declines, let the API retry on its recommended fallback model
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if msg.stop_reason == "refusal" or msg.parsed_output is None:
            record_event(None, "llm_failed", f"no position answer for {raw!r} (stop_reason={msg.stop_reason})",
                         level="WARNING")
            return None
        group = msg.parsed_output.group
    except Exception as e:  # noqa: BLE001 - LLM failures must never break the pipeline
        record_event(None, "llm_failed", f"position classification failed for {raw!r}: {type(e).__name__}",
                     level="WARNING")
        return None
    if group not in ALLOWED_BASEBALL or group == "UNKNOWN":
        return None
    return group
