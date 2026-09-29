"""Softball, basketball, soccer and football: seasons, positions, parsing, analysis, posts.

Uses SYNTHETIC Sidearm-style pages (tests/sidearm_html.py) for a made-up school; real-page
fixtures for these sports get added once `python -m app.cli verify --save-pages` has run."""
from datetime import date

import pytest
from sqlalchemy import select

from app.collectors import registry as creg
from app.content.guardrails import check_telegram, check_x, school_names
from app.models import Opportunity
from app.pipeline.research import research_team
from app.sports import basketball, football, soccer
from app.sports.seasons import label_for, latest_completed_season, next_season, start_year
from tests.sidearm_html import add_program, adapter, roster_html, stat_table, stats_html


# ---------------------------------------------------------------- seasons
@pytest.mark.parametrize("style,today,expected", [
    ("spring", date(2026, 9, 28), "2026"), ("spring", date(2026, 3, 1), "2025"),
    ("fall", date(2026, 9, 28), "2025"), ("fall", date(2027, 1, 5), "2026"),
    ("winter", date(2026, 9, 28), "2025-26"), ("winter", date(2026, 2, 1), "2024-25"),
])
def test_latest_completed_season(style, today, expected):
    assert latest_completed_season(style, today) == expected


def test_season_labels():
    assert label_for("winter", 2025) == "2025-26" and label_for("winter", 2099) == "2099-00"
    assert next_season("2026-27", "winter") == "2027-28" and next_season("2025", "fall") == "2026"
    assert start_year("2025-26") == 2025 and start_year("unknown") is None


# ---------------------------------------------------------------- positions
@pytest.mark.parametrize("mod,raw,primary,secondary,conf", [
    (basketball, "G", "G", None, 1.0), (basketball, "Guard/Forward", "G", "F", 0.7),
    (basketball, "PG", "G", None, 1.0), (basketball, "F/C", "F", "C", 0.7), (basketball, "Wing", None, None, 0.0),
    (soccer, "GK", "GK", None, 1.0), (soccer, "D/M", "D", "M", 0.7), (soccer, "Defender", "D", None, 1.0),
    (football, "OL", "OL", None, 1.0), (football, "DE", "DL", None, 1.0), (football, "Defensive Back", "DB", None, 1.0),
    (football, "QB/ATH", "QB", None, 0.5), (football, "LS", None, None, 0.0),
])
def test_position_classification(mod, raw, primary, secondary, conf):
    p = mod.classify(raw)
    assert (p.primary, p.secondary, p.confidence) == (primary, secondary, conf)


def test_basketball_per_game_minutes_are_not_treated_as_totals():
    assert basketball.normalize("overall", {"GP-GS": "30-30", "MIN": "31.5"})["min"] is None
    assert basketball.normalize("overall", {"GP-GS": "30-30", "MIN": "945"})["min"] == 945


def test_soccer_g_column_means_goals_not_games():
    d = soccer.normalize("field", {"GP": "18", "GS": "17", "MIN": "1,520", "G": "9", "A": "4"})
    assert (d["gp"], d["gs"], d["min"], d["g"], d["a"], d["pts"]) == (18, 17, 1520, 9, 4, 22)


# ---------------------------------------------------------------- basketball end to end
BB_CUR = [("101", "G", 1, "Alex Guard", "Senior"), ("102", "G", 2, "Ben Guard", "Graduate Student"),
          ("103", "G", 3, "Cal Guard", "Sophomore"), ("104", "G", 4, "Dan Guard", "Freshman"),
          ("105", "F", 10, "Eli Forward", "Junior"), ("106", "F/C", 11, "Finn Forward", "Senior"),
          ("107", "C", 20, "Gus Center", "Sophomore")]
BB_PREV = [("101", "G", 1, "Alex Guard", "Junior"), ("102", "G", 2, "Ben Guard", "Senior"),
           ("103", "G", 3, "Cal Guard", "Freshman"), ("105", "F", 10, "Eli Forward", "Sophomore"),
           ("106", "F/C", 11, "Finn Forward", "Junior"), ("107", "C", 20, "Gus Center", "Freshman"),
           ("108", "G", 5, "Hal Gone", "Senior")]
BB_HEAD = ["#", "Player", "GP-GS", "MIN", "PTS", "REB", "AST"]
BB_ROWS = [(1, "Guard, Alex", "30-30", "900", "450", "90", "120"), (2, "Guard, Ben", "30-28", "800", "300", "80", "60"),
           (3, "Guard, Cal", "20-2", "200", "40", "15", "20"), (10, "Forward, Eli", "30-25", "700", "280", "150", "30"),
           (11, "Forward, Finn", "25-5", "300", "90", "70", "10"), (20, "Center, Gus", "28-10", "400", "150", "120", "8"),
           (5, "Gone, Hal", "30-20", "600", "200", "50", "70"), ("", "Totals", "30-30", "6000", "1500", "600", "330")]


def _ids(players):
    return {p[3]: p[0] for p in players}


def _basketball(db):
    team = add_program(db, "mens_basketball", "mens-basketball")
    ids = _ids(BB_PREV)
    creg.set_fixture_adapter(adapter(
        "mens_basketball", "mens-basketball",
        current=("2026-27", roster_html("2026-27 Men's Basketball Roster - Example State", BB_CUR)),
        previous=("2025-26", roster_html("2025-26 Men's Basketball Roster - Example State", BB_PREV)),
        stats=("2025-26", stats_html("2025-26 Men's Basketball Statistics - Example State",
                                     [stat_table("Individual Overall Statistics", BB_HEAD, BB_ROWS, ids)]))))
    return team


def test_basketball_guard_turnover(db, now):
    team = _basketball(db)
    res = research_team(db, team, now=now)
    db.commit()
    assert res.ok, res.message
    by = {a.position_group: a for a in res.analyses}
    g = by["G"]
    m = g.metrics
    # current-roster guards: Alex (SR) 900 + Ben (GR) 800 depart; Cal 200; Dan is new (no stats)
    assert (m["roster_count"], m["departing_count"], m["returning_count"]) == (4, 2, 2)
    assert (m["usage_departing"], m["usage_total"]) == (1700, 1900)
    assert (m["starts_departing"], m["starts_total"]) == (58, 60)
    assert m["already_departed_team_count"] == 1  # Hal left after 2025-26: not upcoming turnover
    assert m["returning_experienced_count"] == 0
    assert g.target_season == "2027-28" and g.stats_season == "2025-26" and g.roster_season == "2026-27"
    assert g.basis == "class_year_projection" and g.confidence == "MEDIUM" and g.passes_gates
    assert "F" in by and "C" in by and by["C"].metrics["departing_count"] == 0

    o = db.scalar(select(Opportunity).where(Opportunity.position_group == "G"))
    t = o.telegram_text
    assert "NCAA D2 MEN'S BASKETBALL" in t
    assert "• 4 guards on the 2026-27 roster\n• 2 of them are seniors/grad students" in t
    assert "• They recorded 89% of the minutes by this roster's guards in 2025-26 (1,700 of 1,900)" in t
    assert "• They also made 58 of 60 starts" in t
    assert "• 2 other guards listed, 0 with significant 2025-26 experience" in t
    assert "in the backcourt" in t
    assert check_telegram(t, "roster_opportunity").ok
    assert "~89% of its guard minutes in 2025-26" in o.x_teaser
    assert check_x(o.x_teaser, "roster_opportunity", school_names(o.school)).ok
    assert {s.url for s in o.sources} >= {"https://example.edu/sports/mens-basketball/stats/2025-26"}


# ---------------------------------------------------------------- soccer
SOC = [("201", "GK", 0, "Ada Keeper", "Senior"), ("202", "GK", 1, "Bea Keeper", "Freshman"),
       ("203", "D", 4, "Cy Back", "Senior"), ("204", "D", 5, "Di Back", "Junior"),
       ("205", "M", 8, "Ed Mid", "Sophomore"), ("206", "F", 9, "Flo Striker", "Senior")]
SOC_FIELD = ["#", "Player", "GP", "GS", "MIN", "G", "A", "PTS"]
SOC_GK = ["#", "Player", "GP", "GS", "MIN", "GA", "SV"]


def test_soccer_goalkeeper_and_field_tables(db, now):
    team = add_program(db, "womens_soccer", "womens-soccer")
    ids = _ids(SOC)
    stats = stats_html("2025 Women's Soccer Statistics - Example State", [
        stat_table("Individual Overall Field Players", SOC_FIELD, [
            (4, "Back, Cy", "18", "18", "1600", "1", "2", "4"), (5, "Back, Di", "17", "10", "1000", "0", "1", "1"),
            (8, "Mid, Ed", "18", "16", "1400", "3", "6", "12"), (9, "Striker, Flo", "18", "18", "1500", "12", "3", "27")],
            ids),
        stat_table("Individual Overall Goalkeeping", SOC_GK, [
            (0, "Keeper, Ada", "17", "17", "1530", "15", "70"), (1, "Keeper, Bea", "2", "1", "90", "2", "5")], ids),
    ])
    creg.set_fixture_adapter(adapter("womens_soccer", "womens-soccer",
                                     current=("2025", roster_html("2025 Women's Soccer Roster", SOC)),
                                     stats=("2025", stats)))
    res = research_team(db, team, now=now)
    assert res.ok, res.message
    by = {a.position_group: a for a in res.analyses}
    gk = by["GK"].metrics
    assert (gk["usage_departing"], gk["usage_total"]) == (1530, 1620)  # goalkeeping-table minutes
    assert by["GK"].target_season == "2026"  # roster = stats season (2025): next season is 2026
    assert by["F"].metrics["production_departing_share"] == 1.0
    assert by["M"].metrics["departing_count"] == 0 and not by["M"].passes_gates


# ---------------------------------------------------------------- football
FB = [("301", "QB", 7, "Quinn Arm", "Senior"), ("302", "QB", 12, "Rex Backup", "Sophomore"),
      ("303", "OL", 70, "Otto Line", "Senior"), ("304", "RB", 22, "Ray Run", "Junior")]


def test_football_measures_each_group_by_its_own_stat(db, now):
    team = add_program(db, "football", "football")
    ids = _ids(FB)
    stats = stats_html("2025 Football Statistics - Example State", [
        stat_table("Passing", ["#", "Player", "GP", "CMP-ATT-INT", "YDS", "TD"],
                   [(7, "Arm, Quinn", "11", "200-320-8", "2,600", "22"), (12, "Backup, Rex", "4", "20-35-1", "210", "1")],
                   ids),
        stat_table("Rushing", ["#", "Player", "GP", "ATT", "YDS", "TD"],
                   [(22, "Run, Ray", "11", "180", "900", "9"), (7, "Arm, Quinn", "11", "40", "120", "2")], ids),
    ])
    creg.set_fixture_adapter(adapter("football", "football",
                                     current=("2025", roster_html("2025 Football Roster", FB)), stats=("2025", stats)))
    res = research_team(db, team, now=now)
    assert res.ok, res.message
    by = {a.position_group: a for a in res.analyses}
    qb = by["QB"].metrics
    assert (qb["usage_label"], qb["usage_departing"], qb["usage_total"]) == ("passing yards", 2600, 2810)
    assert qb["starts_total"] is None  # football pages don't give starts: unknown, not 0
    assert by["RB"].metrics["usage_total"] == 900  # QB's rushing yards don't count for RBs
    assert not by["OL"].passes_gates  # no individual OL stats: never posted on a guess


# ---------------------------------------------------------------- softball (same structure as baseball)
SB = [("401", "C", 2, "Cam Catch", "Senior"), ("402", "C", 12, "Cori Catch", "Freshman"),
      ("403", "RHP", 21, "Pia Pitch", "Graduate Student"), ("404", "SS", 6, "Sam Short", "Junior")]
SB_BAT = ["#", "Player", "AVG", "GP-GS", "AB", "TB", "BB", "HBP", "SF", "SH"]
SB_PIT = ["#", "Player", "ERA", "APP-GS", "IP", "SO"]


def test_softball_uses_the_diamond_analyzer(db, now):
    team = add_program(db, "softball", "softball")
    ids = _ids(SB)
    stats = stats_html("2026 Softball Cumulative Statistics - Example State", [
        stat_table("Individual Overall Batting Statistics", SB_BAT, [
            (2, "Catch, Cam", ".310", "50-48", "150", "70", "12", "3", "1", "2"),
            (12, "Catch, Cori", ".200", "10-2", "20", "5", "1", "0", "0", "0"),
            (6, "Short, Sam", ".330", "50-50", "160", "80", "10", "2", "1", "1")], ids),
        stat_table("Individual Overall Pitching Statistics", SB_PIT, [(21, "Pitch, Pia", "2.10", "30-25", "180.1", "190")],
                   ids),
    ])
    creg.set_fixture_adapter(adapter("softball", "softball",
                                     current=("2026", roster_html("2026 Softball Roster", SB)), stats=("2026", stats)))
    res = research_team(db, team, now=now)
    assert res.ok, res.message
    c = {a.position_group: a for a in res.analyses}["C"]
    assert (c.metrics["starts_departing"], c.metrics["starts_total"]) == (48, 50)
    assert c.target_season == "2027"
    o = db.scalar(select(Opportunity).where(Opportunity.position_group == "C"))
    assert o is not None and "NCAA D2 SOFTBALL" in o.telegram_text and "(48 of 50)" in o.telegram_text


# ---------------------------------------------------------------- parsing safety
def test_misaligned_stat_table_is_never_guessed(db, now):
    """Grouped headers that don't line up with the cells: rows are skipped, the page fails safely."""
    team = add_program(db, "mens_basketball", "mens-basketball")
    ids = _ids(BB_CUR)
    bad = stat_table("Individual Overall Statistics", ["#", "Player", "GP-GS", "MIN"],
                     [(1, "Guard, Alex", "30-30", "900", "450", "90")], ids)  # 2 extra cells
    creg.set_fixture_adapter(adapter("mens_basketball", "mens-basketball",
                                     current=("2025-26", roster_html("2025-26 Men's Basketball Roster", BB_CUR)),
                                     stats=("2025-26", stats_html("2025-26 Men's Basketball Statistics", [bad]))))
    res = research_team(db, team, now=now)
    assert not res.ok and "parse failed" in res.message
