"""Accuracy fixes from the Recruiting Insider Plus audit (2026-10-30), on synthetic rosters built from the real
CSUSM baseball pages plus small hand-made rosters that reproduce each audited case."""
import copy
from datetime import datetime, timezone

import pytest

from app.collectors.base import RawRoster, RawRosterPlayer, RawStatRow, RawStats, SourceRecord
from app.sports.baseball.team_input import NOT_ON_ROSTER, FINAL_YEAR, RETURNING, build_team_input, roster_check
from app.sports.registry import get_sport

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def _src(kind, season):
    return SourceRecord(url=f"https://example.edu/{kind}/{season}", kind=kind, tier="A", fetched_at=NOW,
                        http_status=200, content_hash="x", title=None, publisher="Example", season_label=season)


def _p(name, pos, cls, jersey, bt="R/R"):
    return RawRosterPlayer(name=name, jersey=str(jersey), position_raw=pos, position_long=None, class_year_raw=cls,
                           bats_throws=bt, height=None, weight=None, hometown=None, high_school=None,
                           previous_school=None, site_player_id=None)


def _roster(players, season):
    return RawRoster(season_label=season, players=players, source=_src("roster", season), warnings=[])


def _stats(rows, season="2026"):
    return RawStats(season_label=season, tables=rows, source=_src("stats", season), warnings=[])


def _bat(name, gs, pa):
    return RawStatRow(name=name, jersey=None, site_player_id=None,
                      values={"GP-GS": f"{gs}-{gs}", "AB": str(pa - 5), "BB": "4", "HBP": "1", "SF": "0", "SH": "0",
                              "TB": str(pa // 2), "H": str(pa // 4), "AVG": ".300"})


def _pit(name, ip, gs=0, app=15):
    return RawStatRow(name=name, jersey=None, site_player_id=None,
                      values={"APP-GS": f"{app}-{gs}", "IP": str(ip), "ERA": "4.00", "SO": "20", "SV": "0",
                              "W-L": "2-2", "BB": "5", "H": "20"})


def _analyze(prev, cur, stats, sport="baseball"):
    cfg = get_sport(sport)
    ti = cfg.module.build_team_input(school_slug="x", school_name="X", division="NCAA D1", conference=None,
                                     current_roster=cur, stats=stats, stats_season_roster=prev)
    return ti, {a.position_group: a for a in cfg.analyzer(ti, cfg, now=NOW)}


def _team(n=36, start=0):
    """A full 2026 roster: 8 infielders (SS/2B/1B/3B), 4 C, 6 OF, 14 RHP, 4 LHP, jerseys 0..n-1."""
    pos = ["SS", "2B", "1B", "3B", "SS", "2B", "1B", "3B", "C", "C", "C", "C", "OF", "OF", "OF", "OF", "OF", "OF"] + \
        ["RHP"] * 14 + ["LHP"] * 4
    cls = ["Sr.", "Jr.", "So.", "Fr."]
    return [_p(f"Player {i}", pos[i], cls[i % 4], start + i) for i in range(n)]


def _stats_for(players):
    bat = [_bat(p.name, 30, 120) for p in players if p.position_raw not in ("RHP", "LHP", "P")]
    pit = [_pit(p.name, 40, 5) for p in players if p.position_raw in ("RHP", "LHP", "P")]
    return _stats({"batting": bat, "pitching": pit})


# (a) partial current roster ------------------------------------------------------------------------------
def test_roster_check_flags_partial_upload():
    prev = _team()
    partial = [p for p in prev if int(p.jersey) >= 10][:18]
    why = roster_check(prev, partial, norm_min=25)
    assert any("vs 36 last season" in w for w in why)
    assert any("no jerseys 0-9" in w for w in why)
    assert roster_check(prev, copy.deepcopy(prev), norm_min=25) == []


def test_partial_roster_projects_from_class_year_instead_of_observed_departures():
    """The Pacific case: a partial 2027 roster used to read as most of the infield gone, at HIGH confidence."""
    prev = _team()
    partial = [copy.deepcopy(p) for p in prev if int(p.jersey) >= 10][:18]
    ti, res = _analyze(_roster(prev, "2026"), _roster(partial, "2027"), _stats_for(prev))
    assert ti.roster_incomplete and ti.basis == "class_year_projection"
    assert not any(p.status == NOT_ON_ROSTER for p in ti.players)
    mif = res["MIF"]
    # only the two senior shortstops (Players 0 and 4) are projected to leave; the 2B/SS juniors+ come back
    assert mif.metrics["departing_count"] == 2 and mif.metrics["roster_count"] == 4
    assert mif.metrics["roster_complete"] is False
    assert mif.confidence != "HIGH"
    assert "looks incomplete" in mif.reason


# (b) restocked positions ---------------------------------------------------------------------------------
def test_newcomers_at_the_position_lower_the_signal():
    prev = _team()
    cur = [copy.deepcopy(p) for p in prev if p.position_raw != "C"]  # all four catchers gone
    _, res_empty = _analyze(_roster(prev, "2026"), _roster(cur + [], "2027"), _stats_for(prev))
    restocked = cur + [_p(f"New C {i}", "C", "Fr.", 60 + i) for i in range(4)]
    _, res_full = _analyze(_roster(prev, "2026"), _roster(restocked, "2027"), _stats_for(prev))
    a, b = res_empty["C"], res_full["C"]
    assert a.metrics["departing_count"] == b.metrics["departing_count"] == 4
    assert b.metrics["restock_ratio"] == 1.0 and b.metrics["known_incoming_count"] == 4
    assert b.signal < a.signal * 0.7


# (c) infield split ---------------------------------------------------------------------------------------
def test_infield_split_and_plain_inf_counts_in_both_at_lower_weight():
    players = _team()
    players.append(_p("Plain Inf", "INF", "Sr.", 77))
    ti, res = _analyze(None, _roster(players, "2026"), _stats_for(players))
    assert "MIF" in res and "CIF" in res and "INF" not in res
    for g in ("MIF", "CIF"):
        row = next(r for r in res[g].player_rows if r["name"] == "Plain Inf")
        assert row["weight"] == 0.5 and row["usage_weight"] == 0.5
        assert res[g].metrics["roster_count"] == 4 and res[g].metrics["flex_roster_count"] == 1


def test_school_listing_only_inf_keeps_one_infield_group():
    players = [_p(f"I{i}", "INF", "Jr.", i) for i in range(8)] + [_p("Two Way", "RHP/1B", "So.", 40)]
    _, res = _analyze(None, _roster(players, "2026"), _stats_for(players))
    assert "INF" in res and "MIF" not in res and "CIF" not in res


# (e) P with no hand, UT ----------------------------------------------------------------------------------
def test_staff_without_hands_is_one_pitching_group():
    players = [_p(f"P{i}", "P", "Sr." if i < 4 else "Jr.", i, bt="") for i in range(10)]
    _, res = _analyze(None, _roster(players, "2026"), _stats_for(players))
    assert set(res) == {"P"} and res["P"].metrics["roster_count"] == 10


def test_unknown_hand_minority_and_ut_are_partial_depth_only():
    players = _team() + [_p("No Hand", "P", "Jr.", 80, bt=""), _p("Util", "UT", "So.", 81)]
    _, res = _analyze(None, _roster(players, "2026"), _stats_for(players))
    for g in ("RHP", "LHP"):
        row = next(r for r in res[g].player_rows if r["name"] == "No Hand")
        assert (row["weight"], row["usage_weight"]) == (0.5, 0.0)
    for g in ("MIF", "CIF", "OF"):
        assert any(r["name"] == "Util" and r["usage_weight"] == 0.0 for r in res[g].player_rows)


def test_football_ath_is_placed_by_his_stats():
    from app.sports.football import _ath_group

    assert _ath_group({"receiving": {"yds": 420.0}, "rushing": {"yds": 30.0}}) == "WR"
    assert _ath_group({"defense": {"tackles": 40.0}, "rushing": {"yds": 100.0}}) == "DB"
    assert _ath_group({}) is None


# research-only sports ------------------------------------------------------------------------------------
def test_research_only_sports_research_but_never_post(monkeypatch):
    from app import settings as st

    monkeypatch.setenv("ENABLED_SPORTS", "baseball,softball,mens_basketball,mens_soccer,football")
    monkeypatch.setenv("RESEARCH_ONLY_SPORTS", "womens_basketball,womens_tennis")
    st.get_settings.cache_clear()
    try:
        s = st.get_settings()
        assert s.sport_researched("womens_basketball") and not s.sport_enabled("womens_basketball")
        assert s.sport_researched("baseball") and s.sport_enabled("baseball")
        assert not s.sport_researched("womens_soccer")
        from app.cli import _sports

        assert "womens_tennis" in _sports("all", only_enabled=True, research=True)
        assert "womens_tennis" not in _sports("all", only_enabled=True)  # publish-daily's list
    finally:
        st.get_settings.cache_clear()


def test_daily_jobs_unchanged_without_research_only_variable(monkeypatch):
    from app import settings as st
    from app.cli import _sports

    monkeypatch.setenv("ENABLED_SPORTS", "baseball,softball,mens_basketball,mens_soccer,football")
    monkeypatch.delenv("RESEARCH_ONLY_SPORTS", raising=False)
    st.get_settings.cache_clear()
    try:
        assert _sports("all", only_enabled=True, research=True) == _sports("all", only_enabled=True)
    finally:
        st.get_settings.cache_clear()


# tennis -------------------------------------------------------------------------------------------------
def test_tennis_lineup_spots():
    from app.sports import tennis

    v = {"Overall": "4-14", "Dual": "4-14", "1": "—", "2": "—", "3": "—", "4": "0-1", "5": "1-4", "6": "3-9"}
    n = tennis.normalize("singles", v)
    assert (n["matches"], n["top"], n["wins"]) == (18, 0, 4)
    d = tennis.normalize("doubles", {"Dual": "2-12", "1": "1-1", "2": "0-2", "3": "2-11"})
    assert (d["matches"], d["top"]) == (17, 2)
    assert tennis.classify(None).primary == "SGL"


# sport conference ---------------------------------------------------------------------------------------
def test_sync_conferences_uses_the_sports_directory(db):
    from app.models import School, Team
    from app.pipeline.discover import sync_conferences

    sc = School(slug="howard-university", name="Howard University", conference="Mid-Eastern Athletic Conference")
    db.add(sc)
    db.flush()
    db.add(Team(school_id=sc.id, sport="mens_soccer", adapter="sidearm", base_url="https://hubison.com",
                sport_path="mens-soccer"))
    db.flush()
    recs = [{"nameOfficial": "Howard University", "athleticWebUrl": "hubison.com", "division": 1,
             "conferenceName": "Northeast Conference", "memberOrgAddress": {"state": "DC"}}]
    assert sync_conferences(db, "mens_soccer", records=recs, echo=lambda *_: None) == 1
    t = db.query(Team).one()
    assert t.conference == "Northeast Conference" and sc.conference == "Mid-Eastern Athletic Conference"
