"""Optional Claude helpers (LLM_ENABLED=true). Used ONLY for classification help
where deterministic rules fail. Never for math, never to add claims.
Every output is validated against a closed set; anything else is discarded."""
from __future__ import annotations

import json
from functools import lru_cache

from app.logging_setup import record_event
from app.settings import get_settings

ALLOWED_BASEBALL = {"C", "MIF", "CIF", "INF", "OF", "UT", "RHP", "LHP", "P", "UNKNOWN"}


@lru_cache(maxsize=512)
def classify_baseball_position(raw: str) -> str | None:
    """Map an unusual roster position string to a baseball group, or None."""
    s = get_settings()
    if not (s.llm_enabled and s.anthropic_api_key) or not raw.strip():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        msg = client.messages.create(
            model=s.anthropic_model,
            max_tokens=50,
            system=("You classify college baseball roster position strings. Reply with JSON only: "
                    '{"group": one of ' + json.dumps(sorted(ALLOWED_BASEBALL)) + "}. "
                    "Use UNKNOWN if the string is not clearly a baseball position."),
            messages=[{"role": "user", "content": f"Position string: {raw[:80]!r}"}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        group = json.loads(text.strip().strip("`").removeprefix("json")).get("group")
    except Exception as e:  # noqa: BLE001 - LLM failures must never break the pipeline
        record_event(None, "llm_failed", f"position classification failed for {raw!r}: {type(e).__name__}",
                     level="WARNING")
        return None
    if group not in ALLOWED_BASEBALL or group in ("UNKNOWN", "P"):
        return None
    return group
