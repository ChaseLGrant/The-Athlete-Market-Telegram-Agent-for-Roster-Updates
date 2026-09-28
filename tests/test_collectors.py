"""Fetcher politeness + Sidearm parsing (fixtures captured from the real CSUSM site)."""
from datetime import datetime, timezone

import httpx
import pytest

from app.collectors.base import ParseError, SourceUnavailable
from app.collectors.fixture import FixtureAdapter
from app.collectors.http import FetchResult, PoliteFetcher, RobotsPolicy
from app.collectors.sidearm import SidearmAdapter

# The User-agent: * block of https://csusmcougars.com/robots.txt (captured 2026-09-28)
CSUSM_ROBOTS = """User-agent: MJ12bot
Disallow: /

User-agent: *
Disallow: /common/
Disallow: /images/
Disallow: /documents/
Disallow: /admin/
Disallow: /services/
DisAllow: /site/
DisAllow: /hidden/
Disallow: /*.js$
Disallow: /*.css$
Disallow: /*.jpg$
Disallow: /*.gif$
Disallow: /*.axd
Disallow: /*print=true*
Allow: /
Crawl-delay: 30
"""

UA = "TAMRosterIntelBot/0.1 (+https://theathletemarket.com)"


def test_robots_rules_match_real_file():
    p = RobotsPolicy(CSUSM_ROBOTS, UA)
    assert p.crawl_delay == 30
    assert p.allowed("/sports/baseball/roster")
    assert p.allowed("/sports/baseball/stats/2026")
    assert not p.allowed("/services/responsive-roster.ashx")
    assert not p.allowed("/sports/baseball/roster?print=true")
    assert not p.allowed("/scripts/app.js")
    assert p.allowed("/scripts/app.js?v=2")  # $ anchors the end
    assert not RobotsPolicy(CSUSM_ROBOTS, "MJ12bot/1.0").allowed("/sports/baseball/roster")


def _fetcher(handler, tmp_path, sleeps):
    clock = {"t": 0.0}

    def sleep(sec):
        sleeps.append(sec)
        clock["t"] += sec

    return PoliteFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleep,
                         clock=lambda: clock["t"], cache_dir=str(tmp_path / "c"))


def test_fetcher_honors_crawl_delay_robots_and_cache(tmp_path):
    calls, sleeps = [], []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        assert "TAMRosterIntelBot" in req.headers["user-agent"]
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=CSUSM_ROBOTS)
        return httpx.Response(200, text="<html><title>2026 Baseball Roster</title> sidearm</html>")

    f = _fetcher(handler, tmp_path, sleeps)
    f.get("https://csusmcougars.com/sports/baseball/roster")
    f.get("https://csusmcougars.com/sports/baseball/stats/2026")
    assert calls == ["/robots.txt", "/sports/baseball/roster", "/sports/baseball/stats/2026"]
    assert 30 in [round(s) for s in sleeps]  # crawl-delay honored between page hits
    # cached: no new network call
    r = f.get("https://csusmcougars.com/sports/baseball/roster")
    assert r.from_cache and len(calls) == 3
    with pytest.raises(SourceUnavailable, match="robots"):
        f.get("https://csusmcougars.com/services/x.ashx")


@pytest.mark.parametrize("status,body,match", [
    (403, "Forbidden", "restricted"),
    (429, "slow down", "restricted"),
    (404, "nope", "not found"),
    (200, "<html>Please complete the CAPTCHA to verify you are human</html>", "challenge"),
])
def test_fetcher_marks_unavailable_and_never_bypasses(tmp_path, status, body, match):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(status, text=body)

    f = _fetcher(handler, tmp_path, [])
    with pytest.raises(SourceUnavailable, match=match):
        f.get("https://example.edu/sports/baseball/roster")


def test_robots_forbidden_means_unavailable(tmp_path):
    f = _fetcher(lambda req: httpx.Response(403), tmp_path, [])
    with pytest.raises(SourceUnavailable):
        f.get("https://example.edu/sports/baseball/roster")


# ---------------------------------------------------------------- parsing
def test_parse_real_roster_fixture(csusm_team_ref):
    r = FixtureAdapter().fetch_roster(csusm_team_ref)
    assert r.season_label == "2026"
    assert len(r.players) == 37
    assert r.source.url == "https://csusmcougars.com/sports/baseball/roster"
    by = {p.name: p for p in r.players}
    shor = by["Max Shor"]
    assert (shor.site_player_id, shor.jersey, shor.position_raw, shor.class_year_raw, shor.bats_throws) == (
        "8383", "8", "C", "Graduate Student", "R/R")
    assert by["Luke Higgins"].class_year_raw == "Redshirt Senior"  # desktop block, not the "R-Sr." mobile dup
    assert by["Mikey Gray"].position_raw == "INF/RHP"
    assert by["Jaden St. Cyr"].previous_school == "Chaffey College"


# One <li> exactly as served by csusmcougars.com (whitespace collapsed, image + audio removed)
REAL_LI = ('<li class="sidearm-roster-player" data-bind="click: togglePlayer" data-player-id="7619" '
           'data-player-url="/sports/baseball/roster/michael-weber/7619"><div class="sidearm-roster-player-container '
           'flex row flex-wrap flex-align-center"><div class="sidearm-roster-player-details flex flex-align-center '
           'large-6 x-small-12 full columns"><div class="sidearm-roster-player-pertinents flex-item-1 column"><div '
           'class="sidearm-roster-player-position"><span class="text-bold"><span class="sidearm-roster-player-position'
           '-long-short hide-on-small-down"> Infielder </span><span class="sidearm-roster-player-position-long-short '
           'hide-on-medium"> INF </span></span><span class="sidearm-roster-player-height">6\'1"</span><span '
           'class="sidearm-roster-player-weight">220 lbs</span><span class="sidearm-roster-player-custom1">R/R</span>'
           '</div><div class="sidearm-roster-player-name"><span class="sidearm-roster-player-jersey flex flex-inline">'
           '<span class="sidearm-roster-player-jersey-number"> 1 </span></span><p></p><h3><a href="/sports/baseball/'
           'roster/michael-weber/7619" aria-label="Michael Weber - View Full Bio">Michael Weber</a></h3><p></p></div>'
           '<div class="sidearm-roster-player-other hide-on-large"><div class="sidearm-roster-player-class-hometown">'
           '<span class="sidearm-roster-player-academic-year hide-on-large">Sr.</span><span class="sidearm-roster-'
           'player-hometown">Pittsburg, Calif.</span><span class="sidearm-roster-player-previous-school">UC Riverside'
           '</span></div></div></div></div><div class="sidearm-roster-player-other flex-item-1 columns hide-on-medium-'
           'down"><div class="sidearm-roster-player-class-hometown"><span class="sidearm-roster-player-academic-year">'
           'Senior</span><span class="sidearm-roster-player-hometown">Pittsburg, Calif.</span><span class="sidearm-'
           'roster-player-previous-school">UC Riverside</span></div></div></div><button type="button" class="reset-'
           'button sidearm-roster-player-toggle"> Hide/Show Additional Information For Michael Weber </button></li>')


def _res(html, url="https://x.edu/sports/baseball/roster"):
    return FetchResult(url, 200, html, datetime.now(timezone.utc), False, "h")


def test_parse_untouched_real_markup(csusm_team_ref):
    html = f"<html><head><title>2026 Baseball Roster - X</title></head><body><ul>{REAL_LI}</ul></body></html>"
    r = SidearmAdapter(fetcher=None).parse_roster(_res(html), csusm_team_ref)
    p = r.players[0]
    assert (p.name, p.site_player_id, p.jersey, p.position_raw, p.class_year_raw, p.previous_school) == (
        "Michael Weber", "7619", "1", "INF", "Senior", "UC Riverside")


def test_parse_roster_table_fallback(csusm_team_ref):
    html = ("<html><title>2025-26 Roster</title><table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Cl.</th>"
            "<th>B/T</th></tr></thead><tbody><tr><td>7</td><td><a href='/roster/jane/55'>Jane Doe</a></td><td>C</td>"
            "<td>Jr.</td><td>R/R</td></tr></tbody></table></html>")
    r = SidearmAdapter(fetcher=None).parse_roster(_res(html), csusm_team_ref)
    assert r.season_label == "2025-26"
    assert (r.players[0].name, r.players[0].site_player_id, r.players[0].class_year_raw) == ("Jane Doe", "55", "Jr.")


def test_unrecognised_page_raises(csusm_team_ref):
    with pytest.raises(ParseError):
        SidearmAdapter(fetcher=None).parse_roster(_res("<html><title>Home</title><p>hi</p></html>"), csusm_team_ref)


def test_parse_real_stats_fixture(csusm_team_ref):
    s = FixtureAdapter().fetch_stats(csusm_team_ref, "2026")
    assert len(s.tables["batting"]) == 20  # Totals / Opponents rows excluded
    assert len(s.tables["pitching"]) == 16
    shor = next(r for r in s.tables["batting"] if r.site_player_id == "8383")
    assert shor.name == "Shor, Max" and shor.jersey == "8" and shor.values["GP-GS"] == "47-40"


def test_stats_season_mismatch_is_rejected(csusm_team_ref):
    html = "<html><title>2025 Baseball Cumulative Statistics</title></html>"
    with pytest.raises(ParseError, match="2025"):
        SidearmAdapter(fetcher=None).parse_stats(_res(html, "https://x.edu/sports/baseball/stats/2026"),
                                                 csusm_team_ref, "2026")


def test_unknown_season_redirect_is_rejected(csusm_team_ref):
    # live behaviour: /stats/2027 redirects to /schedule titled "2026 Baseball Schedule"
    html = "<html><title>2026 Baseball Schedule - Cal State San Marcos Athletics</title></html>"
    with pytest.raises(ParseError, match="redirected"):
        SidearmAdapter(fetcher=None).parse_stats(_res(html, "https://csusmcougars.com/sports/baseball/schedule"),
                                                 csusm_team_ref, "2026")
