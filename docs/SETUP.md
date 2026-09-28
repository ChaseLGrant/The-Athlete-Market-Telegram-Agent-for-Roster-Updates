# Setup guide (step by step)

You'll do this once. Allow about 30 minutes. Never paste secrets (bot token,
passwords, API keys) into chat. They go only in the `.env` file on your computer
or your host.

---

## 1. Install Python and the project

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/.
   On Windows, tick **"Add python.exe to PATH"** on the first installer screen.
2. Get the code: download it from GitHub (Code → Download ZIP) and unzip it, or use `git clone`.
3. Open a terminal **in the project folder**. On Windows: open the folder, click the address bar, type `cmd`, press Enter.
4. Run:

```bash
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Mac/Linux: cp .env.example .env
```

5. Open `.env` in Notepad and set `ADMIN_PASSWORD` to a long random password.

## 2. Try it in TEST MODE (nothing is sent anywhere)

```bash
python -m app.cli init-db
python -m app.cli research
uvicorn app.main:app
```

Open http://localhost:8000 and log in as `admin` with your password. You should see
**Cal State San Marcos — Catcher** under Pending. That result comes from real CSUSM
pages saved on 2026-09-28. Click it, check the evidence, then click **APPROVE** and
**PUBLISH NOW**. In test mode the post is logged, not sent. Press `Ctrl+C` in the
terminal to stop the server.

## 3. Create the Telegram bot

1. In Telegram, open a chat with **@BotFather** (it has the blue verified check).
2. Send `/newbot`. Name it e.g. `The Athlete Market Roster Bot`, and give it a username ending in `bot`, e.g. `tam_roster_bot`.
3. BotFather replies with a **token** like `123456:ABC...`. Put it in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   ```
   Don't share this token. If it leaks, send `/revoke` to BotFather.

## 4. Create the channels and add the bot

For each sport (start with Baseball):

1. Telegram → New Channel → name it **The Athlete Market | Baseball**.
2. Make it **Public** and pick a link, e.g. `t.me/tam_baseball`. Public channels are easiest because the ID is just `@tam_baseball`.
3. Channel → Administrators → Add Admin → search for your bot's username → turn on **only "Post Messages"** and turn everything else off → Save.
4. In `.env`:
   ```
   TELEGRAM_BASEBALL_CHANNEL_ID=@tam_baseball
   TELEGRAM_JOIN_LINKS=baseball=https://t.me/tam_baseball
   ```
   For a *private* channel, the ID is a number like `-1001234567890`. To find it,
   post something in the channel, forward that post to **@userinfobot**, and copy
   the number it shows for the forwarded chat.
5. Check the setup:
   ```bash
   python -m app.cli check-telegram --sport baseball
   ```
   You want three ✓ lines: token works, channel found, bot is administrator.

## 5. Real data, without sending anything (DRY RUN)

In `.env`:

```
TEST_MODE=false
DRY_RUN=true
```

Delete `roster_intel.db` so test-mode records don't mix with real ones, then:

```bash
python -m app.cli init-db
python -m app.cli research
```

This collects the live CSUSM roster and stats. The crawler is slow on purpose,
because the site's robots.txt asks for 30 seconds between requests. Review the
result in the dashboard.

## 6. Go live

```
TEST_MODE=false
DRY_RUN=false
```

Restart the server, open the opportunity, **APPROVE**, then **PUBLISH NOW**. The post
appears in your Baseball channel and the item moves to **Published**. It can't be
sent again. Copy the X teaser from the same page and post it on X by hand.

## 7. Run it every day automatically

Pick one:

* **Built-in scheduler.** Set `ENABLE_SCHEDULER=true` and keep `uvicorn app.main:app`
  running. Research runs at `RESEARCH_CRON_HOUR` and posts go out at `PUBLISH_TIMES`,
  both in `APP_TIMEZONE`.
* **Your computer's scheduler.** Windows Task Scheduler (or cron on Mac/Linux) runs
  `python -m app.cli research` nightly and
  `python -m app.cli publish-daily --sport baseball` each morning.

Only **approved** items are ever published. If nothing is approved, nothing is posted.

## 8. Move the database to Supabase (optional, for hosting)

1. Create a project at https://supabase.com.
2. Supabase → SQL Editor → paste all of `db/schema.sql` → Run.
3. Project Settings → Database → Connection string → **URI** (Session pooler). Put it in `.env`:
   ```
   DATABASE_URL=postgresql://postgres.xxxx:YOUR-DB-PASSWORD@aws-0-us-west-1.pooler.supabase.com:5432/postgres
   ```

## 9. Add more programs

Edit `config/programs/baseball.csv`. Each program needs one line:

```
slug,name,short_name,division,conference,state,adapter,base_url,sport_path,active
ucsd,UC San Diego,UCSD,NCAA D1,Big West,CA,sidearm,https://ucsdtritons.com,baseball,true
```

`adapter=sidearm` covers sites whose roster lives at `<base_url>/sports/baseball/roster`
(most NCAA sites). Run `python -m app.cli research`. A school whose site can't be read
shows `SKIP ... parse failed` or `source unavailable`. That is expected: the system
skips it instead of guessing. Add a few schools at a time rather than hundreds.
