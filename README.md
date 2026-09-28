# The Athlete Market — Roster Intelligence

Reads **official college rosters and stats**, finds positions where a program may be
losing most of its playing time, and posts **one roster opportunity per sport per day**
to Telegram. It also writes an X teaser for you to copy.

Everything it infers is labeled 🔵 ROSTER OPPORTUNITY and carries:

> Roster analysis only. This is not a confirmed recruiting opening from the coaching staff.

**Status:** Baseball works end to end. The other six sports are registered (channels,
queue, config) and their analyzers come next.

| Doc | What's in it |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | **Start here.** Step-by-step setup: Telegram bot, `.env`, running it, going live |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, database, adapters, publishing, approval workflow, plan |
| [docs/BASEBALL_METHODOLOGY.md](docs/BASEBALL_METHODOLOGY.md) | Exactly how the Opportunity Signal and confidence are calculated |
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
python -m app.cli research [--sport baseball] [--limit 5]   # collect + analyze (safe to re-run)
python -m app.cli list --status pending
python -m app.cli publish-daily --sport baseball             # today's post (max 1/day/sport)
python -m app.cli check-telegram --sport baseball            # verify bot + channel setup
python -m app.cli expire                                     # expire stale items
python -m pytest                                             # 84 tests
```

## Safety switches

| `.env` | Collects real data? | Sends to Telegram? | Marks published? |
|---|---|---|---|
| `TEST_MODE=true` | no (saved pages) | no (logged) | yes (so you can see the whole flow) |
| `DRY_RUN=true` | yes | no (logged) | no |
| both `false` | yes | **yes** | yes |
