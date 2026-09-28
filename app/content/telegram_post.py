"""Deterministic post + teaser generation. Every number comes from stored metrics."""
from __future__ import annotations

from html import escape

from app.content.guardrails import DISCLAIMER, ROSTER_LABEL, VERIFIED_LABEL

PLURAL = {
    "C": "catchers", "INF": "infielders", "MIF": "middle infielders", "CIF": "corner infielders",
    "OF": "outfielders", "RHP": "right-handed pitchers", "LHP": "left-handed pitchers",
}
SINGULAR = {
    "C": "catcher", "INF": "infield", "MIF": "middle infield", "CIF": "corner infield",
    "OF": "outfield", "RHP": "right-handed pitcher", "LHP": "left-handed pitcher",
}
PITCHER_GROUPS = {"RHP", "LHP"}


def pct(x: float | None) -> str:
    return "unknown" if x is None else f"{round(100 * x)}%"


def _division_line(division: str | None, sport_name: str) -> str:
    return f"{(division or 'COLLEGE').upper()} {sport_name.upper()}"


def why_line(group: str, components: dict, metrics: dict, target_season: str) -> str:
    noun = SINGULAR.get(group, group.lower())
    usage = components.get("usage_departing") or 0
    exp_gap = components.get("experience_gap") or 0
    depth_gap = components.get("depth_gap") or 0
    if usage >= 0.6 and exp_gap >= 0.99:
        return f"Significant potential turnover at {noun} with limited returning experience."
    if usage >= 0.6:
        return f"A large share of last season's {noun} workload may be turning over."
    if depth_gap >= 0.5:
        return f"Thin listed depth at {noun} heading into {target_season}."
    return f"Notable potential turnover at {noun} that may be worth investigating."


def build_roster_post(
    *,
    school_name: str,
    division: str | None,
    sport_name: str,
    group: str,
    position_label: str,
    basis: str,
    stats_season: str,
    target_season: str,
    metrics: dict,
    components: dict,
    sources: list[tuple[str, str]],  # (label, url)
) -> str:
    noun = PLURAL.get(group, position_label.lower())
    listed = metrics["roster_count"]
    dep = metrics["departing_count"]
    ret = metrics["returning_count"]
    ret_exp = metrics["returning_experienced_count"]
    dep_label = "Not on current roster" if basis == "observed" else "Listed as seniors/grad students"

    lines = [
        "🚨 <b>ROSTER WATCH</b>",
        "",
        f"<b>{escape(_division_line(division, sport_name))}</b>",
        f"<b>{escape(school_name)}</b>",
        "",
        f"<b>POSITION:</b> {escape(position_label)}",
        "",
        f"Listed {noun} ({stats_season}): {listed}",
        f"{dep_label}: {dep}",
        "",
    ]
    if group in PITCHER_GROUPS:
        lines.append(
            f"Those pitchers threw about {pct(metrics.get('ip_departing_share'))} of the innings pitched by "
            f"listed {noun} in {stats_season}"
            + (f" ({metrics.get('ip_departing')} of {metrics.get('ip_total')} IP)." if metrics.get("ip_total") else ".")
        )
        if metrics.get("gs_total"):
            lines.append(f"They made {metrics['gs_departing']} of {metrics['gs_total']} starts by listed {noun}.")
    else:
        lines.append(
            f"Those players accounted for about {pct(metrics.get('starts_departing_share'))} of starts made by "
            f"listed {noun} in {stats_season} ({metrics.get('starts_departing')} of {metrics.get('starts_total')})."
        )
    lines += [
        "",
        f"{ret} listed {noun} remain" + (f", {ret_exp} with significant {stats_season} experience." if ret else "."),
    ]
    if metrics.get("known_incoming_count"):
        lines.append(f"{metrics['known_incoming_count']} newcomer(s) are listed at the position.")
    lines += [
        "",
        "📊 <b>WHY WE'RE WATCHING</b>",
        "",
        escape(why_line(group, components, metrics, target_season)),
    ]
    if basis != "observed":
        lines += [
            "",
            "<i>Class years are from the official roster. Eligibility (redshirts/extra years) isn't published, "
            "so some listed seniors could return.</i>",
        ]
    lines += ["", ROSTER_LABEL, "", DISCLAIMER, "", "Sources:"]
    for label, url in sources:
        lines.append(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>')
    return "\n".join(lines)


def build_x_teaser(
    *,
    sport_name: str,
    division: str | None,
    group: str,
    basis: str,
    stats_season: str,
    metrics: dict,
    join_link: str,
) -> str:
    noun = PLURAL.get(group, group.lower())
    sing = SINGULAR.get(group, group.lower())
    div = f"{division} " if division else ""
    if group in PITCHER_GROUPS:
        headline = (f"Today's {div}program could potentially lose pitchers who threw "
                    f"~{pct(metrics.get('ip_departing_share'))} of its {noun}' {stats_season} innings.")
    else:
        headline = (f"Today's {div}program could potentially lose players who made "
                    f"~{pct(metrics.get('starts_departing_share'))} of its {sing} starts in {stats_season}.")
    why = ("Those players are no longer on the current roster."
           if basis == "observed" else "Most of it came from listed seniors/grad students.")
    link = join_link or "[TELEGRAM LINK]"
    from app.content.guardrails import X_MAX, x_length

    for middle in (f"{why}\n\nWe broke down the program we're watching today.", why, ""):
        text = (f"🚨 COLLEGE {sport_name.upper()} ROSTER WATCH\n\n{headline}\n\n"
                + (f"{middle}\n\n" if middle else "")
                + f"Full school + analysis free in Telegram ↓\n{link}")
        if x_length(text) <= X_MAX:
            return text
    return text


def build_verified_post(*, school_name: str, division: str | None, sport_name: str, position_label: str,
                        summary: str, source_label: str, source_url: str) -> str:
    return "\n".join([
        "🚨 <b>ROSTER WATCH</b>", "",
        f"<b>{escape(_division_line(division, sport_name))}</b>",
        f"<b>{escape(school_name)}</b>", "",
        f"<b>POSITION:</b> {escape(position_label)}", "",
        escape(summary), "",
        VERIFIED_LABEL, "",
        "Sources:",
        f'<a href="{escape(source_url, quote=True)}">{escape(source_label)}</a>',
    ])
