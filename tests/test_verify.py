"""`verify` (checks page reading on live sites) and the live-publishing lock for unverified sports."""
import json
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.collectors import registry as creg
from app.collectors.fixture import FixtureAdapter
from app.models import Opportunity, Status
from app.pipeline import verify, workflow
from app.pipeline.research import research_team
from app.publishing.service import publish_opportunity
from app.settings import reset_settings_cache
from tests import test_other_sports as other
from tests.sidearm_html import roster_html, stat_table, stats_html


def _site(pages: dict[str, str]):
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n")
        if req.url.path in pages:
            return httpx.Response(200, text=pages[req.url.path])
        return httpx.Response(404)

    return verify.RecordingFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None,
                                   use_cache=False)


def _csv(tmp_path, monkeypatch, sport="mens_basketball", path="mens-basketball"):
    d = tmp_path / "programs"
    d.mkdir()
    (d / f"{sport}.csv").write_text(
        "slug,name,short_name,division,conference,state,adapter,base_url,sport_path,active\n"
        f"exst,Example State,EXST,NCAA D2,,,sidearm,https://example.edu,{path},false\n")
    monkeypatch.setattr(verify, "PROGRAMS_DIR", d)


def _basketball_pages():
    ids = other._ids(other.BB_PREV)
    return {
        "/sports/mens-basketball/roster": roster_html("2026-27 Men's Basketball Roster", other.BB_CUR),
        "/sports/mens-basketball/roster/2025-26": roster_html("2025-26 Men's Basketball Roster", other.BB_PREV),
        "/sports/mens-basketball/stats/2025-26": stats_html("2025-26 Men's Basketball Statistics", [
            stat_table("Individual Overall Statistics", other.BB_HEAD, other.BB_ROWS, ids)]),
    }


def test_verify_reports_pass_and_saves_fixture_pages(tmp_path, monkeypatch, now):
    _csv(tmp_path, monkeypatch)
    out = []
    reps = verify.run_verify("mens_basketball", save_dir=str(tmp_path / "saved"), fetcher=_site(_basketball_pages()),
                             now=now, echo=out.append)
    text = "\n".join(out)
    assert [r.verdict for r in reps] == ["PASS"], text
    assert "season 2026-27  players 7" in text and "last season's roster" in text
    assert "table 'overall': 7 players" in text and "7/7 (100%)" in text
    assert "G    listed  4, final-year  2; minutes departing 1700.0 of 1900.0" in text
    assert "is NOT live-verified yet" in text
    # saved pages load back through the fixture adapter (so they can become test fixtures)
    manifest = json.loads((tmp_path / "saved" / "manifest.json").read_text())
    assert set(manifest["exst:mens_basketball"]["rosters"]) == {"2025-26"}
    fx = FixtureAdapter(tmp_path / "saved")
    ref = creg.TeamRef("mens_basketball", "exst", "Example State", "https://example.edu", "mens-basketball")
    assert len(fx.fetch_roster(ref).players) == 7 and fx.fetch_stats(ref, "2025-26").tables["overall"]


def test_verify_flags_unreadable_pages(tmp_path, monkeypatch, now):
    _csv(tmp_path, monkeypatch)
    pages = _basketball_pages()
    pages["/sports/mens-basketball/stats/2025-26"] = stats_html("2025-26 Men's Basketball Statistics",
                                                                ["<table><caption>Team Totals</caption></table>"])
    out = []
    reps = verify.run_verify("mens_basketball", fetcher=_site(pages), now=now, echo=out.append)
    assert reps[0].verdict == "FAIL" and "no individual stats tables recognised" in "\n".join(out)


def test_unverified_sport_never_posts_live(db, now, monkeypatch):
    team = other._basketball(db)
    research_team(db, team, now=now)
    o = db.scalar(select(Opportunity).where(Opportunity.position_group == "G"))
    workflow.approve(db, o)
    db.commit()
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("TELEGRAM_MBB_CHANNEL_ID", "-100123")
    reset_settings_cache()

    def no_network(req):
        raise AssertionError("must not contact Telegram")

    from app.publishing.telegram import TelegramClient

    client = TelegramClient(token="TEST-TOKEN", http=httpx.Client(transport=httpx.MockTransport(no_network)))
    out = publish_opportunity(db, o, client=client, now=now + timedelta(hours=1))
    assert out.status == "blocked" and "verify --sport mens_basketball" in out.message
    assert o.status == Status.APPROVED
