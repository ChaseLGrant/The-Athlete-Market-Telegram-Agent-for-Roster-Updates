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


# Where the reps happen, in coaching language ("reps behind the plate"). Keyed by baseball/softball group,
# or by the singular noun for the other sports; anything else falls back to "at <position>".
SPOT = {
    "C": "behind the plate", "INF": "in the infield", "MIF": "up the middle", "CIF": "at the corners",
    "OF": "in the outfield", "RHP": "among the right-handed arms", "LHP": "among the left-handed arms",
    "guard": "in the backcourt", "forward": "at forward", "center": "at center",
    "goalkeeper": "in goal", "defender": "on the back line", "midfielder": "in the midfield",
    "quarterback": "under center", "running back": "in the backfield", "wide receiver": "at receiver",
    "tight end": "at tight end", "offensive lineman": "on the offensive line",
    "defensive lineman": "on the defensive line", "linebacker": "at linebacker", "defensive back": "in the secondary",
    "kicker": "at kicker", "punter": "at punter",
}
HEADER = "📋 <b>TAM SCOUTING REPORT</b>"


def _behind_them(n: int, singular: str, plural: str, exp: int, season: str) -> str:
    """The non-senior depth behind the group that may leave (projection: we never say they 'return')."""
    if n == 0:
        return f"• No other {plural} listed behind them"
    if n == 1:
        return f"• 1 other {singular} listed, {'with' if exp else 'without'} significant {season} experience"
    return f"• {n} other {plural} listed, {exp} with significant {season} experience"


def escape(s: str, quote: bool = False) -> str:
    """Escape text for Telegram HTML. Quotes only need escaping inside attributes (links)."""
    return _html_escape(s, quote=quote)


def pct(x: float | None) -> str:
    return "unknown" if x is None else f"{round(100 * x)}%"


def _division_line(division: str | None, sport_name: str) -> str:
    return f"{(division or 'COLLEGE').upper()} {sport_name.upper()}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _of_them(dep: int, listed: int, what: str) -> str:
    """'2 of them are seniors/grad students' / 'the only one listed is a senior/grad student'."""
    if listed == 1 and dep == 1:
        return f"• That one is {what[0]}"
    return f"• {dep} of them {'is' if dep == 1 else 'are'} {what[0] if dep == 1 else what[1]}"


SENIORS = ("a senior/grad student", "seniors/grad students")
OFF_ROSTER = ("off the current roster", "off the current roster")


def why_line(group: str, components: dict, metrics: dict, target_season: str, noun: str | None = None,
             basis: str = "class_year_projection") -> str:
    """The scout's read, in coaching language. Never says a program needs, wants or is recruiting anyone."""
    spot = SPOT.get(noun or group) or f"at {noun or SINGULAR.get(group, group.lower())}"
    usage = components.get("usage_departing") or 0
    exp_gap = components.get("experience_gap") or 0
    depth_gap = components.get("depth_gap") or 0
    reps = "Innings" if group in PITCHER_GROUPS and noun is None else "Reps"
    if usage >= 0.6 and exp_gap >= 0.99:
        return (f"The bulk of the work {spot} could be walking out the door, with little proven experience left "
                f"on the depth chart. {reps} {spot} may be up for grabs in {target_season}.")
    if usage >= 0.6:
        who = "players no longer on the roster" if basis == "observed" else "players in their final listed year"
        return (f"A big chunk of last season's workload {spot} came from {who}. "
                f"The {target_season} depth chart {spot} could look a lot different.")
    if depth_gap >= 0.5:
        return f"Depth {spot} is thin on paper heading into {target_season}. One to keep on the board."
    return f"Some turnover to track {spot}. Worth a closer look."


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
    one = noun[:-1] if noun.endswith("s") else noun  # PLURAL values all end in "s"
    listed = metrics["roster_count"]
    dep = metrics["departing_count"]
    ret = metrics["returning_count"]
    ret_exp = metrics["returning_experienced_count"]
    observed = basis == "observed"
    who = "They" if dep != 1 else ("That pitcher" if group in PITCHER_GROUPS else "That player")

    lines = _top(division, sport_name, school_name, position_label) + [
        "🔎 <b>THE DEPTH CHART</b>",
        f"• {_count(listed, one, noun)} listed in {stats_season}",
        _of_them(dep, listed, OFF_ROSTER if observed else SENIORS),
        "",
        "📈 <b>WORKLOAD ON THE WAY OUT</b>",
    ]
    if group in PITCHER_GROUPS:
        lines.append(
            f"• {who} threw {pct(metrics.get('ip_departing_share'))} of the innings by listed {noun}"
            + (f" ({metrics.get('ip_departing')} of {metrics.get('ip_total')} IP)" if metrics.get("ip_total") else "")
        )
        if metrics.get("gs_total"):
            lines.append(f"• {who} also made {metrics['gs_departing']} of {metrics['gs_total']} starts")
    else:
        lines.append(
            f"• {who} made {pct(metrics.get('starts_departing_share'))} of the starts by listed "
            f"{noun} ({metrics.get('starts_departing')} of {metrics.get('starts_total')})"
        )
    lines += ["", "🧱 <b>WHO'S BEHIND THEM</b>"]
    if observed:
        lines.append(f"• {ret} of the {listed} {'is' if ret == 1 else 'are'} on the current roster"
                     + (f", {ret_exp} with significant {stats_season} experience" if ret else ""))
    else:
        # projection: we only know they aren't listed as seniors/grads, not that they'll return
        lines.append(_behind_them(ret, one, noun, ret_exp, stats_season))
    if metrics.get("known_incoming_count"):
        n = metrics["known_incoming_count"]
        lines.append(f"• {n} newcomer{'' if n == 1 else 's'} listed at the position")
    lines += ["", "🧠 <b>SCOUT'S TAKE</b>", escape(why_line(group, components, metrics, target_season, basis=basis))]
    return _finish(lines, basis, sources)


def _top(division, sport_name, school_name, position_label) -> list[str]:
    return [
        HEADER,
        "",
        f"<b>{escape(_division_line(division, sport_name))}</b>",
        f"<b>{escape(school_name)}</b>",
        f"<b>Position:</b> {escape(position_label)}",
        "",
    ]


def _finish(lines: list[str], basis: str, sources: list[tuple[str, str]]) -> str:
    if basis != "observed":
        lines += [
            "",
            "<i>Scouting note: class years come from the official roster. Eligibility (redshirts, extra years) "
            "isn't published, so some listed seniors could return.</i>",
        ]
    lines += ["", ROSTER_LABEL, "", DISCLAIMER, "", "📎 <b>Sources</b>"]
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
    lines = _top(division, sport_name, school_name, position_label) + [
        "🔎 <b>THE DEPTH CHART</b>",
        escape(f"• {_count(metrics['roster_count'], sing, plural)} on the {roster_season} roster"),
        _of_them(metrics["departing_count"], metrics["roster_count"], SENIORS),
        "",
        "📈 <b>WORKLOAD ON THE WAY OUT</b>",
        escape(f"• {'They' if metrics['departing_count'] != 1 else 'That player'} recorded {pct(metrics.get('usage_departing_share'))} of the {label} by "
               f"this roster's {plural} in {stats_season} ({_n(metrics.get('usage_departing'))} of "
               f"{_n(metrics.get('usage_total'))})"),
    ]
    if metrics.get("starts_total"):
        lines.append(f"• {'They' if metrics['departing_count'] != 1 else 'That player'} also made "
                     f"{metrics['starts_departing']} of {metrics['starts_total']} starts")
    ret, ret_exp = metrics["returning_count"], metrics["returning_experienced_count"]
    lines += [
        "",
        "🧱 <b>WHO'S BEHIND THEM</b>",
        escape(_behind_them(ret, sing, plural, ret_exp, stats_season)),
        "",
        "🧠 <b>SCOUT'S TAKE</b>",
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
        headline = (f"One {div}program could lose the players who logged "
                    f"~{pct(metrics.get('usage_departing_share'))} of its {sing} {metrics['usage_label']} "
                    f"in {stats_season}.")
    elif group in PITCHER_GROUPS:
        headline = (f"One {div}staff could lose the arms that threw "
                    f"~{pct(metrics.get('ip_departing_share'))} of its {noun}' {stats_season} innings.")
    else:
        headline = (f"One {div}program could lose the players who made "
                    f"~{pct(metrics.get('starts_departing_share'))} of its {sing} starts in {stats_season}.")
    why = ("Those players are already off the current roster."
           if basis == "observed" else "That workload came from seniors/grad students. Depth chart could flip.")
    link = join_link or "[TELEGRAM LINK]"
    from app.content.guardrails import X_MAX, x_length

    for middle in (f"{why}\n\nOur scouts broke down the full depth chart.", why, ""):
        text = (f"📋 COLLEGE {sport_name.upper()} SCOUTING REPORT\n\n{headline}\n\n"
                + (f"{middle}\n\n" if middle else "")
                + f"Full scouting report free in Telegram ↓\n{link}")
        if x_length(text) <= X_MAX:
            return text
    return text


def build_verified_post(*, school_name: str, division: str | None, sport_name: str, position_label: str,
                        summary: str, source_label: str, source_url: str) -> str:
    return "\n".join([
        HEADER, "",
        f"<b>{escape(_division_line(division, sport_name))}</b>",
        f"<b>{escape(school_name)}</b>",
        f"<b>Position:</b> {escape(position_label)}", "",
        escape(summary), "",
        VERIFIED_LABEL, "",
        "📎 <b>Sources</b>",
        f'<a href="{escape(source_url, quote=True)}">{escape(source_label)}</a>',
    ])
