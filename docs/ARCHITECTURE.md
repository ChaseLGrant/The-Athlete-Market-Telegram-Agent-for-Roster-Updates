# The Athlete Market — Roster Intelligence: Architecture

## 1. What this system does (and does not do)

It reads **official public college rosters and statistics**, computes positional
turnover and returning/departing production with deterministic code, and turns
the strongest findings into **one post per sport per day** in Telegram, plus an
X teaser you copy and post by hand.

It never claims a program "needs" a player, has scholarship money, or is
recruiting a position — unless a Tier A source says so explicitly (🟢 VERIFIED
NEED, entered by an admin with the source URL). Everything the engine infers is
🔵 ROSTER OPPORTUNITY and always carries the disclaimer:

> Roster analysis only. This is not a confirmed recruiting opening from the coaching staff.

When data is missing or doubtful, the system stores `NULL`/`unknown`, lowers
confidence, and prefers to publish nothing.

## 2. Pipeline

```
programs.csv ─► RESEARCH JOB (independent of publishing)
                  │ adapter.fetch_roster()  ─┐  PoliteFetcher: robots.txt, crawl-delay,
                  │ adapter.fetch_stats()   ─┘  per-host rate limit, disk cache
                  ▼
                NORMALIZE  (positions, class year, name/ID matching, stat parsing)
                  ▼
                SPORT ANALYZER (baseball.analyzer) — pure functions, no I/O
                  ▼
                SIGNAL + CONFIDENCE (configurable weights per sport)
                  ▼
                FINGERPRINT / DEDUPE ─► opportunities (+ opportunity_evidence, sources)
                  ▼
ADMIN DASHBOARD: pending → approve / reject / edit / reanalyze
                  ▼
PUBLISH JOB (per sport, at configured local time)
   pick 1 approved item (quality, freshness, variety) ─► REVALIDATE if stale
   ─► Telegram Bot API (or log only in TEST_MODE / DRY_RUN) ─► published_posts
   ─► X teaser stored for manual copy
```

Research and publishing are separate jobs. Research can find 50+ opportunities
per sport; publishing releases about one per sport per day.

## 3. Tech choices

| Concern | Choice | Why |
|---|---|---|
| Jobs + logic | Python 3.11 | Scraping and data work |
| Web / admin | FastAPI + Jinja2 server-rendered pages | One process, no JS build step, easy for a beginner to host |
| DB | PostgreSQL (Supabase in prod). SQLAlchemy 2 models, `db/schema.sql` for Supabase | Relational, cheap, portable |
| Scheduling | APScheduler inside the web process **or** CLI commands run by any cron | Cheapest possible hosting |
| HTML parsing | BeautifulSoup + lxml | Robust to messy markup |
| LLM | Claude, optional, off by default | Only for classifying positions the rules can't handle; never for math or new claims |
| Messaging | Telegram Bot API `sendMessage` (HTML parse mode) | Official, free |

## 4. Folder structure

```
app/
  settings.py            env config (TEST_MODE, DRY_RUN, APP_TIMEZONE, channel IDs…)
  db.py, models.py       SQLAlchemy engine + ORM models (mirror db/schema.sql)
  logging_setup.py       structured event logs (also written to event_log table)
  sports/
    base.py              SportConfig, SportModule (per-sport hooks), PositionGroup, SignalWeights
    registry.py          all 7 sports; `live_verified` marks the ones allowed to post live
    seasons.py           season labels: spring "2026", fall "2025", winter "2025-26"
    baseball/            positions, stats, team_input, analyzer, config (also used by softball)
    generic/             shared engine for usage sports (minutes / starts / yards / tackles)
    basketball.py, soccer.py, football.py   positions, stat columns, measures, weights
  collectors/
    base.py              SourceAdapter interface + RawRoster/RawStats dataclasses
    http.py              PoliteFetcher (robots, crawl-delay, rate-limit, cache)
    sidearm.py           Sidearm Sports adapter (most NCAA athletic sites)
    fixture.py           offline adapter for TEST_MODE / tests
  analysis/              signal scoring, confidence, fingerprinting, name matching
  pipeline/              research.py (collect→store), revalidate.py, workflow.py, verify.py (live check)
  content/               telegram_post.py, x_teaser.py, guardrails.py, llm.py
  publishing/            telegram.py (client), queue.py (selection), service.py,
                         admin_bot.py + webhook.py (private review chat with Approve/Reject buttons)
  admin/                 routes + templates
  main.py                FastAPI app + scheduler
  cli.py                 `python -m app.cli research|publish|revalidate|...`
config/programs/<sport>.csv    programs to watch per sport (active=false until verified)
db/schema.sql            full Postgres schema for Supabase
tests/                   pytest suite + fixtures captured from a real Sidearm site
```

## 5. Database (summary — full DDL in `db/schema.sql`)

| Table | Purpose |
|---|---|
| `schools` | name, slug, division, conference, athletics domain |
| `teams` | school × sport, adapter name, roster/stats URL templates, active flag |
| `seasons` | sport + year label (e.g. baseball 2026) |
| `sources` | every fetched URL: tier (A/B/C), kind, fetched_at, http status, content hash, availability |
| `roster_snapshots` | one collection of a team roster for a season, linked to source |
| `players` | stable per-team identity (site player id when available) |
| `roster_entries` | player on a snapshot: raw + normalized position, class year, eligibility (nullable) |
| `player_stats` | per player/season/stat-type (batting, pitching…), JSONB of parsed stats + raw |
| `opportunities` | fingerprint, type, position, score, confidence, status, timestamps, telegram/X copy |
| `opportunity_evidence` | the numbers + the source rows that justify an opportunity |
| `opportunity_sources` | link table to `sources` |
| `score_history` | every score change with reason |
| `telegram_channels` | sport → env var name holding the channel ID (the ID itself stays in env) |
| `publishing_queue` | one row per sport per day (unique) → an opportunity |
| `published_posts` | telegram message id, text actually sent, status (unique per opportunity+channel) |
| `event_log` | observability: collection/parse failures, LLM failures, publishes, dedupes, stale |

Future tables (`athletes`, `athlete_metrics`, `athlete_preferences`, `matches`,
`coach_submissions`) are intentionally **not** created yet; nothing in the
current schema blocks adding them.

## 6. Source adapter interface

```python
class SourceAdapter(Protocol):
    name: str                       # "sidearm"
    def fetch_roster(self, team: TeamRef, season: str | None) -> RawRoster: ...
    def fetch_stats(self, team: TeamRef, season: str) -> RawStats: ...
```

* `RawRoster` = season label found on the page, list of `RawRosterPlayer`
  (site_player_id, name, jersey, position_raw, class_year_raw, height, weight,
  bats_throws, hometown, high_school, previous_school), and a `SourceRecord`
  (url, tier, fetched_at, http_status, content_hash).
* `RawStats` = tables keyed by type (`batting`, `pitching`, `fielding`), each row
  a dict of column → raw string plus `site_player_id` when present.
* Every adapter uses `PoliteFetcher`, which checks robots.txt, honors
  `Crawl-delay` (Sidearm sites commonly set 30s), identifies itself with a
  descriptive User-Agent, follows redirects itself (re-checking robots.txt on
  every hop and recording where it landed, so a parser can reject a page that
  was redirected elsewhere), caches responses, and **never** bypasses CAPTCHAs,
  logins, paywalls or bot protection. A 401/403/429/robots-disallow (or a robots.txt that answers 429/5xx) marks the
  source `unavailable` and the pipeline moves on.
* New site platforms (PrestoSports, WMT, custom) are added as new adapters; the
  analyzers never see HTML.

## 7. Data models (normalized)

`NormalizedPlayer`: key, name, jersey, position_raw, position_group,
position_confidence (0–1), is_two_way, class_year (FR/SO/JR/SR/GR/UNKNOWN),
redshirt flag, eligibility_remaining (always `None` unless a reliable source
states it), final_year_listed (SR/GR), previous_school, batting stats, pitching stats.

`PositionAnalysis`: position group, roster counts (total/departing/returning),
usage shares departing (starts, PA, IP, GS), production share departing,
returning experienced count, known incoming/transfer counts, list of per-player
evidence rows, data-quality inputs → `signal` (0–100) + `confidence` (LOW/MEDIUM/HIGH).

## 8. Telegram publishing architecture

* One bot, many channels. Channel IDs live in env vars
  (`TELEGRAM_BASEBALL_CHANNEL_ID`, …). The `telegram_channels` table stores only
  the env var name, never the ID or token.
* The bot token is used only server-side in `publishing/telegram.py`.
* `publish_daily(sport)` (`app/publishing/service.py`), the scheduled job:
  1. Skips if the sport already used today's slot (local date in `APP_TIMEZONE`).
     A post whose delivery is `unknown` (network drop mid-send) also uses the slot.
  2. Picks the item scheduled for today, or the best approved one
     (`publishing/queue.py`: signal × confidence, minus freshness/variety penalties).
  3. **Revalidates** if `last_verified_at` is older than `REVALIDATE_AFTER_HOURS`:
     re-fetches sources; if unavailable → blocked; if numbers materially changed →
     back to `pending` for review. A blocked item frees the slot for the next candidate.
  4. Runs guardrails on the exact Telegram text and X teaser.
  5. Live mode: writes a `published_posts` claim (`status='sending'`) and commits it
     *before* calling Telegram, then records the `message_id` and marks the
     opportunity `published`. A network error after the request may have reached
     Telegram leaves the claim as `unknown`, so it is never re-sent automatically.
  6. `TEST_MODE` or `DRY_RUN` → logs the exact post instead of sending.
* `publish_opportunity` (the dashboard's **PUBLISH NOW**) runs steps 3–6 and also
  refuses if the sport already has a post today.
* Idempotency: unique `(opportunity_id, channel_ref, mode)` on `published_posts`, unique
  `(sport, publish_date)` on `publishing_queue`, and the fingerprint prevents
  re-creating the same opportunity.

## 9. Admin approval workflow

```
         research job
              │ creates / updates
              ▼
        ┌──────────┐  reject  ┌──────────┐
        │ pending  │─────────►│ rejected │
        └────┬─────┘          └──────────┘
    approve  │  ▲ reanalyze / material change on revalidation
             ▼  │
        ┌──────────┐ schedule ┌───────────┐ publish job ┌───────────┐
        │ approved │─────────►│ scheduled │────────────►│ published │
        └────┬─────┘          └───────────┘             └───────────┘
             │ publish now ───────────────────────────────────▲
   (any non-published status) ── expires_at passed ──► expired
```

* EDIT changes the Telegram/X copy; guardrails re-run on save and before send.
* REANALYZE re-fetches sources and recomputes; the opportunity returns to
  `pending` if anything material changed.
* Only `approved`/`scheduled` items can be published. `LOW` confidence items can
  be viewed but not approved without ticking an explicit override.

## 10. Implementation plan

| Milestone | Scope | Done when |
|---|---|---|
| M0 | Architecture, schema, methodology | this document + `db/schema.sql` + `docs/BASEBALL_METHODOLOGY.md` |
| M1 | Settings, models, sport registry | tests create schema on Postgres and SQLite |
| M2 | PoliteFetcher + Sidearm adapter | parses real captured Sidearm roster/stats pages |
| M3 | Baseball analyzer, signal, confidence, dedupe | real CSUSM 2026 data produces a catcher opportunity with correct math |
| M4 | Post generation, guardrails, queue, Telegram publisher, revalidation | publish flow tested end-to-end with a mock Telegram server; no double publish |
| M5 | Admin dashboard | every button performs its real workflow (tested with FastAPI TestClient) |
| M6 | Real run + handoff | you add the bot token → first real post to your Baseball channel |
| M7 | Other six sports | softball, basketball, soccer, football analyzers; tested on synthetic pages ✓ |
| M8 | Telegram admin chat | Approve / Reject buttons, webhook + polling ✓ |
| Next | Live verification | `verify` PASS on real schools per sport → fixtures → `live_verified=True` |
| Next | PrestoSports adapter | built from pages captured with `verify --save-pages` / real fixtures |
