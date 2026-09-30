"""Head coach contact: read only what the school publishes on its official athletics pages.

Pages in tests/fixtures/coaches are REAL official pages (captured 2026-09-28, slimmed)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.collectors.coaches import email_on_bio_page, is_head_coach, parse_staff, pick_head_coach
from app.content.guardrails import check_telegram
from app.content.telegram_post import CoachContact
from app.pipeline.research import coach_due, save_coach
from tests.test_content import post

DIR = Path(__file__).parent / "fixtures" / "coaches"


@pytest.mark.parametrize("slug,name,email", [
    ("university-of-kansas", "Jennifer McFalls", "jmcfalls@ku.edu"),
    ("charleston-southern-university", "Christi Musser", "cmusser@csuniv.edu"),
])
def test_person_cards_on_real_roster_pages(slug, name, email):
    url = f"https://example.edu/sports/softball/roster"
    staff = parse_staff((DIR / f"{slug}_softball_roster.html").read_text(), url)
    head = pick_head_coach(staff)
    assert (head.name, head.title, head.email) == (name, "Head Coach", email)
    # associate head coaches, trainers and directors are never taken for the head coach
    assert all(not is_head_coach(c.title) for c in staff if c.name != name)


def test_head_coach_titles():
    for t in ["Head Coach", "Head Softball Coach", "Head Men's Basketball Coach", "Interim Head Coach",
              "Head Football Coach", "Associate Athletic Director for Administration/Head Coach"]:
        assert is_head_coach(t), t
    for t in ["Associate Head Coach", "Assistant Coach", "Assistant Head Coach", "Volunteer Assistant Coach",
              "Director of Operations", "Head Athletic Trainer", "Head Strength and Conditioning Coach",
              "Associate Head Coach/Recruiting Coordinator", None]:
        assert not is_head_coach(t), t


def test_bio_page_email_must_belong_to_the_coach():
    page = """<html><body><div class="sidearm-coach-bio"><dl><dt>Title:</dt><dd>Head Coach</dd>
      <dt>Email:</dt><dd><a href="mailto:jsmith@school.edu">jsmith@school.edu</a></dd></dl></div>
      <footer><a href="mailto:athletics@school.edu">athletics@school.edu</a></footer></body></html>"""
    assert email_on_bio_page(page, "Jane Smith") == "jsmith@school.edu"
    # only a department address (in the footer) or an unrelated one: nothing, never a guess
    only_footer = page.replace('jsmith@school.edu">jsmith@school.edu', 'x@y.edu">x')
    only_footer = only_footer.replace("<dt>Email:</dt>", "<dt>Phone:</dt>")
    assert email_on_bio_page(only_footer, "Jane Smith") is None
    assert email_on_bio_page("<p><a href='mailto:not-an-email'>x</a></p>", "Jane Smith") is None


def test_contact_block_at_the_bottom_of_posts():
    c = CoachContact("Jane Smith", "Head Coach", "jsmith@school.edu", "https://school.edu/sports/softball/coaches")
    t = post(coach=c)
    assert t.rstrip().splitlines()[-4:] == [
        "📬 <b>Contact the coaching staff</b>", "Head Coach: Jane Smith", "jsmith@school.edu",
        '<i>Listed on the <a href="https://school.edu/sports/softball/coaches">official athletics site</a>.</i>']
    assert t.index("📎 <b>Sources</b>") < t.index("📬")
    assert check_telegram(t, "roster_opportunity").ok
    # no published email: no contact block at all
    assert "📬" not in post(coach=CoachContact("Jane Smith", "Head Coach", None))
    assert "📬" not in post()


class _Team:
    coach_name = coach_title = coach_email = coach_source_url = coach_checked_at = None


def test_save_coach_keeps_only_what_the_site_shows():
    from app.collectors.coaches import RawCoach

    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    t = _Team()
    assert coach_due(t, now)
    save_coach(t, RawCoach("Jane Smith", "Head Coach", "jsmith@school.edu", "https://s.edu/c"), now)
    assert (t.coach_email, t.coach_source_url, coach_due(t, now + timedelta(days=5))) == (
        "jsmith@school.edu", "https://s.edu/c", False)
    assert coach_due(t, now + timedelta(days=31))
    save_coach(t, None, now)  # pages unreachable this time: keep the last known contact
    assert t.coach_email == "jsmith@school.edu"
    save_coach(t, RawCoach("New Coach", "Head Coach", None, "https://s.edu/r"), now)  # site stopped showing it
    assert (t.coach_name, t.coach_email) == ("New Coach", None)


class _Pages:
    """Serves saved real pages by URL; anything else is 'not found'. Records what was asked for."""

    def __init__(self, pages: dict[str, Path]):
        self.pages, self.asked = pages, []

    def get(self, url, *, force_refresh=False):
        from app.collectors.base import SourceUnavailable
        from app.collectors.http import FetchResult

        self.asked.append(url)
        if url not in self.pages:
            raise SourceUnavailable(url, "not found (HTTP 404)", 404)
        return FetchResult(url=url, status=200, text=self.pages[url].read_text(),
                           fetched_at=datetime(2026, 9, 30, tzinfo=timezone.utc), from_cache=False, content_hash="x")


SOFT = Path(__file__).parent / "fixtures" / "sidearm_softball"


def _lookup(base, slug, extra):
    from app.collectors.base import TeamRef
    from app.collectors.sidearm import SidearmAdapter

    pages = _Pages({f"{base}/sports/softball/roster": SOFT / f"{slug}_softball_roster.html",
                    **{f"{base}{path}": DIR / f for path, f in extra.items()}})
    return SidearmAdapter(pages).fetch_head_coach(TeamRef("softball", slug, slug, base, "softball")), pages.asked


def test_classic_site_email_comes_from_the_head_coachs_bio_page():
    coach, asked = _lookup("https://csusmcougars.com", "csusm", {
        "/sports/softball/roster/coaches/a-j-robinson/1000": "csusm_softball_coach_bio.html",
        "/sports/softball/coaches": "csusm_softball_coaches.html"})
    assert (coach.name, coach.title, coach.email) == ("A.J. Robinson", "Head Softball Coach", "arobinson@csusm.edu")
    assert coach.source_url.endswith("/roster/coaches/a-j-robinson/1000")
    assert not any(u.endswith("/coaches") for u in asked)  # found on the bio page: staff page not needed


def test_school_that_publishes_no_email_gets_none():
    coach, asked = _lookup("https://hillsdalechargers.com", "hillsdale-college", {
        "/sports/softball/roster/coaches/kyle-gross/570": "hillsdale-college_softball_coach_bio.html",
        "/sports/softball/coaches": "hillsdale-college_softball_coaches.html"})
    assert (coach.name, coach.email) == ("Kyle Gross", None)
    assert asked[-1].endswith("/sports/softball/coaches")  # tried every official page before giving up


def test_combined_title_on_a_real_staff_page():
    from app.collectors.coaches import head_role

    head = pick_head_coach(parse_staff((DIR / "stevens-institute-of-technology_softball_coaches.html").read_text(),
                                       "https://stevensducks.com/sports/softball/coaches"))
    assert (head.name, head.email) == ("Emily Kaczmarek", "ekaczmar@stevens.edu")
    assert head_role(head.title) == "Head Coach"
