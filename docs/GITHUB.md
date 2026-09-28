# Running everything from GitHub

| Piece | Where it runs | Cost |
|---|---|---|
| Code + history | GitHub repo | free |
| Nightly research + daily post | GitHub Actions (`.github/workflows/daily.yml`) | free (private repos get 2,000 min/month; one run takes about 5–30 min) |
| Database | Supabase | free tier |
| Admin dashboard (approve / edit) | Render (`render.yaml`), or run it on your laptop | free tier (it sleeps when idle; the first visit takes about 30 seconds) |
| Tests on every push | GitHub Actions (`.github/workflows/tests.yml`) | free |

## Steps

1. **Supabase:** create a project, then SQL Editor → paste `db/schema.sql` → Run. Copy the connection string (URI, Session pooler).
2. **Secrets:** GitHub repo → Settings → Secrets and variables → Actions.
   * **Secrets:** `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BASEBALL_CHANNEL_ID` (and `ANTHROPIC_API_KEY` only if you turn on the LLM)
   * **Variables:** `TELEGRAM_JOIN_LINKS` = `baseball=https://t.me/yourchannel`. Leave `DRY_RUN` unset for now.
3. **First run:** Actions tab → "Daily roster intel" → Run workflow → `research`. When it finishes, the opportunities are in your Supabase database.
4. **Dashboard:** render.com → New → Blueprint → pick this repo. Fill in `DATABASE_URL`, `ADMIN_PASSWORD` and the Telegram values. Open the URL Render gives you, then review and approve.
5. **Go live:** add the repository **variable** `DRY_RUN` = `false`, and set `DRY_RUN=false` in Render too. From then on, every morning the workflow posts the best approved item (at most one per day).

Until `DRY_RUN` is set to `false`, the workflow runs dry: it collects real data but only logs posts and never sends them.
