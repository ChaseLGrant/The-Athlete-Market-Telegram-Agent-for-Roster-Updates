"""Research pipeline end-to-end on fixtures: storage, dedupe, material change."""
from datetime import timedelta

from sqlalchemy import func, select

from app.collectors.fixture import FixtureAdapter
from app.collectors import registry as creg
from app.models import (EventLog, Opportunity, OpportunityEvidence, PlayerStat, RosterEntry, ScoreHistory, Source,
                        Status, TelegramChannel)
from app.pipeline import workflow
from app.pipeline.research import run_research


def _count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def test_research_creates_evidence_backed_opportunity(db, now):
    results = run_research(db, "baseball", now=now)
    assert results[0].ok, results[0].message
    opps = db.scalars(select(Opportunity)).all()
    assert len(opps) == 1
    o = opps[0]
    assert (o.school.name, o.position_group, o.status, o.confidence) == ("Cal State San Marcos", "C", "pending",
                                                                         "MEDIUM")
    assert o.opportunity_type == "roster_opportunity"
    assert {s.url for s in o.sources} == {"https://csusmcougars.com/sports/baseball/roster",
                                          "https://csusmcougars.com/sports/baseball/stats/2026"}
    assert all(s.tier == "A" for s in o.sources)
    assert _count(db, OpportunityEvidence, OpportunityEvidence.opportunity_id == o.id) == 5  # summary + 4 catchers
    assert _count(db, RosterEntry) == 37 and _count(db, PlayerStat) == 36
    assert _count(db, PlayerStat, PlayerStat.player_id.is_(None)) == 0
    assert "Roster analysis only." in o.telegram_text and o.x_teaser
    assert "Cal State San Marcos" not in o.x_teaser
    assert _count(db, TelegramChannel) == 7
    assert db.scalar(select(TelegramChannel.channel_env_var).where(TelegramChannel.sport == "baseball")) == \
        "TELEGRAM_BASEBALL_CHANNEL_ID"


def test_rerun_dedupes(db, now):
    run_research(db, "baseball", now=now)
    run_research(db, "baseball", now=now + timedelta(hours=5))
    assert _count(db, Opportunity) == 1
    assert _count(db, EventLog, EventLog.event == "duplicate_detected") == 1
    o = db.scalar(select(Opportunity))
    assert o.first_detected_at < o.last_analyzed_at


def test_material_change_sends_approved_back_to_pending(db, now):
    run_research(db, "baseball", now=now)
    o = db.scalar(select(Opportunity))
    workflow.approve(db, o)
    db.commit()
    # the site updates: the Junior catcher gets 30 starts' worth of new stats row -> numbers change
    fx = FixtureAdapter()
    stats_path = fx.dir / "csusm_baseball_stats_2026.html"
    html = stats_path.read_text().replace(">47-40<", ">47-10<")  # Shor's starts
    creg.set_fixture_adapter(FixtureAdapter(overrides={"csusm:baseball:stats:2026": html}))
    run_research(db, "baseball", now=now + timedelta(days=1))
    db.refresh(o)
    assert o.status == Status.PENDING
    assert "changed materially" in o.status_note
    assert _count(db, ScoreHistory, ScoreHistory.opportunity_id == o.id) == 2


def test_source_unavailable_is_logged_not_fatal(db, now, monkeypatch):
    monkeypatch.setenv("TEST_MODE", "false")
    from app.settings import reset_settings_cache

    reset_settings_cache()
    import httpx
    from app.collectors.http import PoliteFetcher

    creg._fetcher = PoliteFetcher(client=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(403, text="blocked"))), sleep=lambda s: None)
    res = run_research(db, "baseball", now=now)
    assert not res[0].ok and "unavailable" in res[0].message
    assert _count(db, Opportunity) == 0
    assert _count(db, EventLog, EventLog.event == "source_unavailable") == 1
    assert _count(db, Source, Source.available.is_(False)) == 1


def test_expire_stale(db, now):
    run_research(db, "baseball", now=now)
    o = db.scalar(select(Opportunity))
    assert workflow.expire_stale(db, now=now + timedelta(days=30)) == 1
    assert o.status == Status.EXPIRED


def test_research_batch_rotates_least_recently_checked_first(db, now, monkeypatch):
    from app.models import School, Team
    from app.pipeline import research

    run_research(db, "baseball", now=now)  # csusm checked
    s2 = School(slug="zz", name="Zed U")
    db.add(s2)
    db.flush()
    db.add(Team(school_id=s2.id, sport="baseball", adapter="sidearm", base_url="https://zed.example",
                sport_path="baseball"))
    db.commit()
    seen = []
    monkeypatch.setattr(research, "research_team",
                        lambda session, team, now=None, **kw: seen.append(team.school.slug) or
                        research.TeamResult(team.id, team.school.name, True, "ok"))
    monkeypatch.setenv("RESEARCH_BATCH", "1")
    from app.settings import reset_settings_cache

    reset_settings_cache()
    run_research(db, "baseball", now=now)
    assert seen == ["zz"]  # never checked -> goes first; csusm waits for the next run
