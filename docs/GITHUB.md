# Running everything from GitHub

| Piece | Where it runs | Cost |
|---|---|---|
| Code + history | GitHub repo | free |
| Nightly research + daily posts (all sports) | GitHub Actions (`.github/workflows/daily.yml`) | free (private repos get 2,000 min/month; one run takes about 5–40 min) |
| Database | Supabase | free tier |
| Admin dashboard (approve / edit) | Render (`render.yaml`), or run it on your laptop | free tier (it sleeps when idle; the first visit takes about 30 seconds) |
| Review from your phone (optional) | a private chat with your bot: Approve / Reject buttons | free |
| Tests on every push | GitHub Actions (`.github/workflows/tests.yml`) | free |

## Steps

1. **Supabase:** create a project, then SQL Editor → paste `db/schema.sql` → Run. Copy the connection string (URI, Session pooler).
2. **Secrets:** GitHub repo → Settings → Secrets and variables → Actions.
   * **Secrets:** `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BASEBALL_CHANNEL_ID` (and `ANTHROPIC_API_KEY` only if you turn on the LLM)
   * **Variables:** `TELEGRAM_JOIN_LINKS` = `baseball=https://t.me/yourchannel`. Leave `DRY_RUN` unset for now.
3. **Check Telegram (optional):** Actions tab → "Daily roster intel" → Run workflow → job `check-telegram`, sport `baseball`. It sends nothing; it confirms the token works, the channel exists and the bot is an admin there.
4. **First run:** Actions tab → "Daily roster intel" → Run workflow → `research`. When it finishes, the opportunities are in your Supabase database.
5. **Dashboard:** render.com → New → Blueprint → pick this repo. Fill in `DATABASE_URL`, `ADMIN_PASSWORD` and the Telegram values. Open the URL Render gives you, then review and approve.
6. **Go live:** add the repository **variable** `DRY_RUN` = `false`, and set `DRY_RUN=false` in Render too. From then on, every morning the workflow posts the best approved item for each sport (at most one per sport per day).

Until `DRY_RUN` is set to `false`, the workflow runs dry: it collects real data but only logs posts and never sends them.

## Review from Telegram instead of the dashboard (optional)

New items can come to a private chat with your bot, each with **✅ Approve** and **❌ Reject** buttons.
Approving there follows the same rules as the dashboard (guardrails; LOW confidence still needs the
dashboard), and approved items go out in their sport's normal daily slot.

1. In Telegram, open your bot and press **Start**. It replies with your chat id. (Or run
   `python -m app.cli telegram-whoami` on your computer.)
2. Add the GitHub **secret** `TELEGRAM_ADMIN_CHAT_ID` = that number (and the same value in Render).
3. That's it. After each research run the new items arrive in the chat. Button presses are collected
   right before the morning post.
4. *Instant buttons (optional, needs the Render dashboard):* in Render set `PUBLIC_BASE_URL` to your
   dashboard's `https://…onrender.com` address (`TELEGRAM_WEBHOOK_SECRET` is generated for you), then
   in the Render **Shell** tab run `python -m app.cli telegram-webhook --set`. Also add the repository
   **variable** `TELEGRAM_USE_WEBHOOK` = `true` so the workflow stops polling.

## Turning on another sport

Every sport is built, but only **baseball** has been checked against real live pages. The others
research and show up for review, but they won't post live until they're verified:

1. Actions → "Daily roster intel" → Run workflow → job `verify`, sport e.g. `softball`.
   It reads the real pages of the schools in `config/programs/softball.csv`, writes nothing and posts
   nothing, and prints what it understood for each school with a verdict: **PASS**, **CHECK** or **FAIL**.
2. Open the run → **Summary** → download the `verify-softball-pages` zip (the pages it read).
3. If it says PASS, send the zip and the log to Claude Code and ask it to add them as test fixtures and
   mark the sport live-verified. If it says CHECK/FAIL, send the same; the log says what didn't match.
4. Create the sport's Telegram channel, add the bot as admin, and add the secret
   (`TELEGRAM_SOFTBALL_CHANNEL_ID`, `TELEGRAM_MBB_CHANNEL_ID`, `TELEGRAM_WBB_CHANNEL_ID`,
   `TELEGRAM_MSOC_CHANNEL_ID`, `TELEGRAM_WSOC_CHANNEL_ID` or `TELEGRAM_FOOTBALL_CHANNEL_ID`).
   Add the sport to the `TELEGRAM_JOIN_LINKS` variable too, e.g.
   `baseball=https://t.me/tam_baseball,softball=https://t.me/tam_softball`.
5. In `config/programs/<sport>.csv`, set `active` to `true` for the schools that passed.

GitHub pauses scheduled workflows after 60 days without a commit to the repo. If the daily
posts stop, open Actions → "Daily roster intel" → **Enable workflow**.
