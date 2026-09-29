"""Deterministic post + teaser generation. Every number comes from stored metrics."""
from __future__ import annotations

from html import escape as _html_escape

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


def _not_seniors(n: int, singular: str, plural: str, exp: int, season: str) -> str:
    """'1 other listed catcher is not a senior/grad student and has significant 2026 experience.' /
    '2 other listed catchers are not seniors/grad students, 0 with significant 2026 experience.'"""
    if n == 0:
        return f"0 other listed {plural} are not seniors/grad students."
    if n == 1:
        return (f"1 other listed {singular} is not a senior/grad student and "
                f"{'has' if exp else 'does not have'} significant {season} experience.")
    return f"{n} other listed {plural} are not seniors/grad students, {exp} with significant {season} experience."


def escape(s: str, quote: bool = False) -> str:
    """Escape text for Telegram HTML. Quotes only need escaping inside attributes (links)."""
    return _html_escape(s, quote=quote)


def pct(x: float | None) -> str:
    return "unknown" if x is None else f"{round(100 * x)}%"


def _division_line(division: str | None, sport_name: str) -> str:
    return f"{(division or 'COLLEGE').upper()} {sport_name.upper()}"


def why_line(group: str, components: dict, metrics: dict, target_season: str, noun: str | None = None) -> str:
    noun = noun or SINGULAR.get(group, group.lower())
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
    nouns: tuple[str, str] | None = None,  # (singular, plural) for non-baseball sports
    roster_season: str | None = None,
) -> str:
    if "usage_label" in metrics:  # basketball / soccer / football (app/sports/generic)
        return _build_usage_post(school_name=school_name, division=division, sport_name=sport_name, group=group,
                                 position_label=position_label, stats_season=stats_season,
                                 target_season=target_season, roster_season=roster_season or stats_season,
                                 metrics=metrics, components=components, sources=sources,
                                 nouns=nouns or (position_label.lower(), position_label.lower() + "s"))
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
    if basis == "observed":
        remaining = (f"{ret} of the {listed} listed {noun} {'is' if ret == 1 else 'are'} on the current roster"
                     + (f", {ret_exp} with significant {stats_season} experience." if ret else "."))
    else:
        # projection: we only know they aren't listed as seniors/grads, not that they'll return
        one = noun[:-1] if noun.endswith("s") else noun  # PLURAL values all end in "s"
        remaining = _not_seniors(ret, one, noun, ret_exp, stats_season)
    lines += ["", remaining]
    if metrics.get("known_incoming_count"):
        lines.append(f"{metrics['known_incoming_count']} newcomer(s) are listed at the position.")
    lines += [
        "",
        "📊 <b>WHY WE'RE WATCHING</b>",
        "",
        escape(why_line(group, components, metrics, target_season)),
    ]
    return _finish(lines, basis, sources)


def _finish(lines: list[str], basis: str, sources: list[tuple[str, str]]) -> str:
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


def _n(x) -> str:
    """1234.0 -> '1,234'."""
    return "unknown" if x is None else f"{round(x):,}"


def _build_usage_post(*, school_name, division, sport_name, group, position_label, stats_season, target_season,
                      roster_season, metrics, components, sources, nouns) -> str:
    sing, plural = nouns
    label = metrics["usage_label"]
    lines = [
        "🚨 <b>ROSTER WATCH</b>",
        "",
        f"<b>{escape(_division_line(division, sport_name))}</b>",
        f"<b>{escape(school_name)}</b>",
        "",
        f"<b>POSITION:</b> {escape(position_label)}",
        "",
        f"Listed {escape(plural)} ({escape(roster_season)} roster): {metrics['roster_count']}",
        f"Listed as seniors/grad students: {metrics['departing_count']}",
        "",
        escape(f"Those players recorded about {pct(metrics.get('usage_departing_share'))} of the {label} by this "
               f"roster's {plural} in {stats_season} ({_n(metrics.get('usage_departing'))} of "
               f"{_n(metrics.get('usage_total'))})."),
    ]
    if metrics.get("starts_total"):
        lines.append(escape(f"They made {metrics['starts_departing']} of {metrics['starts_total']} starts by this "
                            f"roster's {plural}."))
    ret, ret_exp = metrics["returning_count"], metrics["returning_experienced_count"]
    lines += [
        "",
        escape(_not_seniors(ret, sing, plural, ret_exp, stats_season)),
        "",
        "📊 <b>WHY WE'RE WATCHING</b>",
        "",
        escape(why_line(group, components, metrics, target_season, noun=sing)),
    ]
    return _finish(lines, "class_year_projection", sources)


def build_x_teaser(
    *,
    sport_name: str,
    division: str | None,
    group: str,
    basis: str,
    stats_season: str,
    metrics: dict,
    join_link: str,
    nouns: tuple[str, str] | None = None,
) -> str:
    noun = PLURAL.get(group, group.lower())
    sing = SINGULAR.get(group, group.lower())
    div = f"{division} " if division else ""
    if "usage_label" in metrics:
        sing = (nouns or (group.lower(), ""))[0]
        headline = (f"Today's {div}program could potentially lose players who recorded "
                    f"~{pct(metrics.get('usage_departing_share'))} of its {sing} {metrics['usage_label']} "
                    f"in {stats_season}.")
    elif group in PITCHER_GROUPS:
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
