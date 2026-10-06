"""Command line entry points. `--sport all` works for research and publish-daily.

  python -m app.cli init-db
  python -m app.cli research [--sport baseball|all] [--limit 3]
  python -m app.cli publish-daily --sport baseball|all
  python -m app.cli verify --sport softball [--school csusm] [--save-pages captured/]
  python -m app.cli discover --sport baseball [--limit 60] [--probe]   # add schools from the NCAA directory
  python -m app.cli expire
  python -m app.cli list [--status pending] [--sport baseball]
  python -m app.cli check-telegram [--sport baseball]
  python -m app.cli telegram-whoami            # find your chat id for TELEGRAM_ADMIN_CHAT_ID
  python -m app.cli telegram-poll              # process Approve/Reject presses (no webhook needed)
  python -m app.cli telegram-webhook --set|--delete
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from app.db import create_all, session_scope  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402
from app.models import Opportunity  # noqa: E402
from app.settings import get_settings  # noqa: E402
from app.sports.registry import registry  # noqa: E402


def _sports(arg: str, *, only_enabled: bool = False) -> list[str]:
    """only_enabled: skip sports switched off with ENABLED_SPORTS (for crawling and posting commands)."""
    on = get_settings().sport_enabled if only_enabled else (lambda k: True)
    if arg == "all":
        return [k for k in registry() if on(k)]
    if arg == "live":  # sports allowed to post live (verified on real pages)
        return [k for k, c in registry().items() if c.live_verified and on(k)]
    if arg in registry() and not on(arg):
        print(f"{arg} is switched off (ENABLED_SPORTS); nothing to do.")
        return []
    if arg not in registry():
        raise SystemExit(f"Unknown sport '{arg}'. Use one of: all, live, {', '.join(registry())}")
    return [arg]


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    p = argparse.ArgumentParser(prog="roster-intel")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    r = sub.add_parser("research")
    r.add_argument("--sport", default="baseball")
    r.add_argument("--limit", type=int)
    pd = sub.add_parser("publish-daily")
    pd.add_argument("--sport", default="baseball")
    v = sub.add_parser("verify")
    v.add_argument("--sport", required=True)
    v.add_argument("--school", help="only this program slug from the CSV")
    v.add_argument("--save-pages", help="folder to save the fetched pages (fixture format)")
    v.add_argument("--from-directory", type=int, default=0,
                   help="also check this many random schools from the NCAA directory")
    dv = sub.add_parser("discover")
    dv.add_argument("--sport", default="baseball")
    dv.add_argument("--probe", action="store_true", help="only print what the NCAA directory returns")
    dv.add_argument("--limit", type=int, default=60, help="max new schools to check this run")
    dv.add_argument("--workers", type=int, default=8, help="schools checked at the same time")
    sub.add_parser("expire")
    ct = sub.add_parser("check-telegram")
    ct.add_argument("--sport", default="baseball")
    ls = sub.add_parser("list")
    ls.add_argument("--status", default="pending")
    ls.add_argument("--sport", default="baseball")
    sub.add_parser("telegram-whoami")
    sub.add_parser("telegram-poll")
    wh = sub.add_parser("telegram-webhook")
    g = wh.add_mutually_exclusive_group(required=True)
    g.add_argument("--set", action="store_true")
    g.add_argument("--delete", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "verify":  # reads live pages only; no database needed
        from app.pipeline.verify import run_verify

        reports = run_verify(_sports(a.sport)[0], school=a.school, save_dir=a.save_pages,
                             from_directory=a.from_directory)
        return 0 if reports and all(r.verdict == "PASS" for r in reports) else 1
    if a.cmd == "discover" and a.probe:
        from app.pipeline.discover import probe

        return probe(_sports(a.sport)[0])
    if a.cmd == "check-telegram":
        return check_telegram(a.sport)
    if a.cmd == "telegram-whoami":
        return telegram_whoami()
    if a.cmd == "telegram-webhook":
        return telegram_webhook(a.set)

    create_all()
    if a.cmd == "discover":
        from app.pipeline.discover import discover

        from app.collectors.base import SourceUnavailable

        for sport in _sports(a.sport, only_enabled=True):
            try:
                with session_scope() as s:
                    counts = discover(s, sport, limit=a.limit, workers=a.workers)
            except SourceUnavailable as e:
                # e.g. the NCAA directory's robots.txt refused us (seen 2026-10-01). We never work around that;
                # finding new schools just waits for another night, and research still runs.
                print(f"[{sport}] couldn't read the NCAA directory ({e.reason}); no new schools tonight")
                continue
            print(f"[{sport}] added {counts['PASS']}, needs a look {counts['CHECK']}, unreadable {counts['FAIL']}")
        return 0
    if a.cmd == "init-db":
        from app.pipeline.research import ensure_channels, sync_programs

        with session_scope() as s:
            ensure_channels(s)
            counts = {k: sync_programs(s, k) for k in registry()}
        print("Database ready. Programs loaded: " + ", ".join(f"{k} {n}" for k, n in counts.items()))
    elif a.cmd == "research":
        from app.pipeline import workflow
        from app.pipeline.research import run_research
        from app.publishing import admin_bot

        for sport in _sports(a.sport, only_enabled=True):
            with session_scope() as s:
                results = run_research(s, sport, limit=a.limit)
                workflow.expire_stale(s)
            for res in results:
                print(f"{'OK ' if res.ok else 'SKIP'} [{sport}] {res.school}: {res.message} "
                      f"{'→ opportunities ' + str(res.opportunity_ids) if res.opportunity_ids else ''}")
        if admin_bot.enabled() and not get_settings().test_mode:
            with session_scope() as s:
                n = admin_bot.notify_pending(s)
            print(f"Sent {n} new item(s) to the Telegram admin chat.")
    elif a.cmd == "publish-daily":
        from app.pipeline import workflow
        from app.publishing.service import current_mode, publish_daily

        s_ = get_settings()
        failed = False
        for sport in _sports(a.sport, only_enabled=True):
            if a.sport == "all" and current_mode() == "live" and not s_.channel_id_for(sport):
                print(f"skip [{sport}]: {s_.channel_env_var(sport)} is not set")
                continue
            with session_scope() as s:
                workflow.expire_stale(s)
                out = publish_daily(s, sport)
            print(f"{out.status} [{sport}]: {out.message}")
            failed |= not (out.ok or out.status == "skipped")
        return 1 if failed else 0
    elif a.cmd == "expire":
        from app.pipeline import workflow

        with session_scope() as s:
            print(f"expired {workflow.expire_stale(s)}")
    elif a.cmd == "telegram-poll":
        from app.publishing import admin_bot

        if not admin_bot.enabled():
            print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID first.")
            return 1
        with session_scope() as s:
            print(f"processed {admin_bot.poll(s)} Telegram update(s)")
    elif a.cmd == "list":
        with session_scope() as s:
            for o in s.scalars(select(Opportunity).where(Opportunity.status == a.status, Opportunity.sport == a.sport)
                               .order_by(Opportunity.signal.desc())):
                print(f"#{o.id:<4} {o.signal:5.1f} {o.confidence:<6} {o.school.name} — {o.position_label}")
    return 0


def check_telegram(sport: str) -> int:
    """Check the bot token, then each sport's channel/group (sport='all' checks every one that is set).
    Sends nothing."""
    from app.publishing.telegram import TelegramClient, TelegramError

    s = get_settings()
    if not s.telegram_bot_token:
        print("✗ TELEGRAM_BOT_TOKEN is empty (GitHub secret TELEGRAM_BOT_TOKEN or TELEGRAM_BOT)")
        return 1
    c = TelegramClient()
    try:
        me = c.get_me()
        print(f"✓ Bot token works: @{me.get('username')}")
    except TelegramError as e:
        print(f"✗ {e}")
        return 1
    sports = _sports(sport)
    ok_all, checked = True, 0
    for key in sports:
        chat = s.channel_id_for(key)
        var = s.channel_env_var(key)
        name = registry()[key].display_name
        if not chat:
            if sport != "all":
                print(f"✗ {name}: {var} is empty")
                ok_all = False
            else:
                print(f"- {name}: not set (skipped)")
            continue
        checked += 1
        if chat.startswith("invite-link:"):
            print(f"✗ {name}: that's a private invite link, which can't be used as an id. Make the group public "
                  f"and use @its_link_name, or use the numeric id (see the telegram-chats job).")
            ok_all = False
            continue
        try:
            info = c.get_chat(chat)
            m = c.get_my_member_status(chat)
            admin = m.get("status") in ("administrator", "creator")
            can_post = m.get("can_post_messages", True) is not False
            ok = admin and can_post
            print(("✓" if ok else "✗") + f" {name}: found '{info.get('title')}' ({info.get('type')}), bot is "
                  f"{m.get('status')}" + ("" if ok else " — make the bot an admin that can post messages"))
            ok_all &= ok
        except TelegramError as e:
            shape = ("@name" if chat.startswith("@") else "number" if chat.lstrip("-").isdigit() else "other text")
            print(f"✗ {name}: {e} (value looks like: {shape}). Use the group's public @link_name, or its numeric "
                  f"id, and make sure @{me.get('username')} is a member/admin there.")
            ok_all = False
    if sport == "all" and checked == 0:
        print("✗ No channel/group ids are set yet")
        ok_all = False
    if s.telegram_admin_chat_id:
        try:
            c.get_chat(s.telegram_admin_chat_id)
            print("✓ Admin chat reachable (TELEGRAM_ADMIN_CHAT_ID)")
        except TelegramError as e:
            print(f"✗ Admin chat: {e} — open your bot in Telegram and press Start first")
            ok_all = False
    return 0 if ok_all else 1


def telegram_whoami() -> int:
    """List the chats the bot recently saw (private chats, groups, channels) with their exact ids,
    so you can fill in TELEGRAM_<SPORT>_CHANNEL_ID / TELEGRAM_ADMIN_CHAT_ID. Telegram keeps these
    for 24 hours, so add the bot to a group (or post in it) shortly before running this."""
    from app.publishing.telegram import TelegramClient, TelegramError

    try:
        updates = TelegramClient().get_updates(
            allowed=["message", "channel_post", "my_chat_member", "callback_query"])
    except TelegramError as e:
        print(f"✗ {e}\n(If a webhook is set, run: python -m app.cli telegram-webhook --delete)")
        return 1
    seen: dict[int, dict] = {}
    for u in updates:
        for key in ("message", "channel_post", "my_chat_member"):
            item = u.get(key) or {}
            chat = item.get("chat")
            if not chat:
                continue
            info = seen.setdefault(chat["id"], {"type": chat.get("type", "?"), "status": ""})
            info["name"] = chat.get("title") or chat.get("username") or (item.get("from") or {}).get("username") or ""
            if chat.get("username"):
                info["public"] = "@" + chat["username"]
            if key == "my_chat_member":
                info["status"] = (item.get("new_chat_member") or {}).get("status", "")
    if not seen:
        print("Nothing seen in the last 24 hours. Add the bot to your groups/channels (or send a message\n"
              "in them, or press Start in a private chat with the bot), then run this again.")
        return 1
    print("Chats your bot can see (use the id on the right as the secret's value):")
    for chat_id, i in seen.items():
        status = f", bot is {i['status']}" if i["status"] else ""
        public = f"  (or {i['public']})" if i.get("public") else ""
        print(f"  {i['type']:<10} {i['name'][:40]:<40}{status}  →  {chat_id}{public}")
    return 0


def telegram_webhook(set_it: bool) -> int:
    from app.publishing.telegram import TelegramClient, TelegramError

    s = get_settings()
    c = TelegramClient()
    try:
        if not set_it:
            c.delete_webhook()
            print("✓ Webhook removed (use telegram-poll to process button presses).")
            return 0
        if not s.telegram_webhook_secret or not s.public_base_url.startswith("https://"):
            print("✗ Set TELEGRAM_WEBHOOK_SECRET (any long random text) and PUBLIC_BASE_URL (your https "
                  "dashboard address, e.g. https://tam-roster-intel-admin.onrender.com) first.")
            return 1
        url = s.public_base_url.rstrip("/") + "/telegram/webhook"
        c.set_webhook(url, s.telegram_webhook_secret)
        print(f"✓ Webhook set: {url}")
        return 0
    except TelegramError as e:
        print(f"✗ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
