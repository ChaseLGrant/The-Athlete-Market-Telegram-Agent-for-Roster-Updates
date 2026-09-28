"""Single place that lists every sport the system knows about."""
from __future__ import annotations

from app.sports._planned import configs as planned
from app.sports.base import SportConfig
from app.sports.baseball import config as bb


def _baseball() -> SportConfig:
    from app.sports.baseball.analyzer import analyze_team

    return SportConfig(
        key="baseball",
        display_name="Baseball",
        channel_title="The Athlete Market | Baseball",
        positions=bb.POSITIONS,
        stat_types=("batting", "pitching", "fielding"),
        key_stats={
            "batting": ("gp", "gs", "ab", "pa", "avg", "obp", "slg", "ops", "tb", "bb", "hbp"),
            "pitching": ("app", "gs", "ip", "era", "whip", "so", "sv"),
        },
        weights=bb.WEIGHTS,
        quality_weights=bb.QUALITY_WEIGHTS,
        min_candidate_signal=bb.MIN_CANDIDATE_SIGNAL,
        implemented=True,
        analyzer=analyze_team,
        x_hashtag="#CollegeBaseball",
    )


def _planned(key, name, positions, stats, weights, tag) -> SportConfig:
    return SportConfig(
        key=key,
        display_name=name,
        channel_title=f"The Athlete Market | {name}",
        positions=positions,
        stat_types=tuple(stats.keys()),
        key_stats=stats,
        weights=weights,
        implemented=False,
        x_hashtag=tag,
    )


_REGISTRY: dict[str, SportConfig] | None = None


def registry() -> dict[str, SportConfig]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {
            "baseball": _baseball(),
            "football": _planned("football", "Football", planned.FOOTBALL_POSITIONS,
                                 planned.FOOTBALL_KEY_STATS, planned.FOOTBALL_WEIGHTS, "#CollegeFootball"),
            "softball": _planned("softball", "Softball", planned.SOFTBALL_POSITIONS,
                                 planned.SOFTBALL_KEY_STATS, planned.SOFTBALL_WEIGHTS, "#CollegeSoftball"),
            "mens_basketball": _planned("mens_basketball", "Men's Basketball", planned.BASKETBALL_POSITIONS,
                                        planned.BASKETBALL_KEY_STATS, planned.BASKETBALL_WEIGHTS, "#CollegeHoops"),
            "womens_basketball": _planned("womens_basketball", "Women's Basketball", planned.BASKETBALL_POSITIONS,
                                          planned.BASKETBALL_KEY_STATS, planned.BASKETBALL_WEIGHTS, "#WBB"),
            "mens_soccer": _planned("mens_soccer", "Men's Soccer", planned.SOCCER_POSITIONS,
                                    planned.SOCCER_KEY_STATS, planned.SOCCER_WEIGHTS, "#CollegeSoccer"),
            "womens_soccer": _planned("womens_soccer", "Women's Soccer", planned.SOCCER_POSITIONS,
                                      planned.SOCCER_KEY_STATS, planned.SOCCER_WEIGHTS, "#CollegeSoccer"),
        }
    return _REGISTRY


def get_sport(key: str) -> SportConfig:
    try:
        return registry()[key]
    except KeyError as e:
        raise KeyError(f"Unknown sport '{key}'. Known: {', '.join(registry())}") from e
