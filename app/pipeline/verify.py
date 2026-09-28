"""Check that we read a sport's REAL official pages correctly, before trusting it to post live.

    python -m app.cli verify --sport softball [--school csusm] [--save-pages captured/]

For every program in config/programs/<sport>.csv (active or not) this fetches the live pages with the
polite crawler, parses them, runs the analyzer and prints what it understood: seasons, players,
unrecognised positions, which stats tables were found, how many stats rows matched the roster, and
each position group's numbers. It never writes to the database and never posts anything.

--save-pages writes the fetched HTML plus a manifest.json in the tests/fixtures format, so the pages
can become test fixtures (then a reviewer flips `live_verified=True` in app/sports/registry.py).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.collectors.base import ParseError, SourceUnavailable, TeamRef
from app.collectors.http import FetchResult, PoliteFetcher
from app.collectors.sidearm import SidearmAdapter
from app.pipeline.research import PROGRAMS_DIR, build_input, fetch_team_pages
from app.sports.registry import get_sport

# thresholds for a PASS verdict
MIN_MATCH_RATE = 0.8
MAX_UNRECOGNISED_POSITIONS = 0.2


class RecordingFetcher(PoliteFetcher):
    """A PoliteFetcher that also keeps every page it returns (for --save-pages)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pages: list[FetchResult] = []

    def get(self, url: str, *, force_refresh: bool = False) -> FetchResult:
        res = super().get(url, force_refresh=force_refresh)
        self.pages.append(res)
        return res


@dataclass
class _School:
    slug: str
    name: str
    division: str | None
    conference: str | None


@dataclass
class VerifyReport:
    school: str
    verdict: str  # PASS | CHECK | FAIL
    lines: list[str] = field(default_factory=list)


def programs(sport: str, school: str | None = None, path: Path | None = None) -> list[dict]:
    path = path or PROGRAMS_DIR / f"{sport}.csv"
    if not path.exists():
        return []
    with path.open() as f:
        rows = [r for r in csv.DictReader(f) if r.get("slug") and not r["slug"].startswith("#")]
    return [r for r in rows if school in (None, r["slug"])]


def verify_program(row: dict, sport: str, adapter, *, now: datetime | None = None) -> VerifyReport:
    now = now or datetime.now(timezone.utc)
    cfg = get_sport(sport)
    ref = TeamRef(sport, row["slug"], row["name"], row["base_url"], row.get("sport_path") or sport)
    rep = VerifyReport(row["name"], "FAIL")
    out = rep.lines.append
    if row.get("adapter", "sidearm") != "sidearm":
        out(f"adapter '{row.get('adapter')}' can't be verified yet (only sidearm)")
        return rep
    try:
        pages = fetch_team_pages(adapter, ref, cfg.season_style, now.date())
    except (SourceUnavailable, ParseError) as e:
        out(f"✗ could not read the pages: {getattr(e, 'reason', None) or e}")
        return rep

    problems: list[str] = []
    r = pages.roster
    out(f"roster: {r.source.url}  season {r.season_label or '?'}  players {len(r.players)}")
    unrecognised = [p.position_raw or "(blank)" for p in r.players
                    if cfg.module.classify(p.position_raw, p.position_long, None).primary is None]
    if unrecognised:
        out(f"  positions not recognised ({len(unrecognised)}): {', '.join(sorted(set(unrecognised)))[:300]}")
    if r.players and len(unrecognised) / len(r.players) > MAX_UNRECOGNISED_POSITIONS:
        problems.append("many roster positions weren't recognised")
    if pages.prev_roster:
        out(f"last season's roster: {pages.prev_roster.source.url}  season {pages.prev_roster.season_label or '?'}"
            f"  players {len(pages.prev_roster.players)}")
    st = pages.stats
    out(f"stats: {st.source.url}  season {st.season_label}")
    for kind, rows in st.tables.items():
        cols = sorted({c for row in rows for c in row.values})
        out(f"  table '{kind}': {len(rows)} players; columns: {', '.join(cols)[:300]}")
    for w in r.warnings + st.warnings:
        out(f"  warning: {w}")

    ti = build_input(cfg, _School(row["slug"], row["name"], row.get("division") or None,
                                  row.get("conference") or None), pages)
    rate = ti.match_rate
    out(f"stats rows matched to roster: {ti.stats_rows_matched}/{ti.stats_rows_total}"
        + (f" ({round(100 * rate)}%)" if rate is not None else ""))
    if ti.unmatched_stats:
        out(f"  unmatched: {'; '.join(ti.unmatched_stats[:8])}")
    if rate is None or rate < MIN_MATCH_RATE:
        problems.append(f"under {round(100 * MIN_MATCH_RATE)}% of stats rows matched the roster")

    usable = False
    for a in cfg.analyzer(ti, cfg, now=now):
        m = a.metrics
        if "usage_label" in m:
            use = (f"{m['usage_label']} departing {m['usage_departing']} of {m['usage_total']}"
                   if m["usage_total"] is not None else f"{m['usage_label']}: none found")
            usable |= m["usage_total"] is not None
        else:
            key = "ip" if a.kind == "pitcher" else "starts"
            use = f"{key} departing {m.get(key + '_departing')} of {m.get(key + '_total')}"
            usable |= bool(m.get("starts_total") or m.get("ip_total"))
        out(f"  {a.position_group:<4} listed {m['roster_count']:>2}, final-year {m['departing_count']:>2}; {use}; "
            f"signal {a.signal} {a.confidence}" + ("" if a.passes_gates else f"  (not a candidate: "
                                                   f"{'; '.join(a.gate_failures)})"))
    if not usable:
        problems.append("no playing-time numbers were found for any position group")

    for p in problems:
        out(f"✗ {p}")
    rep.verdict = "PASS" if not problems else "CHECK"
    return rep


def save_pages(fetcher: RecordingFetcher, row: dict, sport: str, out_dir: Path, now: datetime) -> list[Path]:
    """Write fetched pages + manifest.json in the tests/fixtures/<adapter>/ format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = row["slug"]
    mpath = out_dir / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    entry = {"school_name": row["name"], "captured_at": now.isoformat(), "stats": {}, "rosters": {}}
    written = []
    for res in fetcher.pages:
        url = res.landed_url
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        if "/stats/" in url:
            fname = f"{slug}_{sport}_stats_{tail}.html"
            entry["stats"][tail] = {"file": fname, "url": url}
        elif url.rstrip("/").endswith("/roster"):
            fname = f"{slug}_{sport}_roster.html"
            entry["roster"] = {"file": fname, "url": url}
        elif "/roster/" in url:
            fname = f"{slug}_{sport}_roster_{tail}.html"
            entry["rosters"][tail] = {"file": fname, "url": url}
        else:
            continue
        (out_dir / fname).write_text(res.text)
        written.append(out_dir / fname)
    manifest[f"{slug}:{sport}"] = entry
    mpath.write_text(json.dumps(manifest, indent=2))
    return written


def run_verify(sport: str, *, school: str | None = None, save_dir: str | None = None, fetcher=None,
               now: datetime | None = None, echo=print) -> list[VerifyReport]:
    now = now or datetime.now(timezone.utc)
    cfg = get_sport(sport)
    rows = programs(sport, school)
    if not rows:
        echo(f"No programs listed in config/programs/{sport}.csv" + (f" with slug '{school}'" if school else ""))
        return []
    reports = []
    for row in rows:
        f = fetcher or RecordingFetcher(use_cache=False)
        if isinstance(f, RecordingFetcher):
            f.pages.clear()
        rep = verify_program(row, sport, SidearmAdapter(f), now=now)
        echo(f"\n=== {cfg.display_name}: {row['name']} — {rep.verdict}")
        for line in rep.lines:
            echo("  " + line)
        if save_dir and isinstance(f, RecordingFetcher) and f.pages:
            for p in save_pages(f, row, sport, Path(save_dir), now):
                echo(f"  saved {p}")
        reports.append(rep)
    status = "is already marked live-verified" if cfg.live_verified else (
        "is NOT live-verified yet: it can research and be reviewed, but won't post live. After a PASS on a few "
        "schools (and saved pages added as test fixtures), set live_verified=True for it in app/sports/registry.py")
    echo(f"\n{cfg.display_name} {status}.")
    return reports
