"""Discovering programs from the NCAA member directory, and research with pages fetched on worker threads."""
from sqlalchemy import select

from app.models import Opportunity, Team
from app.pipeline import discover as disc
from app.pipeline.research import Prefetched, fetch_team_pages, research_team, run_research

# shape copied from the real directory response (2026-09-28), trimmed to the fields we use
RECORDS = [
    {"orgId": 2, "nameOfficial": "Abilene Christian University", "deactive": "N", "division": 1,
     "conferenceName": "United Athletic Conference ", "athleticWebUrl": "www.acusports.com",
     "memberOrgAddress": {"state": "TX"}},
    {"orgId": 929, "nameOfficial": "Adams State University", "deactive": "N", "division": 2,
     "conferenceName": "Rocky Mountain Athletic Conference", "athleticWebUrl": "www.asugrizzlies.com",
     "memberOrgAddress": {"state": "CO"}},
    {"orgId": 5, "nameOfficial": "California State University San Marcos", "deactive": "N", "division": 2,
     "conferenceName": "CCAA", "athleticWebUrl": "www.csusmcougars.com", "memberOrgAddress": {"state": "CA"}},
    {"orgId": 6, "nameOfficial": "No Website College", "deactive": "N", "division": 3, "athleticWebUrl": None},
    {"orgId": 7, "nameOfficial": "Gone University", "deactive": "Y", "division": 2, "athleticWebUrl": "gone.edu"},
]


def test_candidates_from_directory_records():
    cs = disc.candidates(RECORDS)
    assert [c.name for c in cs] == ["Abilene Christian University", "Adams State University",
                                    "California State University San Marcos"]
    acu = cs[0]
    assert (acu.slug, acu.base_url, acu.division, acu.conference, acu.state) == (
        "abilene-christian-university", "https://www.acusports.com", "NCAA D1", "United Athletic Conference", "TX")
    assert disc.base_url("https://x.edu/sports/") == "https://x.edu" and disc.base_url("nonsense") is None


def test_discover_adds_readable_schools_and_skips_known_ones(db, now, monkeypatch):
    run_research(db, "baseball", now=now)  # CSUSM already known from the CSV (csusmcougars.com)
    checked = []

    def fake_check(c, sport, now):
        checked.append(c.name)
        return (c, "PASS", "ok") if "Abilene" in c.name else (c, "FAIL", "✗ could not read the pages: 404")

    monkeypatch.setattr(disc, "_check", fake_check)
    counts = disc.discover(db, "baseball", records=RECORDS, now=now, echo=lambda *_: None)
    assert counts == {"PASS": 1, "CHECK": 0, "FAIL": 1}
    assert "California State University San Marcos" not in checked  # same site as the CSV's csusm
    teams = {t.school.name: t for t in db.scalars(select(Team).where(Team.sport == "baseball"))}
    assert teams["Abilene Christian University"].active is True
    assert teams["Abilene Christian University"].school.division == "NCAA D1"
    assert teams["Adams State University"].active is False and "404" in teams["Adams State University"].notes
    # a second run doesn't re-check schools it has already seen
    checked.clear()
    disc.discover(db, "baseball", records=RECORDS, now=now, echo=lambda *_: None)
    assert checked == []


def test_research_with_pages_fetched_on_a_worker_thread(db, now):
    from app.collectors import registry as creg

    run_research(db, "baseball", now=now)
    team = db.scalar(select(Team))
    adapter = creg.get_adapter(team.adapter, creg.TeamRef("baseball", "csusm", "Cal State San Marcos",
                                                           team.base_url, "baseball"))
    pages = fetch_team_pages(adapter, creg.TeamRef("baseball", "csusm", "Cal State San Marcos", team.base_url,
                                                   "baseball"), "spring", now.date())
    res = research_team(db, team, now=now, prefetched=Prefetched(pages=pages))
    assert res.ok and db.scalar(select(Opportunity)).signal == 74.8
    from app.collectors.base import SourceUnavailable

    bad = research_team(db, team, now=now, prefetched=Prefetched(
        error=SourceUnavailable(team.base_url, "HTTP 503", 503), failed_kind="stats"))
    assert not bad.ok and "503" in bad.message
