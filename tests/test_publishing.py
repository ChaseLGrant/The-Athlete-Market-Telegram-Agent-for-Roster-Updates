"""Publishing: modes, one-per-day, idempotency, revalidation, fail-safe behaviour."""
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.collectors import registry as creg
from app.collectors.base import SourceUnavailable
from app.models import Opportunity, PublishedPost, PublishingQueue, Status
from app.pipeline import workflow
from app.pipeline.research import run_research
from app.publishing.service import publish_daily, publish_opportunity
from app.publishing.telegram import TelegramClient
from app.settings import reset_settings_cache


class FakeTelegram:
    """Stands in for api.telegram.org via httpx.MockTransport."""

    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    def handler(self, req: httpx.Request):
        if self.fail == "network":
            raise httpx.ReadTimeout("timeout", request=req)
        body = json.loads(req.content or b"{}")
        method = req.url.path.rsplit("/", 1)[-1]
        assert "/botTEST-TOKEN/" in req.url.path
        if self.fail == "api":
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
        if method == "sendMessage":
            self.sent.append(body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 100 + len(self.sent)}})
        return httpx.Response(200, json={"ok": True, "result": {}})

    def client(self):
        return TelegramClient(token="TEST-TOKEN", http=httpx.Client(transport=httpx.MockTransport(self.handler)))


def _approved(db, now):
    run_research(db, "baseball", now=now)
    o = db.scalar(select(Opportunity))
    workflow.approve(db, o)
    db.commit()
    return o


def _live(monkeypatch, channel="-1001234567890"):
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("TELEGRAM_BASEBALL_CHANNEL_ID", channel)
    reset_settings_cache()


def test_test_mode_logs_and_marks_published_once(db, now):
    o = _approved(db, now)
    out = publish_daily(db, "baseball", now=now + timedelta(hours=1))
    assert out.ok and out.status == "logged"
    db.refresh(o)
    assert o.status == Status.PUBLISHED and o.published_at is not None
    post = db.scalar(select(PublishedPost))
    assert post.mode == "test" and post.status == "logged" and "ROSTER WATCH" in post.text
    again = publish_daily(db, "baseball", now=now + timedelta(hours=2))
    assert not again.ok and again.status == "skipped"
    assert db.scalar(select(func.count()).select_from(PublishedPost)) == 1


def test_live_publish_sends_once_and_records_message_id(db, now, monkeypatch):
    o = _approved(db, now)
    _live(monkeypatch)
    tg = FakeTelegram()
    out = publish_daily(db, "baseball", client=tg.client(), now=now + timedelta(hours=1))
    assert out.ok and out.status == "published" and out.telegram_message_id == 101
    assert len(tg.sent) == 1
    sent = tg.sent[0]
    assert sent["chat_id"] == "-1001234567890" and sent["parse_mode"] == "HTML"
    assert "Roster analysis only. This is not a confirmed recruiting opening from the coaching staff." in sent["text"]
    db.refresh(o)
    assert o.status == Status.PUBLISHED
    q = db.scalar(select(PublishingQueue))
    assert q.status == "published" and q.opportunity_id == o.id
    # a second daily run, a publish-now, and a re-approval attempt all refuse
    assert publish_daily(db, "baseball", client=tg.client(), now=now + timedelta(hours=3)).status == "skipped"
    assert publish_opportunity(db, o, client=tg.client(), now=now + timedelta(hours=3)).status == "blocked"
    with pytest.raises(workflow.WorkflowError):
        workflow.approve(db, o)
    assert len(tg.sent) == 1
    # research re-run does not re-queue a published item
    run_research(db, "baseball", now=now + timedelta(days=1))
    db.refresh(o)
    assert o.status == Status.PUBLISHED
    assert db.scalar(select(func.count()).select_from(Opportunity)) == 1


def test_dry_run_never_sends_or_marks_published(db, now, monkeypatch):
    o = _approved(db, now)
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("TELEGRAM_BASEBALL_CHANNEL_ID", "-100999")
    reset_settings_cache()
    tg = FakeTelegram()
    out = publish_opportunity(db, o, client=tg.client(), now=now + timedelta(hours=1))
    assert out.ok and out.status == "logged" and tg.sent == []
    db.refresh(o)
    assert o.status == Status.APPROVED


def test_missing_channel_id_blocks(db, now, monkeypatch):
    o = _approved(db, now)
    _live(monkeypatch, channel="")
    out = publish_opportunity(db, o, client=FakeTelegram().client(), now=now + timedelta(hours=1))
    assert out.status == "blocked" and "TELEGRAM_BASEBALL_CHANNEL_ID" in out.message
    assert o.status == Status.APPROVED


def test_telegram_api_error_is_retryable(db, now, monkeypatch):
    o = _approved(db, now)
    _live(monkeypatch)
    out = publish_opportunity(db, o, client=FakeTelegram(fail="api").client(), now=now + timedelta(hours=1))
    assert out.status == "failed" and "chat not found" in out.message
    assert o.status == Status.APPROVED
    assert db.scalar(select(func.count()).select_from(PublishedPost)) == 0  # claim released
    ok = publish_opportunity(db, o, client=FakeTelegram().client(), now=now + timedelta(hours=2))
    assert ok.ok


def test_ambiguous_network_error_is_never_auto_resent(db, now, monkeypatch):
    o = _approved(db, now)
    _live(monkeypatch)
    out = publish_opportunity(db, o, client=FakeTelegram(fail="network").client(), now=now + timedelta(hours=1))
    assert out.status == "failed" and "delivery unknown" in out.message
    tg = FakeTelegram()
    again = publish_opportunity(db, o, client=tg.client(), now=now + timedelta(hours=2))
    assert again.status == "skipped" and tg.sent == []


def test_stale_opportunity_is_revalidated_before_publish(db, now):
    o = _approved(db, now)
    later = now + timedelta(days=5)  # older than REVALIDATE_AFTER_HOURS (48h)
    out = publish_daily(db, "baseball", now=later)
    assert out.ok
    db.refresh(o)
    lv = o.last_verified_at if o.last_verified_at.tzinfo else o.last_verified_at.replace(tzinfo=later.tzinfo)
    assert lv == later


def test_stale_and_source_unavailable_blocks_publish(db, now):
    o = _approved(db, now)

    class Down:
        name = "down"

        def has(self, team):
            return True

        def fetch_roster(self, team, season=None):
            raise SourceUnavailable("https://csusmcougars.com/sports/baseball/roster", "HTTP 503", 503)

        fetch_stats = fetch_roster

    creg.set_fixture_adapter(Down())
    out = publish_daily(db, "baseball", now=now + timedelta(days=5))
    assert not out.ok and out.status == "blocked"
    db.refresh(o)
    assert o.status == Status.APPROVED and o.published_at is None
    assert db.scalar(select(func.count()).select_from(PublishedPost)) == 0


def test_material_change_on_revalidation_blocks_and_returns_to_pending(db, now):
    from app.collectors.fixture import FixtureAdapter

    o = _approved(db, now)
    html = (FixtureAdapter().dir / "csusm_baseball_stats_2026.html").read_text().replace(">47-40<", ">47-5<")
    creg.set_fixture_adapter(FixtureAdapter(overrides={"csusm:baseball:stats:2026": html}))
    out = publish_daily(db, "baseball", now=now + timedelta(days=5))
    assert not out.ok
    db.refresh(o)
    assert o.status == Status.PENDING and "materially" in o.status_note


def test_guardrails_block_bad_edited_copy(db, now):
    o = _approved(db, now)
    problems = workflow.edit_copy(db, o, o.telegram_text.replace("Roster analysis only.", "") +
                                  "\nThis school needs a catcher.", o.x_teaser)
    assert problems and o.status == Status.PENDING
    with pytest.raises(workflow.WorkflowError):
        workflow.approve(db, o)


def test_scheduling_and_variety_selection(db, now):
    from app.publishing.queue import rank_candidates

    o = _approved(db, now)
    day = (now + timedelta(days=2)).date()
    workflow.schedule(db, o, day)
    assert o.status == Status.SCHEDULED
    with pytest.raises(workflow.WorkflowError):
        workflow.approve(db, o)  # already scheduled
    # nothing approved is left for 'today' (the only item is scheduled for later)
    assert rank_candidates(db, "baseball", now.date(), now) == []
    out = publish_daily(db, "baseball", day=day, now=now + timedelta(days=2))
    assert out.ok and db.scalar(select(PublishingQueue)).status == "published"


def _twin(db, o, now):
    """A second approved baseball item (lower signal) for the same program."""
    from app.models import Opportunity as O

    twin = O(fingerprint="x" * 64, sport="baseball", school_id=o.school_id, team_id=o.team_id,
             opportunity_type="roster_opportunity", position_group="OF", position_label="Outfield",
             target_season="2027", stats_season="2026", roster_season="2026", departure_basis="class_year_projection",
             signal=50, confidence="MEDIUM", data_quality=0.9, components={}, metrics={}, reason="test",
             status=Status.APPROVED, telegram_text=o.telegram_text, x_teaser=o.x_teaser,
             last_verified_at=now, expires_at=now + timedelta(days=10))
    db.add(twin)
    db.commit()
    return twin


def test_one_post_per_sport_per_day(db, now):
    """Two approved items; only one goes out per day and the second waits for tomorrow."""
    o = _approved(db, now)
    twin = _twin(db, o, now)
    first = publish_daily(db, "baseball", now=now + timedelta(hours=1))
    second = publish_daily(db, "baseball", now=now + timedelta(hours=2))
    assert first.ok and first.opportunity_id == o.id  # higher signal wins
    assert second.status == "skipped"
    third = publish_daily(db, "baseball", now=now + timedelta(days=1))
    assert third.ok and third.opportunity_id == twin.id


def test_publish_now_respects_one_post_per_day(db, now, monkeypatch):
    """The dashboard's PUBLISH NOW button can't add a second post on a day that already has one."""
    o = _approved(db, now)
    twin = _twin(db, o, now)
    _live(monkeypatch)
    tg = FakeTelegram()
    assert publish_daily(db, "baseball", client=tg.client(), now=now + timedelta(hours=1)).ok
    out = publish_opportunity(db, twin, client=tg.client(), now=now + timedelta(hours=2))
    assert out.status == "blocked" and "max 1 per day" in out.message
    assert len(tg.sent) == 1 and twin.status == Status.APPROVED
    assert publish_opportunity(db, twin, client=tg.client(), now=now + timedelta(days=1)).ok


def test_unknown_delivery_uses_up_the_day(db, now, monkeypatch):
    """If Telegram may have received today's post, don't send a different one the same day."""
    o = _approved(db, now)
    _twin(db, o, now)
    _live(monkeypatch)
    out = publish_daily(db, "baseball", client=FakeTelegram(fail="network").client(), now=now + timedelta(hours=1))
    assert out.status == "failed"
    tg = FakeTelegram()
    again = publish_daily(db, "baseball", client=tg.client(), now=now + timedelta(hours=2))
    assert again.status == "skipped" and tg.sent == []


def test_pasted_secrets_are_trimmed(monkeypatch):
    """A token copied from Telegram with a leading newline must still work."""
    from app.settings import get_settings

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "\n123:ABC \n")
    monkeypatch.setenv("DATABASE_URL", " postgresql://u:p@h:5432/db\n")
    monkeypatch.setenv("TELEGRAM_BASEBALL_CHANNEL_ID", "\n@tam_baseball ")
    reset_settings_cache()
    s = get_settings()
    assert s.telegram_bot_token == "123:ABC"
    assert s.database_url == "postgresql://u:p@h:5432/db"
    assert s.channel_id_for("baseball") == "@tam_baseball"
    assert TelegramClient().token == "123:ABC"


@pytest.mark.parametrize("raw,expected", [
    ("@TheAthleteMarketSoccer", "@TheAthleteMarketSoccer"),
    ("TheAthleteMarketSoccer", "@TheAthleteMarketSoccer"),
    ("https://t.me/TheAthleteMarketSoccer", "@TheAthleteMarketSoccer"),
    (" t.me/TheAthleteMarketSoccer/ \n", "@TheAthleteMarketSoccer"),
    ("-1001234567890", "-1001234567890"),
    ("https://t.me/+AbCdEf123", "invite-link:+AbCdEf123"),
])
def test_channel_ids_accept_what_people_paste(raw, expected):
    from app.settings import normalize_chat_id

    assert normalize_chat_id(raw) == expected
