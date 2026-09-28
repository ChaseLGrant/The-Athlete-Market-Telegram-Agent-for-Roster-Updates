# Baseball Opportunity Signal — Methodology (v1)

All math here is done by ordinary Python in `app/sports/baseball/analyzer.py` and
`app/analysis/`. No LLM touches these numbers. Every weight and threshold lives
in `app/sports/baseball/config.py` so it can be tuned without code changes
elsewhere. Other sports get their own config and analyzer.

**The signal ranks what is worth a human look. It is not proof that a roster
spot exists.**

## 1. Inputs

| Input | Source | Notes |
|---|---|---|
| Roster: name, site player id, jersey, position, class year, B/T, previous school | Official roster page (Tier A) | Season label is read from the page title |
| Batting: GP-GS, AB, BB, HBP, SF, SH, TB, H, 2B, 3B, HR, AVG, OBP, SLG, OPS | Official cumulative stats (Tier A) | "Totals"/"Opponents" rows ignored |
| Pitching: APP-GS, IP, ERA, WHIP, SO, BB, SV, W-L | Official cumulative stats (Tier A) | IP converted to outs (61.1 → 184 outs) |

Stats rows are matched to roster players by **site player id** first (Sidearm
puts the same `data-player-id` on both pages), then by normalized name + jersey.
Unmatched stats rows are counted and lower data quality; they are never guessed.

## 2. Position groups

| Group | Roster strings |
|---|---|
| C | C, Catcher |
| MIF | SS, 2B, MIF |
| CIF | 1B, 3B, CIF |
| INF | INF, IF, Infielder — and **all infielders combined** when any infielder is listed generically (we can't split generic "INF" into middle/corner honestly) |
| OF | OF, LF, CF, RF |
| UT | UT, UTL (counted for depth only, low position confidence) |
| RHP / LHP | RHP, LHP; plain "P" uses the Throws column, else unknown-handed |

Multi-position strings (`INF/RHP`, `RHP/1B`) → first token is the primary group,
the pitcher token puts the player in a pitching group too (`is_two_way = true`).
Position confidence: exact position 1.0 · generic (INF, P with throws) 0.8 ·
multi-position 0.7 · UT / unknown-handed P 0.5.

Starter vs reliever is **derived from stats** (GS/APP ≥ 0.5 → starter) and
reported in evidence (e.g. share of starter innings departing).

## 3. Departure status (per player)

| Status | When | Wording used publicly |
|---|---|---|
| `final_year_listed` | Roster season = stats season and class is SR, R-SR, GR, 5th | "listed as seniors/graduate students" / "potentially departing" |
| `not_on_current_roster` | A newer roster is published and the player (with stats last season) is not on it | "not listed on the current roster" |
| `returning` | Everyone else | — |
| `incoming` | On a newer roster with no stats last season (freshmen / transfers) | counted as known incoming depth |

Eligibility (redshirt, COVID years) is almost never published reliably, so
`eligibility_remaining` stays `NULL` and **class-year-based departures cap
confidence at MEDIUM**. Observed departures (new roster published) can reach HIGH.

## 4. Metrics per position group

Hitters (C, INF/MIF/CIF, OF):
* `starts_departing_share` = Σ GS(departing) / Σ GS(all players in group)
* `pa_departing_share` — PA = AB + BB + HBP + SF + SH
* `production_departing_share` — production = TB + BB + HBP (a simple, transparent
  "bases produced" measure; no subjective quality judgment)

Pitchers (RHP, LHP):
* `ip_departing_share` (on outs), `gs_departing_share`, plus saves/strikeout shares
  and starter-innings share in evidence.
* production = innings (outs) — we measure **workload leaving**, not talent.

Depth:
* `returning_count`, `returning_experienced` — hitter: GS ≥ 15 or PA ≥ 60;
  pitcher: IP ≥ 20 or GS ≥ 5.
* `known_incoming` — only from newer rosters or future verified commitments.

Note: Sidearm "GS" is games started **at any position**. Posts therefore say
"starts made by players listed at catcher", never "starts at catcher".

## 5. Signal (0–100)

Components (each 0–1):

| Component | Formula | Default weight |
|---|---|---|
| Turnover | departing_count / roster_count | 0.15 |
| Usage departing | hitters: mean(starts share, PA share); pitchers: mean(IP share, GS share) | 0.30 |
| Production departing | production share | 0.20 |
| Returning-depth gap | 1 − min(returning_count / target_depth, 1) | 0.20 |
| Returning-experience gap | 1 − min(returning_experienced / target_experienced, 1) | 0.15 |
| Known incoming (penalty) | min(known_incoming / target_depth, 1) | −0.15 |

`raw = Σ weight × component − penalty`
`signal = clamp(100 × raw × (0.5 + 0.5 × data_quality), 0, 100)`

The data-quality multiplier means weak data can never produce a top score.

Default depth targets: C 3/1 · INF 6/3 · MIF 3/2 · CIF 3/2 · OF 5/3 · RHP 10/4 · LHP 4/1
(target_depth / target_experienced).

Gates (no candidate is created unless all pass):
* hitters: group has ≥ 10 total starts; pitchers: ≥ 30 IP
* `signal ≥ 45` (config `min_candidate_signal`)
* at least one Tier A source for both roster and stats

## 6. Data quality & confidence (LOW / MEDIUM / HIGH)

Confidence measures **evidence quality**, not the chance a coach recruits anyone.

| Factor | Weight | Value |
|---|---|---|
| Source tier (worst of roster/stats) | 0.20 | A 1.0 · B 0.8 · C 0.5 |
| Stats→roster match rate | 0.20 | matched rows / stats rows |
| Class year known (group) | 0.15 | fraction |
| Position confidence (group mean) | 0.20 | 0–1 |
| Recency | 0.15 | roster fetched ≤7d 1.0 · ≤30d 0.8 · else 0.5; ×0.7 if stats season isn't the roster season or the one before |
| Departure basis | 0.10 | observed 1.0 · class-year projection 0.7 |

* HIGH: data_quality ≥ 0.90, match rate ≥ 0.90, basis observed
* MEDIUM: data_quality ≥ 0.70 (class-year projections max out here)
* LOW: anything else — visible in admin, not approvable without override

## 7. Dedupe, staleness, revalidation

* Fingerprint = sha256(`sport|school|position_group|target_season|type`).
  `target_season` = stats season + 1 (the roster cycle the analysis is about).
* Re-running research updates the existing row (`last_analyzed_at`) and writes
  `score_history` if the signal moves; it never creates a duplicate.
* "Material change" = evidence hash changed (who is departing / key totals),
  |Δsignal| ≥ 10, or confidence dropped. Material change on an approved/scheduled
  item sends it back to `pending`. Published items stay published and are never
  re-queued automatically.
* `expires_at` = last_verified_at + 21 days. Expired items can't publish.
* Before publishing, anything last verified > 48h ago is re-fetched and
  re-analyzed. Source unavailable → publish is **blocked** (fail safe).

## 8. Worked example (real data, CSUSM 2026 — captured Sept 2026)

Roster lists 4 catchers: Senior (25 GP / 8 GS), Graduate Student (47 / 40),
Junior (no 2026 stats), Freshman (11 / 4). Roster season = stats season = 2026,
so departures are class-year projections.

* Turnover 2/4 = 0.50 · starts share 48/52 = 0.923 · PA share 192/208 = 0.923
* Production share (TB+BB+HBP) 88/92 = 0.957
* Returning 2 of target 3 → gap 0.333 · returning experienced 0 of 1 → gap 1.0
* raw = 0.075 + 0.277 + 0.191 + 0.067 + 0.150 = 0.760 → signal ≈ 70 with data quality ≈ 0.85
* Confidence MEDIUM (class-year projection; eligibility unknown)

Post language: "Players listed as seniors/graduate students accounted for about
92% of starts made by listed catchers in 2026."
