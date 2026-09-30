"""Single place that lists every sport the system knows about.

`live_verified` is True only for sports whose page parsing has been checked against real, live
official pages (see `python -m app.cli verify`). The others research and can be reviewed in the
dashboard, but live publishing refuses them until someone verifies and flips the flag here.
"""
from __future__ import annotations

from app.sports import basketball, football, soccer
from app.sports.base import PositionGroupSpec as P
from app.sports.base import SignalWeights, SportConfig
from app.sports.baseball import config as bb
from app.sports.baseball import module as bbmod

SOFTBALL_POSITIONS = (
    P("C", "Catcher", "hitter", target_depth=3, target_experienced=1, min_volume=10),
    P("INF", "Infield", "hitter", target_depth=6, target_experienced=3, min_volume=10),
    P("MIF", "Middle Infield", "hitter", target_depth=3, target_experienced=2, min_volume=10),
    P("CIF", "Corner Infield", "hitter", target_depth=3, target_experienced=2, min_volume=10),
    P("OF", "Outfield", "hitter", target_depth=5, target_experienced=3, min_volume=10),
    P("RHP", "Right-Handed Pitcher", "pitcher", target_depth=4, target_experienced=2, min_volume=30),
    P("LHP", "Left-Handed Pitcher", "pitcher", target_depth=2, target_experienced=1, min_volume=30),
)
SOFTBALL_WEIGHTS = SignalWeights(turnover=0.15, usage_departing=0.30, production_departing=0.20, depth_gap=0.20,
                                 experience_gap=0.15, incoming_penalty=0.15)


def _diamond(key: str, name: str, positions, weights, tag: str, verified: bool) -> SportConfig:
    from app.sports.baseball.analyzer import analyze_team

    return SportConfig(
        key=key, display_name=name, channel_title=f"The Athlete Market | {name}", positions=positions,
        stat_types=("batting", "pitching"),
        key_stats={"batting": ("gp", "gs", "ab", "pa", "avg", "obp", "slg", "ops", "tb", "bb", "hbp"),
                   "pitching": ("app", "gs", "ip", "era", "whip", "so", "sv")},
        weights=weights, quality_weights=bb.QUALITY_WEIGHTS, min_candidate_signal=bb.MIN_CANDIDATE_SIGNAL,
        implemented=True, analyzer=analyze_team, x_hashtag=tag, season_style="spring",
        stat_captions=bbmod.STAT_CAPTIONS, module=bbmod.MODULE, live_verified=verified,
    )


def _usage(key: str, name: str, mod, style: str, tag: str, verified: bool) -> SportConfig:
    return SportConfig(
        key=key, display_name=name, channel_title=f"The Athlete Market | {name}", positions=mod.POSITIONS,
        stat_types=tuple(mod.STAT_CAPTIONS), key_stats={}, weights=mod.WEIGHTS, implemented=True,
        analyzer=mod.analyze_team, x_hashtag=tag, season_style=style, stat_captions=mod.STAT_CAPTIONS,
        module=mod.MODULE, live_verified=verified,
    )


_REGISTRY: dict[str, SportConfig] | None = None


def registry() -> dict[str, SportConfig]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {
            # verified 2026-09-28 on csusmcougars.com (real CSUSM roster + stats)
            "baseball": _diamond("baseball", "Baseball", bb.POSITIONS, bb.WEIGHTS, "#CollegeBaseball", True),
            # verified 2026-09-30 on real schools (see tests/test_other_sports_real.py): football 7/10 PASS,
            # men's soccer 9/10, women's soccer 7/10, men's basketball 9/12, women's basketball 8/12; the rest
            # are D1 sites with the newer Sidearm layout or robots.txt denials, which are skipped safely
            "football": _usage("football", "Football", football, "fall", "#CollegeFootball", True),
            # verified 2026-09-28 on 13 real schools (6 PASS as-is, 2 more after fixes; the rest use page
            # layouts we skip safely); real pages in tests/fixtures/sidearm_softball
            "softball": _diamond("softball", "Softball", SOFTBALL_POSITIONS, SOFTBALL_WEIGHTS, "#CollegeSoftball",
                                 True),
            "mens_basketball": _usage("mens_basketball", "Men's Basketball", basketball, "winter", "#CollegeHoops", True),
            "womens_basketball": _usage("womens_basketball", "Women's Basketball", basketball, "winter", "#WBB", True),
            "mens_soccer": _usage("mens_soccer", "Men's Soccer", soccer, "fall", "#CollegeSoccer", True),
            "womens_soccer": _usage("womens_soccer", "Women's Soccer", soccer, "fall", "#CollegeSoccer", True),
        }
    return _REGISTRY


def get_sport(key: str) -> SportConfig:
    try:
        return registry()[key]
    except KeyError as e:
        raise KeyError(f"Unknown sport '{key}'. Known: {', '.join(registry())}") from e
