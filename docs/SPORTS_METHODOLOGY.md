# Other sports: how the signal is calculated

Baseball is documented in [BASEBALL_METHODOLOGY.md](BASEBALL_METHODOLOGY.md). This page covers
softball, men's and women's basketball, men's and women's soccer, and football. The scoring math
(signal, data quality, confidence, gates, dedupe, revalidation) is the same for every sport; only
**how playing time is measured** changes.

**Status: built and tested, not yet live-verified.** These sports' page reading has only been
tested on synthetic pages shaped like real Sidearm pages. Until `python -m app.cli verify --sport X`
shows PASS on real schools and `live_verified=True` is set in `app/sports/registry.py`, a sport can
research and be reviewed in the dashboard, but it **never posts live**.

## Softball

Same structure as baseball (same Sidearm tables, same positions), so it uses the baseball analyzer:
starts, plate appearances and production for hitters; innings and games started for pitchers.
Depth targets: C 3/1 · INF 6/3 · MIF 3/2 · CIF 3/2 · OF 5/3 · RHP 4/2 · LHP 2/1. Season "2026" = spring 2026.

## Basketball, soccer, football (the "usage" engine, `app/sports/generic/`)

### Which players count
Departures are always **projected from class year on the current roster**: players listed as
seniors or graduate students may leave after this season. In the off-season the current roster is
usually newer than the last completed season; then last season's roster is fetched too, stats are
matched against it (reliable names/ids), and each player's numbers are carried to the current roster.
Players who already left are **excluded** from the shares: they aren't part of the upcoming turnover
(the count is kept as `already_departed_team_count` for reference).

Because eligibility isn't published, confidence tops out at **MEDIUM** for these sports (same rule as
baseball's class-year projections).

### Position groups (only what rosters actually publish)

| Sport | Groups | Folds in |
|---|---|---|
| Basketball | G, F, C | PG/SG → G; SF/PF → F; "G/F" counts as G only (first listed) |
| Soccer | GK, D, M, F | CB/FB/WB → D; CM/DM/AM → M; ST/W → F |
| Football | QB, RB, WR, TE, OL, DL, LB, DB, K, P | OT/OG/C → OL; DE/DT/NT/EDGE → DL; CB/S → DB |

Unrecognised labels (e.g. basketball "Wing", football "ATH", "LS") are left unclassified, never guessed.
They lower the position-confidence part of data quality.

### How playing time is measured

| Sport / group | Usage (main share) | Starts | Production | "Significant experience" |
|---|---|---|---|---|
| Basketball | minutes | games started | points + rebounds + assists | ≥ 300 min or ≥ 10 starts |
| Soccer field players | minutes | games started | points (2 × goals + assists) | ≥ 600 min or ≥ 8 starts |
| Soccer GK | goalkeeping minutes | games started | — | ≥ 450 min or ≥ 5 starts |
| Football QB | passing yards | unknown* | passing TDs | ≥ 6 games or ≥ 500 yds |
| Football RB | rushing yards | unknown* | rushing TDs | ≥ 6 games or ≥ 300 yds |
| Football WR / TE | receiving yards | unknown* | receiving TDs | ≥ 6 games or ≥ 250 / 150 yds |
| Football DL / LB / DB | tackles | unknown* | TFL + sacks (DL/LB) | ≥ 6 games or ≥ 20–25 tackles |
| Football K / P | field-goal attempts / punts | unknown* | — | ≥ 6 games or ≥ 5 FGA / 15 punts |
| Football OL | none published | — | — | ≥ 6 games |

\* Football stat pages don't list starts per player; unknown stays unknown (it contributes nothing).
Offensive linemen have no individual stats, so an OL group never passes the volume gate: we don't
post OL turnover based on a guess.

`usage_departing` in the signal = mean of the known shares (usage share, starts share).
Volume gates (the group must have at least this much last season): basketball G/F 400 min, C 200 min;
soccer GK 450 min, D/M 900 min, F 600 min; football QB 500 pass yds, RB 300, WR 400, TE 100 rush/rec
yds, DL/LB/DB 60 tackles, K 5 FGA, P 15 punts.

### Weights

| | turnover | usage | production | depth gap | experience gap | incoming penalty |
|---|---|---|---|---|---|---|
| Basketball | 0.10 | 0.40 | 0.15 | 0.20 | 0.15 | 0.15 |
| Soccer | 0.10 | 0.35 | 0.10 | 0.25 | 0.20 | 0.15 |
| Football | 0.10 | 0.35 | 0.15 | 0.20 | 0.20 | 0.15 |

Tune them in each sport's module (`app/sports/basketball.py`, `soccer.py`, `football.py`).

### Seasons

| Style | Sports | Label | Latest completed season (as of a date) |
|---|---|---|---|
| spring | baseball, softball | "2026" | this year from July, else last year |
| fall | football, soccer | "2025" | last year (waits for January to be safe) |
| winter | basketball | "2025-26" | the one that ended this spring, from May |

The target season in posts is the season after the current roster's season.

## Page-reading safety

* Stats tables are found by their caption (e.g. "Individual Overall Statistics", "Goalkeeping",
  "Rushing"); the most specific kind is checked first.
* If a row's cells don't line up with the header (grouped headers), the row is skipped; a table with
  no readable rows doesn't count, and a page with none raises a parse failure. We never guess columns.
* Basketball "MIN" values that look like per-game averages are treated as unknown, not multiplied out.
* Soccer's "G" column is goals, never games.
