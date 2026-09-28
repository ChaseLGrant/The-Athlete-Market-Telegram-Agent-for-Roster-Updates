"""Softball on REAL official pages (captured 2026-09-28 by the "Verify a sport" workflow, slimmed with
scripts/slim_fixture.py: scripts/images removed, roster cards and stats tables untouched).

These pin the numbers the live check printed, so any parser change that alters them fails loudly."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.collectors import registry as creg
from app.collectors.fixture import FixtureAdapter
from app.models import Opportunity
from app.pipeline.research import research_team
from app.pipeline.verify import verify_program
from tests.sidearm_html import add_program

DIR = Path(__file__).parent / "fixtures" / "sidearm_softball"
WHEN = datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc)
SCHOOLS = {  # slug -> (name, base url)
    "csusm": ("Cal State San Marcos", "https://csusmcougars.com"),
    "hillsdale-college": ("Hillsdale College", "https://hillsdalechargers.com"),
    "mount-saint-mary-college-new-york": ("Mount Saint Mary College (New York)", "https://msmcknights.com"),
    "greensboro-college": ("Greensboro College", "https://greensborocollegesports.com"),
}


def _report(slug):
    name, base = SCHOOLS[slug]
    row = {"slug": slug, "name": name, "base_url": base, "sport_path": "softball"}
    rep = verify_program(row, "softball", FixtureAdapter(DIR), now=WHEN)
    return rep.verdict, "\n".join(rep.lines)


@pytest.mark.parametrize("slug", list(SCHOOLS))
def test_every_captured_school_passes(slug):
    verdict, text = _report(slug)
    assert verdict == "PASS", text


def test_csusm_softball_numbers():
    _, text = _report("csusm")
    assert "stats rows matched to roster: 26/28 (93%)" in text
    assert "OF   listed  6, departing  1; starts departing 66 of 181" in text
    assert "RHP  listed  4, departing  1; ip departing 156.1 of 469.0" in text


def test_hillsdale_newer_roster_means_observed_departures():
    _, text = _report("hillsdale-college")
    assert "last season's roster" in text and "22/22 (100%)" in text
    assert "OF   listed  4, departing  2; starts departing 104 of 154; signal 55.2 HIGH" in text
    assert "INF  listed  5, departing  2; starts departing 104 of 153; signal 54.4 HIGH" in text


def test_unnamed_stat_lines_are_skipped_not_guessed():
    """msmcknights.com lists two stat lines named only '99' and '1': they belong to nobody."""
    _, text = _report("mount-saint-mary-college-new-york")
    assert "18/18 (100%)" in text and "unmatched" not in text
    assert "RHP  listed  3, departing  2; ip departing 185.2 of 222.0; signal 70.7 MEDIUM" in text


def test_new_roster_without_positions_uses_last_seasons_positions():
    """Greensboro's 2027 roster has no positions yet; the analysis (and the check) use the 2026 roster's."""
    verdict, text = _report("greensboro-college")
    assert verdict == "PASS" and "positions not recognised" not in text
    assert "INF  listed  5, departing  4; starts departing 106 of 107; signal 90.0 HIGH" in text


def test_real_softball_post_end_to_end(db):
    team = add_program(db, "softball", "softball", slug="hillsdale-college")
    team.school.name, team.base_url = "Hillsdale College", "https://hillsdalechargers.com"
    db.commit()
    creg.set_fixture_adapter(FixtureAdapter(DIR))
    res = research_team(db, team, now=WHEN)
    assert res.ok, res.message
    of = db.scalar(select(Opportunity).where(Opportunity.position_group == "OF"))
    assert of.confidence == "HIGH" and of.signal == 55.2
    assert "SOFTBALL" in of.telegram_text and "(104 of 154)" in of.telegram_text
    assert "Roster analysis only." in of.telegram_text
