"""Review from Telegram: a private admin chat with Approve / Reject buttons.

After research, each new pending opportunity is sent to TELEGRAM_ADMIN_CHAT_ID as a card: the
exact post that would go to the public channel, plus the numbers behind it and two buttons.
Pressing a button runs the same rules as the dashboard (app/pipeline/workflow.py): guardrails,
LOW-confidence items still need the dashboard's explicit override, and nothing is ever published
from here; approved items go out through the normal daily job (one per sport per day).

Button presses reach us either through the dashboard's webhook (/telegram/webhook, instant) or by
polling (`python -m app.cli telegram-poll`, e.g. at the start of the daily GitHub job).
Only Telegram user ids in TELEGRAM_ADMIN_USER_IDS (default: the admin chat id) can act.
"""
from __future__ import annotations

from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.guardrails import TELEGRAM_MAX
from app.logging_setup import record_event
from app.models import EventLog, Opportunity, Status
from app.pipeline import workflow
from app.publishing.telegram import TelegramClient, TelegramError
from app.settings import get_settings
from app.sports.registry import get_sport

NOTIFIED = "admin_notified"      # event_log marker: this opportunity's card was sent
OFFSET = "telegram_poll_offset"  # event_log marker: last processed update id (polling)
HELP = ("Commands:\n/pending: re-send the top pending items\n/help: this message\n\n"
        "New items arrive here after each research run. ✅ approves (it then goes out in its sport's "
        "daily slot), ❌ rejects. LOW-confidence items need the dashboard.")


def enabled() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_admin_chat_id)


def _dashboard_link(opp_id: int) -> str | None:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/admin/opp/{opp_id}" if base.startswith("https://") else None


def card(opp: Opportunity) -> tuple[str, dict]:
    cfg = get_sport(opp.sport)
    head = (f"🆕 <b>Pending #{opp.id}</b> · {escape(cfg.display_name)}\n"
            f"<b>{escape(opp.school.name)}</b> · {escape(opp.position_label)}\n"
            f"Signal {opp.signal:.1f} · {escape(opp.confidence)} confidence"
            + ("" if cfg.live_verified else " · ⚠️ sport not live-verified yet") + "\n"
            f"<i>{escape(opp.reason or '')}</i>\n\n"
            "━━━━ post preview ━━━━\n")
    body = opp.telegram_text or ""
    if len(head) + len(body) > TELEGRAM_MAX:
        body = "(post is long; open it in the dashboard)"
    buttons = [[{"text": "✅ Approve", "callback_data": f"approve:{opp.id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{opp.id}"}]]
    link = _dashboard_link(opp.id)
    if link:
        buttons.append([{"text": "🔗 Open in dashboard", "url": link}])
    return head + body, {"inline_keyboard": buttons}


def _notified_ids(session: Session) -> set[int]:
    return set(session.scalars(select(EventLog.entity_id).where(EventLog.event == NOTIFIED)))


def notify_pending(session: Session, client: TelegramClient | None = None, *, limit: int = 10,
                   resend: bool = False) -> int:
    """Send cards for pending items not sent before (or the top `limit` again with resend=True)."""
    if not enabled():
        return 0
    s = get_settings()
    client = client or TelegramClient()
    done = set() if resend else _notified_ids(session)
    opps = [o for o in session.scalars(select(Opportunity).where(Opportunity.status == Status.PENDING)
                                       .order_by(Opportunity.signal.desc(), Opportunity.id))
            if o.id not in done][:limit]
    sent = 0
    for o in opps:
        text, markup = card(o)
        try:
            client.send_message(s.telegram_admin_chat_id, text, reply_markup=markup)
        except TelegramError as e:
            record_event(session, "telegram_failed", f"admin card for #{o.id} failed: {e}", level="ERROR",
                         sport=o.sport, entity_type="opportunity", entity_id=o.id)
            break
        record_event(session, NOTIFIED, f"#{o.id} sent to admin chat", sport=o.sport,
                     entity_type="opportunity", entity_id=o.id)
        sent += 1
    return sent


def _act(session: Session, action: str, opp_id: int, who: str) -> str:
    opp = session.get(Opportunity, opp_id)
    if opp is None:
        return f"#{opp_id} no longer exists."
    try:
        if action == "approve":
            workflow.approve(session, opp)
            result = f"✅ #{opp_id} approved. It goes out in the next free {get_sport(opp.sport).display_name} slot."
        elif action == "reject":
            workflow.reject(session, opp, note=f"Rejected from Telegram by {who}")
            result = f"❌ #{opp_id} rejected."
        else:
            return "Unknown action."
    except workflow.WorkflowError as e:
        return f"#{opp_id}: {e}"
    past = {"approve": "approved", "reject": "rejected"}[action]
    record_event(session, f"{past}_via_telegram", f"#{opp_id} {past} from Telegram by {who}",
                 sport=opp.sport, entity_type="opportunity", entity_id=opp_id)
    return result


def handle_update(session: Session, update: dict, client: TelegramClient | None = None) -> str | None:
    """Process one Telegram update (button press or command). Returns what we replied, for logs/tests."""
    client = client or TelegramClient()
    allowed = get_settings().admin_user_ids

    cq = update.get("callback_query")
    if cq:
        user = cq.get("from") or {}
        who = user.get("username") or str(user.get("id"))
        if user.get("id") not in allowed:
            reply = "Not allowed."
            client.answer_callback(cq["id"], reply)
            return reply
        action, _, raw_id = (cq.get("data") or "").partition(":")
        if not raw_id.isdigit():
            client.answer_callback(cq["id"], "Unknown button.")
            return "Unknown button."
        reply = _act(session, action, int(raw_id), who)
        session.flush()
        client.answer_callback(cq["id"], reply)
        msg = cq.get("message") or {}
        if msg.get("message_id") and (reply.startswith("✅") or reply.startswith("❌")):
            try:  # replace the buttons with the outcome so the card can't be pressed twice
                client.edit_reply_markup(msg["chat"]["id"], msg["message_id"],
                                         {"inline_keyboard": [[{"text": reply[:60], "callback_data": "noop:0"}]]})
            except TelegramError:
                pass
        return reply

    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = (msg.get("chat") or {}).get("id")
    if not text or chat_id is None:
        return None
    user_id = (msg.get("from") or {}).get("id")
    cmd = text.split()[0].split("@")[0].lower()
    if cmd == "/start" and user_id not in allowed:
        reply = (f"Hi! Your Telegram user id is {user_id}. To review posts here, set TELEGRAM_ADMIN_CHAT_ID="
                 f"{chat_id} where the app runs.")
    elif user_id not in allowed:
        return None  # ignore strangers
    elif cmd == "/pending":
        n = notify_pending(session, client, limit=5, resend=True)
        reply = "Nothing pending right now." if n == 0 else f"Sent {n} pending item(s)."
        if n:
            return reply
    else:
        reply = HELP
    client.send_message(str(chat_id), escape(reply))
    return reply


def poll(session: Session, client: TelegramClient | None = None) -> int:
    """Fetch and process button presses via getUpdates (use when no webhook is set)."""
    client = client or TelegramClient()
    last = session.scalar(select(EventLog).where(EventLog.event == OFFSET).order_by(EventLog.id.desc()))
    offset = (last.data or {}).get("update_id", 0) + 1 if last else None
    updates = client.get_updates(offset=offset)
    for u in updates:
        handle_update(session, u, client)
    if updates:
        top = max(u["update_id"] for u in updates)
        record_event(session, OFFSET, f"processed Telegram updates up to {top}", update_id=top)
        client.get_updates(offset=top + 1)  # tells Telegram these are done
    return len(updates)
