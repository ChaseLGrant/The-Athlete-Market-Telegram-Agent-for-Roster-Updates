"""Command line entry points.

  python -m app.cli init-db
  python -m app.cli research [--sport baseball] [--limit 3]
  python -m app.cli publish-daily --sport baseball
  python -m app.cli expire
  python -m app.cli check-telegram [--sport baseball]
  python -m app.cli list [--status pending]
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
    sub.add_parser("expire")
    ct = sub.add_parser("check-telegram")
    ct.add_argument("--sport", default="baseball")
    ls = sub.add_parser("list")
    ls.add_argument("--status", default="pending")
    ls.add_argument("--sport", default="baseball")
    a = p.parse_args(argv)

    create_all()
    if a.cmd == "init-db":
        from app.pipeline.research import ensure_channels, sync_programs

        with session_scope() as s:
            ensure_channels(s)
            n = sync_programs(s, "baseball")
        print(f"Database ready. {n} baseball programs loaded.")
    elif a.cmd == "research":
        from app.pipeline import workflow
        from app.pipeline.research import run_research

        with session_scope() as s:
            results = run_research(s, a.sport, limit=a.limit)
            workflow.expire_stale(s)
        for res in results:
            print(f"{'OK ' if res.ok else 'SKIP'} {res.school}: {res.message} "
                  f"{'→ opportunities ' + str(res.opportunity_ids) if res.opportunity_ids else ''}")
    elif a.cmd == "publish-daily":
        from app.pipeline import workflow
        from app.publishing.service import publish_daily

        with session_scope() as s:
            workflow.expire_stale(s)
            out = publish_daily(s, a.sport)
        print(f"{out.status}: {out.message}")
        return 0 if out.ok or out.status == "skipped" else 1
    elif a.cmd == "expire":
        from app.pipeline import workflow

        with session_scope() as s:
            print(f"expired {workflow.expire_stale(s)}")
    elif a.cmd == "check-telegram":
        return check_telegram(a.sport)
    elif a.cmd == "list":
        with session_scope() as s:
            for o in s.scalars(select(Opportunity).where(Opportunity.status == a.status, Opportunity.sport == a.sport)
                               .order_by(Opportunity.signal.desc())):
                print(f"#{o.id:<4} {o.signal:5.1f} {o.confidence:<6} {o.school.name} — {o.position_label}")
    return 0


def check_telegram(sport: str) -> int:
    from app.publishing.telegram import TelegramClient, TelegramError

    s = get_settings()
    if not s.telegram_bot_token:
        print("✗ TELEGRAM_BOT_TOKEN is empty in .env")
        return 1
    c = TelegramClient()
    try:
        me = c.get_me()
        print(f"✓ Bot token works: @{me.get('username')}")
    except TelegramError as e:
        print(f"✗ {e}")
        return 1
    chat = s.channel_id_for(sport)
    var = s.channel_env_var(sport)
    if not chat:
        print(f"✗ {var} is empty in .env")
        return 1
    try:
        info = c.get_chat(chat)
        print(f"✓ Channel found: {info.get('title')} ({info.get('type')})")
        m = c.get_my_member_status(chat)
        ok = m.get("status") == "administrator" and m.get("can_post_messages", True)
        print(("✓" if ok else "✗") + f" Bot status in channel: {m.get('status')}"
              + ("" if ok else " — make the bot an admin with 'Post messages' permission"))
        return 0 if ok else 1
    except TelegramError as e:
        print(f"✗ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
