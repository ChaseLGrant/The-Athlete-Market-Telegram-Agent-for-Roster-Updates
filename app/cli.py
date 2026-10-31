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


def _sports(arg: str, *, only_enabled: bool = False, research: bool = False) -> list[str]:
    """only_enabled: skip sports switched off with ENABLED_SPORTS (for crawling and posting commands).
    research=True also allows RESEARCH_ONLY_SPORTS (crawl + analyze for Insider Plus, never post)."""
    st = get_settings()
    on = (st.sport_researched if research else st.sport_enabled) if only_enabled else (lambda k: True)
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
    sc = sub.add_parser("sync-conferences")  # each team's conference for its sport, from the NCAA directory
    sc.add_argument("--sport", default="all")
    sub.add_parser("expire")
    ct = sub.add_parser("check-telegram")
    ct.add_argument("--sport", default="baseball")
    ls = sub.add_parser("list")
    ls.add_argument("--status", default="pending")
    ls.add_argument("--sport", default="baseball")
    ex = sub.add_parser("export-posts")
    ex.add_argument("--out", default="exports/posts.json")
    ex.add_argument("--days", type=int, default=14)
    eo = sub.add_parser("export-opportunities")
    eo.add_argument("--out", default="exports/opportunities.json")
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
    if a.cmd == "export-posts":
        return export_posts(a.out, a.days)
    if a.cmd == "export-opportunities":
        return export_opportunities(a.out)
    if a.cmd == "discover":
        from app.pipeline.discover import discover

        from app.collectors.base import SourceUnavailable

        for sport in _sports(a.sport, only_enabled=True, research=True):
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
    if a.cmd == "sync-conferences":
        from app.collectors.base import SourceUnavailable
        from app.pipeline.discover import sync_conferences

        for sport in _sports(a.sport, only_enabled=True, research=True):
            try:
                with session_scope() as s:
                    sync_conferences(s, sport)
            except (SourceUnavailable, ValueError) as e:
                print(f"[{sport}] couldn't read the NCAA directory ({getattr(e, 'reason', e)}); conferences unchanged")
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

        for sport in _sports(a.sport, only_enabled=True, research=True):
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


def export_posts(out: str, days: int) -> int:
    """Write the posts that really went to Telegram in the last `days` days to a JSON file, newest first.
    The Athlete Market's email digest reads this file and sends the same posts to Insider subscribers."""
    import json
    import os
    from datetime import datetime, timedelta, timezone

    from app.models import PublishedPost

    since = datetime.now(timezone.utc) - timedelta(days=days)
    tz = get_settings().tz
    rows = []
    with session_scope() as s:
        for p in s.scalars(select(PublishedPost).where(PublishedPost.status == "sent")):
            sent = p.sent_at if p.sent_at.tzinfo else p.sent_at.replace(tzinfo=timezone.utc)
            if p.mode != "live" or sent < since:
                continue
            rows.append({"id": p.id, "sport": p.sport, "sent_at": sent.isoformat(),
                         "local_date": sent.astimezone(tz).date().isoformat(),
                         "telegram_message_id": p.telegram_message_id, "text_html": p.text or ""})
    rows.sort(key=lambda r: r["sent_at"], reverse=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "posts": rows}, f, indent=1)
    print(f"Exported {len(rows)} post(s) to {out}")
    return 0


def export_opportunities(out: str) -> int:
    """Write every current (not rejected/expired) roster opportunity, with its evidence and sources, plus
    per-sport/division coverage counts, to a JSON file. Read by Recruiting Insider Plus (weekly
    position-matched reports). Reads only; changes nothing in the database."""
    import json
    import os
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.orm import selectinload

    from sqlalchemy import func

    from app.models import RosterSnapshot, School, Status, Team
    from app.pipeline.opportunities import render_content
    from app.sports.registry import get_sport

    def iso(d):
        return d.isoformat() if d else None

    rows = []
    with session_scope() as s:
        q = (select(Opportunity)
             .where(Opportunity.status.notin_([Status.REJECTED, Status.EXPIRED]))
             .options(selectinload(Opportunity.school), selectinload(Opportunity.team),
                      selectinload(Opportunity.evidence), selectinload(Opportunity.sources)))
        # newest successful roster read per team: an item analyzed well before it was not re-produced by the
        # team's latest research (its group no longer qualifies or no longer exists), so it is not current
        last_roster = dict(s.execute(select(RosterSnapshot.team_id, func.max(RosterSnapshot.collected_at))
                                     .group_by(RosterSnapshot.team_id)).all())
        not_current = gate_failed = 0
        for o in s.scalars(q):
            sc, tm = o.school, o.team
            lr, la = last_roster.get(o.team_id), o.last_analyzed_at
            if lr and la:
                lr = lr if lr.tzinfo else lr.replace(tzinfo=timezone.utc)
                la = la if la.tzinfo else la.replace(tzinfo=timezone.utc)
            # 12 h: one research batch stamps its analyses with the batch start, its snapshots as it goes
            if lr and la and lr - la > timedelta(hours=12):
                not_current += 1
                continue
            m = o.metrics or {}
            try:
                min_sig = get_sport(o.sport).min_candidate_signal
            except Exception:  # noqa: BLE001 - unknown sport: keep the stored decision
                min_sig = 0
            # a PUBLISHED item stays published when a re-analysis fails the gates; paid reports leave it out
            if (m.get("gates_passed") is False or (o.signal or 0) < min_sig
                    or ("departing_count" in m and not m["departing_count"])
                    or (m.get("restock_ratio") or 0) >= 1.0):  # newcomers already fill it (gate since 2026-10-31)
                gate_failed += 1
                continue
            try:  # the post text as of the latest analysis (a published item keeps the text that was sent)
                report_text = render_content(o, list(o.sources), sc.name, sc.division)[0]
            except Exception:  # noqa: BLE001 - fall back to the stored text
                report_text = None
            rows.append({
                "report_text": report_text,
                "id": o.id, "sport": o.sport, "type": o.opportunity_type, "status": o.status,
                "school": sc.name, "school_slug": sc.slug, "division": sc.division,
                "conference": (tm.conference if tm and tm.conference else sc.conference),
                "state": sc.state, "position_group": o.position_group, "position_label": o.position_label,
                "target_season": o.target_season, "roster_season": o.roster_season,
                "stats_season": o.stats_season, "departure_basis": o.departure_basis,
                "signal": o.signal, "confidence": o.confidence, "data_quality": o.data_quality,
                "metrics": o.metrics, "reason": o.reason, "telegram_text": o.telegram_text,
                "evidence": [{"kind": e.kind, "label": e.label, **({} if e.kind == "summary" else {"data": e.data})}
                             for e in o.evidence],
                "sources": [{"url": x.url, "kind": x.kind, "tier": x.tier, "title": x.title,
                             "season": x.season_label, "fetched_at": iso(x.fetched_at)} for x in o.sources],
                "coach": {"name": tm.coach_name, "title": tm.coach_title, "email": tm.coach_email,
                          "source_url": tm.coach_source_url} if tm and tm.coach_email else None,
                "first_detected_at": iso(o.first_detected_at), "last_verified_at": iso(o.last_verified_at),
                "last_analyzed_at": iso(o.last_analyzed_at), "team_id": o.team_id,
                "expires_at": iso(o.expires_at),
            })
        # Drop items the team's latest analysis no longer produces (e.g. an old merged "INF" group after the
        # infield split, 2026-10-30): an item counts only if it was analyzed within a day of the team's newest.
        newest: dict = {}
        for r in rows:
            if r["last_analyzed_at"]:
                newest[r["team_id"]] = max(newest.get(r["team_id"], ""), r["last_analyzed_at"])
        before = len(rows)
        rows = [r for r in rows if not r["last_analyzed_at"] or not newest.get(r["team_id"]) or
                datetime.fromisoformat(newest[r["team_id"]]) - datetime.fromisoformat(r["last_analyzed_at"])
                <= timedelta(days=1)]
        dropped = before - len(rows)
        cov = Counter()
        for t, sch in s.execute(select(Team, School).join(School, Team.school_id == School.id)
                                .where(Team.active.is_(True))):
            cov[f"{t.sport}|{sch.division or 'unknown'}"] += 1
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(rows),
                   "active_teams": dict(sorted(cov.items())), "opportunities": rows}, f, default=str)
    print(f"Exported {len(rows)} opportunities to {out} ({dropped} superseded by a newer analysis, "
          f"{not_current} not re-produced by the team's latest research, {gate_failed} failing the gates "
          f"left out)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

