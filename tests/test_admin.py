"""Dashboard: every button runs the real workflow."""
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Opportunity, PublishedPost, PublishingQueue, Status

AUTH = ("admin", "test-password")


@pytest.fixture
def client(db):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded(db, client, now):
    from app.pipeline.research import run_research

    run_research(db, "baseball")
    db.commit()
    return db.scalar(select(Opportunity))


def csrf(client, path="/admin"):
    html = client.get(path, auth=AUTH).text
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def test_requires_login(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    assert client.get("/healthz").json() == {"ok": True}


def test_list_and_detail_show_everything(client, seeded):
    html = client.get("/admin?status=pending&sport=baseball", auth=AUTH).text
    assert "Cal State San Marcos" in html and "Catcher" in html and "MEDIUM" in html
    assert "TEST MODE" in html
    d = client.get(f"/admin/opp/{seeded.id}", auth=AUTH).text
    for s in ["Opportunity Signal", "Data quality", "Official Roster", "Official Statistics",
              "https://csusmcougars.com/sports/baseball/stats/2026", "Telegram preview", "X teaser preview",
              "Max Shor", "final_year_listed", "APPROVE", "REJECT", "REANALYZE", "guardrails pass"]:
        assert s in d, s


def test_csrf_required(client, seeded):
    r = client.post(f"/admin/opp/{seeded.id}/approve", auth=AUTH, data={"csrf": "nope"})
    assert r.status_code == 403


def test_full_button_flow(client, seeded, db):
    tok = csrf(client)
    oid = seeded.id
    # EDIT (clean)
    txt = seeded.telegram_text.replace("SCOUT'S TAKE", "SCOUT’S TAKE")
    r = client.post(f"/admin/opp/{oid}/edit", auth=AUTH, data={"csrf": tok, "telegram_text": txt,
                                                                 "x_teaser": seeded.x_teaser}, follow_redirects=False)
    assert r.status_code == 303 and "Copy%20saved" in r.headers["location"]
    # APPROVE
    r = client.post(f"/admin/opp/{oid}/approve", auth=AUTH, data={"csrf": tok}, follow_redirects=True)
    assert "Approved." in r.text
    db.expire_all()
    assert db.get(Opportunity, oid).status == Status.APPROVED
    # SCHEDULE for tomorrow then unschedule
    from app.publishing.service import local_today

    day = (local_today() + timedelta(days=1)).isoformat()
    r = client.post(f"/admin/opp/{oid}/schedule", auth=AUTH, data={"csrf": tok, "day": day}, follow_redirects=True)
    assert f"Scheduled for {day}" in r.text
    db.expire_all()
    assert db.scalar(select(PublishingQueue)).publish_date.isoformat() == day
    client.post(f"/admin/opp/{oid}/unschedule", auth=AUTH, data={"csrf": tok})
    db.expire_all()
    assert db.get(Opportunity, oid).status == Status.APPROVED and db.scalar(select(PublishingQueue)) is None
    # REANALYZE (fixture data, no change)
    r = client.post(f"/admin/opp/{oid}/reanalyze", auth=AUTH, data={"csrf": tok}, follow_redirects=True)
    assert "Reanalyzed" in r.text
    # PUBLISH NOW (test mode → logged, marked published)
    r = client.post(f"/admin/opp/{oid}/publish", auth=AUTH, data={"csrf": tok}, follow_redirects=True)
    assert "test: logged, not sent" in r.text
    db.expire_all()
    assert db.get(Opportunity, oid).status == Status.PUBLISHED
    assert db.scalar(select(PublishedPost)).mode == "test"
    # can't publish twice
    r = client.post(f"/admin/opp/{oid}/publish", auth=AUTH, data={"csrf": tok}, follow_redirects=True)
    assert "Not published" in r.text
    assert "Published (1)" in client.get("/admin?status=published", auth=AUTH).text


def test_bad_edit_is_flagged_and_blocks_approval(client, seeded, db):
    tok = csrf(client)
    bad = seeded.telegram_text.replace("Roster analysis only.", "") + "\nScholarship available!"
    r = client.post(f"/admin/opp/{seeded.id}/edit", auth=AUTH, data={"csrf": tok, "telegram_text": bad,
                                                                      "x_teaser": seeded.x_teaser},
                    follow_redirects=True)
    assert "blocked until fixed" in r.text
    r = client.post(f"/admin/opp/{seeded.id}/approve", auth=AUTH, data={"csrf": tok}, follow_redirects=True)
    assert "fails guardrails" in r.text
    db.expire_all()
    assert db.get(Opportunity, seeded.id).status == Status.PENDING


def test_reject(client, seeded, db):
    tok = csrf(client)
    client.post(f"/admin/opp/{seeded.id}/reject", auth=AUTH, data={"csrf": tok, "note": "not convinced"})
    db.expire_all()
    o = db.get(Opportunity, seeded.id)
    assert o.status == Status.REJECTED and o.status_note == "not convinced"


def test_preview_sanitizes_html():
    from app.admin.routes import telegram_preview

    out = str(telegram_preview('<b>ok</b><script>alert(1)</script><a href="javascript:x">y</a>'
                               '<a href="https://ok.edu">z</a>'))
    assert "<b>ok</b>" in out and "<script>" not in out and '<a href="javascript' not in out
    assert 'href="https://ok.edu"' in out


def test_queue_events_and_verified_pages(client, seeded, db):
    assert "Next up" in client.get("/admin/queue?sport=baseball", auth=AUTH).text
    assert "opportunity_created" in client.get("/admin/events", auth=AUTH).text
    tok = csrf(client, "/admin/verified/new")
    team_id = seeded.team_id
    r = client.post("/admin/verified/new", auth=AUTH, follow_redirects=True, data={
        "csrf": tok, "team_id": team_id, "position_group": "LHP", "target_season": "2027",
        "summary": "The program's official site says it is recruiting left-handed pitchers for 2027.",
        "quote": "We are recruiting LHPs in the 2027 class.", "source_url": "https://csusmcougars.com/news/x",
        "source_label": "Official program announcement", "tier": "A", "publisher": "", "author_account": ""})
    assert "Verified need created" in r.text and "🟢 VERIFIED NEED" in r.text
    # social media without account is refused
    r = client.post("/admin/verified/new", auth=AUTH, follow_redirects=True, data={
        "csrf": tok, "team_id": team_id, "position_group": "C", "target_season": "2027", "summary": "x",
        "quote": "y", "source_url": "https://x.com/someone/status/1", "source_label": "post", "tier": "A",
        "publisher": "", "author_account": ""})
    assert "original account" in r.text


def test_other_sport_detail_shows_its_own_columns_and_verification_notice(db, client, now, unverified):
    unverified("mens_basketball")
    from app.pipeline.research import research_team
    from tests import test_other_sports as other

    team = other._basketball(db)
    research_team(db, team, now=now)
    db.commit()
    o = db.scalar(select(Opportunity).where(Opportunity.position_group == "G"))
    html = client.get(f"/admin/opp/{o.id}", auth=AUTH).text
    assert "<th>Minutes</th>" in html and "<th>Starts</th>" in html
    assert "hasn&#39;t been verified on live sites yet" in html or "hasn't been verified on live sites yet" in html
    assert client.get("/admin?sport=mens_basketball", auth=AUTH).status_code == 200
    assert "Example State" in client.get("/admin?sport=mens_basketball", auth=AUTH).text
