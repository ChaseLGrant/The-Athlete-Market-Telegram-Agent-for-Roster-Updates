"""Basketball, soccer and football on REAL official pages (captured 2026-09-30 by the "Verify a sport"
workflow, slimmed with scripts/slim_fixture.py). These pin the numbers the live check printed, so any
parser change that alters them fails loudly. Fixes these pages forced (see app/collectors/sidearm.py):
  * basketball "Overall Individual Statistics" has a two-row grouped header ("Minutes" over TOT | AVG)
  * conference-only, game-by-game and team tables are never read as a player's season
  * football rushing yards are published as "Net"
  * a stats row without a player link repeats the name in a hidden mobile <button>: read it once
"""
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.collectors import registry as creg
from app.collectors.fixture import FixtureAdapter
from app.content.guardrails import check_telegram
from app.models import Opportunity
from app.pipeline.research import research_team
from app.pipeline.verify import verify_program
from tests.sidearm_html import add_program

FIX = Path(__file__).parent / "fixtures"


def _entry(sport, slug):
    d = FIX / f"sidearm_{sport}"
    e = json.loads((d / "manifest.json").read_text())[f"{slug}:{sport}"]
    url = e["roster"]["url"]
    return d, e, url.split("/sports/")[0], url.split("/sports/")[1].split("/")[0]


def _report(sport, slug):
    d, e, base, path = _entry(sport, slug)
    row = {"slug": slug, "name": e["school_name"], "base_url": base, "sport_path": path}
    rep = verify_program(row, sport, FixtureAdapter(d), now=datetime.fromisoformat(e["captured_at"]))
    return rep.verdict, "\n".join(rep.lines)


PINNED = {
    ("mens_basketball", "csusm"): ["13/13 (100%)",
                                   "F    listed  7, departing  3; minutes departing 618.0 of 618.0; signal 77.1 MEDIUM"],
    ("mens_basketball", "barry-university"): [
        "F    listed  8, departing  3; minutes departing 632.0 of 855.0; signal 61.6 MEDIUM"],
    ("womens_basketball", "lawrence-university"): [
        "17/17 (100%)", "G    listed 16, departing  5; minutes departing 2386.0 of 2898.0; signal 64.1 MEDIUM"],
    ("womens_basketball", "csusm"): [
        "G    listed  9, departing  2; minutes departing 827.0 of 2206.0; signal 24.6 MEDIUM"],
    ("mens_soccer", "west-texas-a-m-university"): [
        "GK   listed  4, departing  3; minutes departing 1530.0 of 1530.0; signal 78.0 MEDIUM",
        "M    listed 11, departing  4; minutes departing 1133.0 of 1133.0; signal 67.6 MEDIUM"],
    ("mens_soccer", "csusm"): ["F    listed  4, departing  3; minutes departing 2021.0 of 2218.0; signal 88.1 MEDIUM"],
    ("womens_soccer", "georgia-southwestern-state-university"): [
        "GK   listed  3, departing  2; minutes departing 1125.0 of 1125.0; signal 77.2 MEDIUM",
        "D    listed 11, departing  4; minutes departing 4181.0 of 5630.0; signal 48.2 MEDIUM"],
    ("womens_soccer", "johnson-wales-university-charlotte"): [
        "GK   listed  2, departing  1; minutes departing 1035.0 of 1452.7; signal 66.3 MEDIUM"],
    ("football", "eastern-illinois-university"): [
        "RB   listed  7, departing  3; rushing yards departing 711.0 of 711.0; signal 72.9 MEDIUM",
        "LB   listed 10, departing  3; tackles departing 95.0 of 123.0; signal 42.6 MEDIUM"],
    ("football", "hiram-college"): [
        "QB   listed  4, departing  1; passing yards departing 2911.0 of 2911.0; signal 75.8 MEDIUM",
        "DB   listed 14, departing  4; tackles departing 69.0 of 80.0; signal 47.0 MEDIUM"],
    ("football", "keystone-college"): ["rushing yards departing 0.0 of 171.0"],
}


@pytest.mark.parametrize("sport,slug", list(PINNED))
def test_real_pages_pass_with_pinned_numbers(sport, slug):
    verdict, text = _report(sport, slug)
    assert verdict == "PASS", text
    for line in PINNED[(sport, slug)]:
        assert line in text, f"{line!r} not in:\n{text}"


def test_grouped_basketball_header_is_expanded_not_guessed():
    _, text = _report("womens_basketball", "lawrence-university")
    assert "Minutes TOT" in text and "Rebounds TOT" in text and "Scoring PTS" in text


def test_names_without_player_links_are_read_once():
    _, text = _report("football", "keystone-college")
    assert "William, Dashawn #?" in text and "William, Dashawn William" not in text


def test_offensive_line_never_posts():
    _, text = _report("football", "eastern-illinois-university")
    assert "OL   listed 18, departing  4; games played: none found" in text and "not a candidate" in text


@pytest.mark.parametrize("sport,slug,group,snippets", [
    ("mens_soccer", "west-texas-a-m-university", "GK", ["MEN'S SOCCER", "in goal", "(1,530 of 1,530)"]),
    ("football", "hiram-college", "QB", ["FOOTBALL", "under center", "(2,911 of 2,911)"]),
    ("womens_basketball", "lawrence-university", "G", ["WOMEN'S BASKETBALL", "in the backcourt",
                                                        "(2,386 of 2,898)"]),
])
def test_real_post_end_to_end(db, sport, slug, group, snippets):
    d, e, base, path = _entry(sport, slug)
    team = add_program(db, sport, path, slug=slug)
    team.school.name, team.base_url = e["school_name"], base
    db.commit()
    creg.set_fixture_adapter(FixtureAdapter(d))
    res = research_team(db, team, now=datetime.fromisoformat(e["captured_at"]))
    assert res.ok, res.message
    o = db.scalar(select(Opportunity).where(Opportunity.position_group == group))
    for s in snippets:
        assert s in o.telegram_text, (s, o.telegram_text)
    assert "Roster analysis only." in o.telegram_text
    assert check_telegram(o.telegram_text, "roster_opportunity").ok
