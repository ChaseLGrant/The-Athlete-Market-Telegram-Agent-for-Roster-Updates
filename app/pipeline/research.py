"""Research job: collect → normalize → analyze → store opportunities.

Runs independently from publishing. Safe to re-run any time (idempotent via
fingerprints)."""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.common import name_key
from app.collectors.base import ParseError, RawRoster, RawStats, SourceRecord, SourceUnavailable, TeamRef
from app.collectors.registry import get_adapter
from app.logging_setup import record_event
from app.models import (
    Player,
    PlayerStat,
    RosterEntry,
    RosterSnapshot,
    School,
    Season,
    Source,
    Team,
    TelegramChannel,
)
from app.pipeline.opportunities import upsert_from_analysis
from app.settings import get_settings
from app.sports.baseball.positions import normalize_class_year, parse_bats_throws
from app.sports.registry import get_sport, registry
from app.sports.seasons import label_for, start_year
from app.sports.seasons import latest_completed_season as _latest

log = logging.getLogger("roster_intel")

PROGRAMS_DIR = Path(__file__).resolve().parents[2] / "config" / "programs"


# ----------------------------------------------------------------- programs
def sync_programs(session: Session, sport: str, path: Path | None = None) -> int:
    """Load config/programs/<sport>.csv into schools + teams (insert/update)."""
    path = path or PROGRAMS_DIR / f"{sport}.csv"
    if not path.exists():
        return 0
    n = 0
    with path.open() as f:
        for row in csv.DictReader(f):
            if not row.get("slug") or row["slug"].startswith("#"):
                continue
            school = session.scalar(select(School).where(School.slug == row["slug"]))
            if school is None:
                school = School(slug=row["slug"], name=row["name"])
                session.add(school)
            school.name = row["name"]
            school.short_name = row.get("short_name") or None
            school.division = row.get("division") or None
            school.conference = row.get("conference") or None
            school.state = row.get("state") or None
            school.athletics_domain = row.get("base_url") or None
            session.flush()
            team = session.scalar(select(Team).where(Team.school_id == school.id, Team.sport == sport))
            if team is None:
                team = Team(school_id=school.id, sport=sport, adapter=row["adapter"], base_url=row["base_url"],
                            sport_path=row.get("sport_path") or sport)
                session.add(team)
            team.adapter = row["adapter"]
            team.base_url = row["base_url"]
            team.sport_path = row.get("sport_path") or sport
            team.active = (row.get("active", "true").strip().lower() != "false")
            n += 1
    ensure_channels(session)
    return n


def ensure_channels(session: Session) -> None:
    s = get_settings()
    for key, cfg in registry().items():
        ch = session.scalar(select(TelegramChannel).where(TelegramChannel.sport == key))
        if ch is None:
            session.add(TelegramChannel(sport=key, title=cfg.channel_title, channel_env_var=s.channel_env_var(key)))


# ----------------------------------------------------------------- seasons
def latest_completed_season(sport: str, today: date) -> str:
    """Most recent finished season for this sport, labelled the way the sport's sites label it."""
    return _latest(get_sport(sport).season_style, today)


def _season(session: Session, sport: str, label: str) -> Season:
    s = session.scalar(select(Season).where(Season.sport == sport, Season.label == label))
    if s is None:
        s = Season(sport=sport, label=label, start_year=start_year(label) or 0)
        session.add(s)
        session.flush()
    return s


# ----------------------------------------------------------------- storage
def _store_source(session: Session, team: Team, rec: SourceRecord) -> Source:
    src = Source(team_id=team.id, url=rec.url, kind=rec.kind, tier=rec.tier, title=rec.title,
                 publisher=rec.publisher, season_label=rec.season_label, fetched_at=rec.fetched_at,
                 http_status=rec.http_status, available=True, content_hash=rec.content_hash)
    session.add(src)
    session.flush()
    return src


def _store_unavailable(session: Session, team: Team, kind: str, err: SourceUnavailable) -> None:
    session.add(Source(team_id=team.id, url=err.url, kind=kind, tier="A", available=False,
                       http_status=err.http_status, error=err.reason, fetched_at=datetime.now(timezone.utc)))


def _get_player(session: Session, team: Team, name: str, site_id: str | None) -> Player:
    if site_id:
        p = session.scalar(select(Player).where(Player.team_id == team.id, Player.site_player_id == site_id))
    else:
        p = session.scalar(select(Player).where(Player.team_id == team.id, Player.name_key == name_key(name),
                                                Player.site_player_id.is_(None)))
    if p is None:
        p = Player(team_id=team.id, site_player_id=site_id, full_name=name, name_key=name_key(name))
        session.add(p)
        session.flush()
    return p


def store_roster(session: Session, team: Team, roster: RawRoster, src: Source) -> RosterSnapshot:
    season = _season(session, team.sport, roster.season_label or "unknown")
    snap = RosterSnapshot(team_id=team.id, season_id=season.id, source_id=src.id, player_count=len(roster.players))
    session.add(snap)
    session.flush()
    classify = get_sport(team.sport).module.classify
    for rp in roster.players:
        player = _get_player(session, team, rp.name, rp.site_player_id)
        bats, throws = parse_bats_throws(rp.bats_throws)
        pos = classify(rp.position_raw, rp.position_long, throws)
        cy, rs = normalize_class_year(rp.class_year_raw)
        session.add(RosterEntry(
            snapshot_id=snap.id, player_id=player.id, jersey=rp.jersey, position_raw=rp.position_raw,
            position_group=pos.primary, secondary_group=pos.secondary,
            position_confidence=pos.confidence, is_two_way=pos.is_two_way, class_year_raw=rp.class_year_raw,
            class_year=cy, redshirt=rs, eligibility_remaining=None, height=rp.height, weight=rp.weight,
            bats=bats, throws=throws, hometown=rp.hometown, high_school=rp.high_school,
            previous_school=rp.previous_school,
        ))
    return snap


def store_stats(session: Session, team: Team, stats: RawStats, src: Source) -> int:
    normalize = get_sport(team.sport).module.normalize_stats
    season = _season(session, team.sport, stats.season_label)
    n = 0
    for kind, rows in stats.tables.items():
        for row in rows:
            player = None
            if row.site_player_id:
                player = session.scalar(select(Player).where(Player.team_id == team.id,
                                                             Player.site_player_id == row.site_player_id))
            if player is None:
                player = session.scalar(select(Player).where(Player.team_id == team.id,
                                                             Player.name_key == name_key(row.name)))
            parsed = normalize(kind, row.values)
            session.add(PlayerStat(team_id=team.id, season_id=season.id, source_id=src.id,
                                   player_id=player.id if player else None, stat_type=kind, name_raw=row.name,
                                   jersey=row.jersey, site_player_id=row.site_player_id, stats=parsed,
                                   raw=row.values))
            n += 1
    return n


# ----------------------------------------------------------------- per team
@dataclass
class TeamResult:
    team_id: int
    school: str
    ok: bool
    message: str
    analyses: list = field(default_factory=list)
    opportunity_ids: list[int] = field(default_factory=list)


def team_ref(team: Team) -> TeamRef:
    return TeamRef(sport=team.sport, school_slug=team.school.slug, school_name=team.school.name,
                   base_url=team.base_url, sport_path=team.sport_path)


@dataclass
class TeamPages:
    roster: RawRoster                   # current roster
    stats: RawStats                     # last completed season (or the roster's season)
    prev_roster: RawRoster | None = None  # the stats season's roster, when the current one is newer


def fetch_team_pages(adapter, ref: TeamRef, season_style: str, today: date, *,
                     on_unavailable=None, on_roster=None) -> TeamPages:
    """Fetch the pages one analysis needs, choosing seasons the same way everywhere (research,
    revalidation, verify). Callbacks let research store each page as it arrives.
    Raises SourceUnavailable / ParseError."""
    def _get(kind, fn, *args):
        try:
            return fn(*args)
        except SourceUnavailable as e:
            if on_unavailable:
                on_unavailable(kind, e)
            raise

    roster = _get("roster", adapter.fetch_roster, ref)
    if on_roster:
        on_roster("roster", roster)

    stats_season = _latest(season_style, today)
    roster_year = start_year(roster.season_label)
    if roster_year is not None and roster_year < start_year(stats_season):
        # the site hasn't published a newer roster yet: analyze the season the roster belongs to
        stats_season = label_for(season_style, roster_year)

    prev = None
    if roster_year is not None and roster_year > start_year(stats_season):
        # current roster is newer than the stats: also read the stats-season roster to match players
        prev = _get("roster", adapter.fetch_roster, ref, stats_season)
        if prev.season_label and start_year(prev.season_label) != start_year(stats_season):
            raise ParseError(f"requested {stats_season} roster but page says {prev.season_label}")
        if on_roster:
            on_roster("previous_roster", prev)

    stats = _get("stats", adapter.fetch_stats, ref, stats_season)
    return TeamPages(roster=roster, stats=stats, prev_roster=prev)


def build_input(cfg, school: School, pages: TeamPages):
    return cfg.module.build_team_input(
        school_slug=school.slug, school_name=school.name, division=school.division, conference=school.conference,
        current_roster=pages.roster, stats=pages.stats, stats_season_roster=pages.prev_roster,
    )


@dataclass
class Prefetched:
    """Pages fetched on a worker thread (or the error that stopped them), handed to the main thread."""
    pages: TeamPages | None = None
    error: Exception | None = None
    failed_kind: str | None = None
    coach: object | None = None     # RawCoach, when the head coach contact was (re)checked
    coach_checked: bool = False


COACH_REFRESH_DAYS = 30


def coach_due(team: Team, now: datetime) -> bool:
    at = team.coach_checked_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at is None or now - at > timedelta(days=COACH_REFRESH_DAYS)


def _fetch_coach(adapter, ref: TeamRef):
    """Head coach contact, or None. Never fails the team's research."""
    if not hasattr(adapter, "fetch_head_coach"):
        return None
    try:
        return adapter.fetch_head_coach(ref)
    except Exception as e:  # noqa: BLE001 - contact info is optional
        log.warning("coach contact lookup failed for %s: %s", ref.school_name, e)
        return None


def save_coach(team: Team, coach, now: datetime) -> None:
    """Store what the official site shows. A head coach without a published email clears the email
    (we never keep an address the school no longer shows). Nothing found: keep the last known values."""
    team.coach_checked_at = now
    if coach is None:
        return
    team.coach_name, team.coach_title = coach.name, coach.title
    team.coach_email = coach.email
    team.coach_source_url = coach.source_url if coach.email else None


def prefetch_pages(ref: TeamRef, adapter_name: str, season_style: str, today: date,
                   want_coach: bool = False) -> Prefetched:
    """Runs on a worker thread: its own polite fetcher, no database access."""
    from app.collectors.http import PoliteFetcher
    from app.collectors.sidearm import SidearmAdapter

    failed: dict = {}
    try:
        if adapter_name != "sidearm":
            raise SourceUnavailable(ref.base_url, f"no adapter named '{adapter_name}'")
        adapter = SidearmAdapter(PoliteFetcher())
        pages = fetch_team_pages(adapter, ref, season_style, today,
                                 on_unavailable=lambda kind, e: failed.setdefault("kind", kind))
        if want_coach:
            return Prefetched(pages=pages, coach=_fetch_coach(adapter, ref), coach_checked=True)
        return Prefetched(pages=pages)
    except (SourceUnavailable, ParseError) as e:
        return Prefetched(error=e, failed_kind=failed.get("kind"))
    except Exception as e:  # noqa: BLE001 - reported per team, never kills the batch
        return Prefetched(error=e)


def collect_and_analyze(session: Session, team: Team, *, now: datetime | None = None,
                        prefetched: Prefetched | None = None):
    """Fetch sources (or use pages already fetched on a worker thread), store them, return
    (analyses, source_rows). Raises SourceUnavailable/ParseError."""
    now = now or datetime.now(timezone.utc)
    cfg = get_sport(team.sport)
    sources: dict[str, Source] = {}

    def on_roster(kind: str, roster: RawRoster) -> None:
        sources[kind] = _store_source(session, team, roster.source)
        store_roster(session, team, roster, sources[kind])

    if prefetched is not None:
        if prefetched.error is not None:
            if isinstance(prefetched.error, SourceUnavailable):
                _store_unavailable(session, team, prefetched.failed_kind or "roster", prefetched.error)
            raise prefetched.error
        pages = prefetched.pages
        on_roster("roster", pages.roster)
        if pages.prev_roster is not None:
            on_roster("previous_roster", pages.prev_roster)
    else:
        adapter = get_adapter(team.adapter, team_ref(team))
        pages = fetch_team_pages(adapter, team_ref(team), cfg.season_style, now.date(), on_roster=on_roster,
                                 on_unavailable=lambda kind, e: _store_unavailable(session, team, kind, e))
    sources["stats"] = _store_source(session, team, pages.stats.source)
    store_stats(session, team, pages.stats, sources["stats"])

    if prefetched is not None:
        if prefetched.coach_checked:
            save_coach(team, prefetched.coach, now)
    elif coach_due(team, now):
        save_coach(team, _fetch_coach(adapter, team_ref(team)), now)

    ti = build_input(cfg, team.school, pages)
    if ti.unmatched_stats:
        record_event(session, "parse_warning", f"{len(ti.unmatched_stats)} stats rows not matched to roster",
                     level="WARNING", sport=team.sport, entity_type="team", entity_id=team.id,
                     unmatched=ti.unmatched_stats[:20])
    analyses = cfg.analyzer(ti, cfg, now=now)
    return analyses, {k: sources[k] for k in ("roster", "stats", "previous_roster") if k in sources}


def research_team(session: Session, team: Team, *, now: datetime | None = None,
                  prefetched: Prefetched | None = None) -> TeamResult:
    cfg = get_sport(team.sport)
    if not cfg.implemented:
        record_event(session, "sport_not_implemented", f"{team.sport} analyzer not implemented yet; skipped",
                     sport=team.sport, entity_type="team", entity_id=team.id)
        return TeamResult(team.id, team.school.name, False, "sport not implemented")
    try:
        analyses, sources = collect_and_analyze(session, team, now=now, prefetched=prefetched)
    except SourceUnavailable as e:
        record_event(session, "source_unavailable", e.reason, level="WARNING", sport=team.sport,
                     entity_type="team", entity_id=team.id, url=e.url, http_status=e.http_status)
        return TeamResult(team.id, team.school.name, False, f"source unavailable: {e.reason}")
    except ParseError as e:
        record_event(session, "parse_failed", str(e), level="ERROR", sport=team.sport, entity_type="team",
                     entity_id=team.id)
        return TeamResult(team.id, team.school.name, False, f"parse failed: {e}")

    ids = []
    for a in analyses:
        opp = upsert_from_analysis(session, team, a, sources, now=now)
        if opp is not None:
            ids.append(opp.id)
    return TeamResult(team.id, team.school.name, True, f"{len(analyses)} groups analyzed", analyses, ids)


def run_research(session: Session, sport: str = "baseball", *, now: datetime | None = None,
                 limit: int | None = None) -> list[TeamResult]:
    sync_programs(session, sport)
    session.commit()
    # least recently checked first, so a nightly batch rotates through every program
    last_checked = (select(Source.team_id, func.max(Source.fetched_at).label("at"))
                    .group_by(Source.team_id).subquery())
    teams = session.scalars(
        select(Team).outerjoin(last_checked, last_checked.c.team_id == Team.id)
        .where(Team.sport == sport, Team.active.is_(True))
        .order_by(last_checked.c.at.asc().nulls_first(), Team.id)).all()
    settings = get_settings()
    teams = teams[:limit or settings.research_batch or None]
    now = now or datetime.now(timezone.utc)

    # Fetch pages for several schools at once (each school's own site is still visited one page at a
    # time with its crawl delay), then do all database work here on the main thread.
    fetched: dict[int, Prefetched] = {}
    workers = settings.research_workers
    if workers > 1 and not settings.test_mode and len(teams) > 1:
        from concurrent.futures import ThreadPoolExecutor

        style = get_sport(sport).season_style
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {t.id: pool.submit(prefetch_pages, team_ref(t), t.adapter, style, now.date(),
                                         coach_due(t, now)) for t in teams}
            fetched = {tid: f.result() for tid, f in futures.items()}

    results = []
    for team in teams:
        # each team commits independently so one failure doesn't lose the rest
        try:
            res = research_team(session, team, now=now, prefetched=fetched.get(team.id))
            session.commit()
        except Exception as e:  # noqa: BLE001 - fail safe, log, continue
            session.rollback()
            record_event(session, "research_error", f"{type(e).__name__}: {e}", level="ERROR", sport=sport,
                         entity_type="team", entity_id=team.id)
            session.commit()
            res = TeamResult(team.id, team.school.name, False, f"error: {e}")
        results.append(res)
    return results
