"""Hard checks run on every post before it is saved as approved AND before it is sent.
If a check fails, publishing is blocked (fail safe)."""
from __future__ import annotations

import re
from dataclasses import dataclass

DISCLAIMER = "Roster analysis only. This is not a confirmed recruiting opening from the coaching staff."
ROSTER_LABEL = "🔵 ROSTER OPPORTUNITY"
VERIFIED_LABEL = "🟢 VERIFIED NEED"

# Claims we never make from inferred data.
BANNED_ALWAYS = [
    r"\bscholarships?\b",
    r"\bguarantee[sd]?\b",
    r"\boffers?\b(?! (?:insight|context))",
    r"\bfull ride\b",
    r"\bnil money\b",
]
BANNED_INFERRED = [
    r"\bneeds? (?:a|an|another|more|to add|to sign)\b",
    r"\bin need of\b",
    r"\bis (?:actively )?recruiting\b",
    r"\bare (?:actively )?recruiting\b",
    r"\blooking for\b",
    r"\bopen (?:roster )?spots?\b",
    r"\broster spots? (?:is |are )?(?:open|available)\b",
    r"\bcoach(?:es)? (?:want|wants|are interested|is interested)\b",
    r"\bwill (?:recruit|sign|offer)\b",
    r"\bconfirmed opening\b(?!\s+from the coaching staff)",
]
ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre", "blockquote"}
TELEGRAM_MAX = 4096
X_MAX = 280


@dataclass
class GuardrailResult:
    ok: bool
    problems: list[str]


def _strip_disclaimer(text: str) -> str:
    return text.replace(DISCLAIMER, "")


def check_telegram(text: str, opportunity_type: str) -> GuardrailResult:
    problems: list[str] = []
    if not text or not text.strip():
        return GuardrailResult(False, ["empty post"])
    if len(text) > TELEGRAM_MAX:
        problems.append(f"too long for Telegram ({len(text)} > {TELEGRAM_MAX})")
    body = _strip_disclaimer(text).lower()
    for pat in BANNED_ALWAYS:
        if re.search(pat, body, re.I):
            problems.append(f"banned phrase: /{pat}/")
    if opportunity_type == "roster_opportunity":
        if DISCLAIMER not in text:
            problems.append("missing required disclaimer")
        if ROSTER_LABEL not in text:
            problems.append("missing 🔵 ROSTER OPPORTUNITY label")
        if "VERIFIED NEED" in text.upper() or "🟢" in text:
            problems.append("inferred opportunity must not be labeled VERIFIED NEED")
        for pat in BANNED_INFERRED:
            if re.search(pat, body, re.I):
                problems.append(f"claim not allowed for inferred data: /{pat}/")
    elif opportunity_type == "verified_need":
        if VERIFIED_LABEL not in text:
            problems.append("missing 🟢 VERIFIED NEED label")
        if "http" not in text:
            problems.append("verified need must link its source")
    else:
        problems.append(f"unknown opportunity type {opportunity_type}")
    problems += _html_problems(text)
    return GuardrailResult(not problems, problems)


def _html_problems(text: str) -> list[str]:
    problems = []
    stack: list[str] = []
    for m in re.finditer(r"<(/?)([a-zA-Z0-9]+)([^>]*)>", text):
        closing, tag = m.group(1) == "/", m.group(2).lower()
        if tag not in ALLOWED_TAGS:
            problems.append(f"HTML tag <{tag}> not supported by Telegram")
            continue
        if closing:
            if not stack or stack[-1] != tag:
                problems.append(f"unbalanced </{tag}>")
            else:
                stack.pop()
        else:
            stack.append(tag)
    if stack:
        problems.append(f"unclosed tags: {stack}")
    stray = re.sub(r"<(/?)([a-zA-Z0-9]+)([^>]*)>", "", text)
    if "<" in stray or ">" in stray:
        problems.append("stray < or > (escape as &lt; &gt;)")
    return problems


def x_length(text: str) -> int:
    """Approximate X weighted length: URLs = 23, emoji / non-Latin chars = 2."""
    t = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(2 if ord(ch) > 0x2FFF else 1 for ch in t)


def check_x(text: str, opportunity_type: str, school_names: list[str] | None = None) -> GuardrailResult:
    problems = []
    if not text.strip():
        problems.append("empty teaser")
    if x_length(text) > X_MAX:
        problems.append(f"too long for X ({x_length(text)} > {X_MAX})")
    low = text.lower()
    for pat in BANNED_ALWAYS + (BANNED_INFERRED if opportunity_type == "roster_opportunity" else []):
        if re.search(pat, low, re.I):
            problems.append(f"banned phrase: /{pat}/")
    for n in school_names or []:
        if n and n.lower() in low:
            problems.append("teaser should not reveal the school")
    return GuardrailResult(not problems, problems)
