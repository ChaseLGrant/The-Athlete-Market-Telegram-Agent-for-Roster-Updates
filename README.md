# The Athlete Market — Roster Intelligence

Reads **official college rosters and stats**, finds positions where a program may be
losing most of its playing time, and posts **one roster opportunity per sport per day**
to Telegram. It also writes an X teaser for you to copy.

Everything it infers is labeled 🔵 ROSTER OPPORTUNITY and carries:

> Roster analysis only. This is not a confirmed recruiting opening from the coaching staff.

**Status:** All seven sports are built. Baseball is verified on real pages and can post live.
Softball, basketball (M/W), soccer (M/W) and football research and can be reviewed, but post live only
after `verify` checks them on real pages (see [docs/GITHUB.md](docs/GITHUB.md#turning-on-another-sport)).
New items can also be approved from a private Telegram chat with buttons.

| Doc | What's in it |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | **Start here.** Step-by-step setup: Telegram bot, `.env`, running it, going live |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, database, adapters, publishing, approval workflow, plan |
| [docs/BASEBALL_METHODOLOGY.md](docs/BASEBALL_METHODOLOGY.md) | Exactly how the Opportunity Signal and confidence are calculated |
| [docs/SPORTS_METHODOLOGY.md](docs/SPORTS_METHODOLOGY.md) | Softball, basketball, soccer and football: what each measures |
| [docs/GITHUB.md](docs/GITHUB.md) | Run the daily jobs on GitHub Actions + dashboard on Render |
| [db/schema.sql](db/schema.sql) | Postgres/Supabase schema |

## Quick start (test mode, no accounts needed)

```bash
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
# edit .env: set ADMIN_PASSWORD
python -m app.cli init-db
python -m app.cli research      # uses saved real CSUSM pages in TEST_MODE
uvicorn app.main:app            # open http://localhost:8000  (user: admin)
```

## Commands

```bash
python -m app.cli research [--sport baseball|all] [--limit 5]   # collect + analyze (safe to re-run)
python -m app.cli list --status pending [--sport softball]
python -m app.cli publish-daily --sport baseball|all            # today's post (max 1/day/sport)
python -m app.cli verify --sport softball [--save-pages dir/]   # check page reading on live sites
python -m app.cli check-telegram --sport baseball               # verify bot + channel setup
python -m app.cli telegram-whoami | telegram-poll | telegram-webhook --set   # review chat
python -m app.cli expire                                     # expire stale items
python -m pytest                                             # all tests (SQLite; set TEST_DATABASE_URL for Postgres)
```

## Safety switches

| `.env` | Collects real data? | Sends to Telegram? | Marks published? |
|---|---|---|---|
| `TEST_MODE=true` | no (saved pages) | no (logged) | yes (so you can see the whole flow) |
| `DRY_RUN=true` | yes | no (logged) | no |
| both `false` | yes | **yes** | yes |
