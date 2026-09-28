"""Private Telegram admin chat: review cards, Approve/Reject buttons, allowlist, webhook, polling."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Opportunity, Status
from app.pipeline.research import run_research
from app.publishing import admin_bot
from app.publishing.telegram import TelegramClient
from app.settings import reset_settings_cache

ADMIN = 555000111


class FakeBotApi:
    def __init__(self, updates=None):
        self.calls: list[tuple[str, dict]] = []
        self.updates = updates or []

    def handler(self, req: httpx.Request):
        method = req.url.path.rsplit("/", 1)[-1]
        body = json.loads(req.content or b"{}")
        self.calls.append((method, body))
        if method == "sendMessage":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.calls)}})
        if method == "getUpdates":
            off = body.get("offset") or 0
            return httpx.Response(200, json={"ok": True, "result": [u for u in self.updates if u["update_id"] >= off]})
        return httpx.Response(200, json={"ok": True, "result": True})

    def client(self):
        return TelegramClient(token="T", http=httpx.Client(transport=httpx.MockTransport(self.handler)))

    def sent(self, method):
        return [b for m, b in self.calls if m == method]


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", str(ADMIN))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tam-admin.example.com")
    reset_settings_cache()


def _press(data, user=ADMIN, update_id=1):
    return {"update_id": update_id, "callback_query": {
        "id": "cb1", "from": {"id": user, "username": "chase"}, "data": data,
        "message": {"message_id": 9, "chat": {"id": ADMIN}}}}


def test_new_pending_items_are_sent_once_with_buttons(db, now, admin_env):
    run_research(db, "baseball", now=now)
    api = FakeBotApi()
    assert admin_bot.notify_pending(db, api.client()) == 1
    assert admin_bot.notify_pending(db, api.client()) == 0  # not re-sent
    msg = api.sent("sendMessage")[0]
    assert msg["chat_id"] == str(ADMIN) and msg["parse_mode"] == "HTML"
    assert "Cal State San Marcos" in msg["text"] and "Signal 74.8 · MEDIUM" in msg["text"]
    assert "Roster analysis only." in msg["text"]  # the exact public post is previewed
    kb = msg["reply_markup"]["inline_keyboard"]
    assert [b["callback_data"] for b in kb[0]] == ["approve:1", "reject:1"]
    assert kb[1][0]["url"] == "https://tam-admin.example.com/admin/opp/1"


def test_approve_button_uses_workflow_rules(db, now, admin_env):
    run_research(db, "baseball", now=now)
    api = FakeBotApi()
    reply = admin_bot.handle_update(db, _press("approve:1"), api.client())
    assert reply.startswith("✅ #1 approved")
    assert db.get(Opportunity, 1).status == Status.APPROVED
    assert api.sent("answerCallbackQuery")[0]["text"].startswith("✅")
    assert api.sent("editMessageReplyMarkup")  # buttons replaced so it can't be pressed twice
    # pressing again: the workflow refuses (already approved)
    again = admin_bot.handle_update(db, _press("approve:1"), api.client())
    assert "can't approve" in again


def test_low_confidence_needs_the_dashboard(db, now, admin_env):
    run_research(db, "baseball", now=now)
    o = db.get(Opportunity, 1)
    o.confidence = "LOW"
    reply = admin_bot.handle_update(db, _press("approve:1"), FakeBotApi().client())
    assert "LOW confidence" in reply and o.status == Status.PENDING


def test_strangers_cannot_press_buttons(db, now, admin_env):
    run_research(db, "baseball", now=now)
    assert admin_bot.handle_update(db, _press("reject:1", user=42), FakeBotApi().client()) == "Not allowed."
    assert db.get(Opportunity, 1).status == Status.PENDING


def test_start_tells_a_new_user_their_chat_id(db, admin_env):
    api = FakeBotApi()
    reply = admin_bot.handle_update(db, {"update_id": 5, "message": {"text": "/start", "chat": {"id": 777},
                                                                    "from": {"id": 777}}}, api.client())
    assert "TELEGRAM_ADMIN_CHAT_ID=777" in reply


def test_polling_processes_each_update_once(db, now, admin_env):
    run_research(db, "baseball", now=now)
    api = FakeBotApi(updates=[_press("reject:1", update_id=40)])
    assert admin_bot.poll(db, api.client()) == 1
    assert db.get(Opportunity, 1).status == Status.REJECTED
    assert admin_bot.poll(db, api.client()) == 0  # offset remembered
    assert api.sent("getUpdates")[-1]["offset"] == 41


def test_webhook_requires_the_secret(db, now, admin_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3cret")
    reset_settings_cache()
    run_research(db, "baseball", now=now)
    db.commit()
    api = FakeBotApi()
    monkeypatch.setattr(admin_bot, "TelegramClient", api.client)
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/telegram/webhook", json=_press("approve:1")).status_code == 403
        r = c.post("/telegram/webhook", json=_press("approve:1"),
                   headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
        assert r.status_code == 200
    db.expire_all()
    assert db.scalar(select(Opportunity)).status == Status.APPROVED


def test_webhook_is_off_without_a_secret(admin_env):
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/telegram/webhook", json={}).status_code == 404
