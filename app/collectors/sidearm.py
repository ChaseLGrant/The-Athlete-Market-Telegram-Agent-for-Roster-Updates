"""Adapter for Sidearm Sports athletics sites (used by a large share of NCAA programs).

Roster:  {base}/sports/{sport}/roster[/{season}]
Stats:   {base}/sports/{sport}/stats/{season}

Parsing is structure-based (Sidearm CSS classes / table captions) with a generic
header-mapped table fallback. If neither matches, ParseError is raised — we
never guess.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from app.collectors.base import (
    ParseError,
    RawRoster,
    RawRosterPlayer,
    RawStatRow,
    RawStats,
    SourceRecord,
    SourceUnavailable,
    TeamRef,
)
from app.collectors.coaches import (
    RawCoach,
    coaches_url,
    email_on_bio_page,
    parse_staff,
    pick_head_coach,
    same_site,
)
from app.collectors.http import FetchResult, PoliteFetcher
from app.sports.seasons import start_year

SEASON_RE = re.compile(r"\b((?:19|20)\d{2}(?:[-–](?:\d{2}|\d{4}))?)\b")
SKIP_NAMES = {"totals", "total", "opponents", "opponent", "team", "tm"}



def _captions_for(sport: str) -> dict[str, tuple[str, ...]]:
    from app.sports.registry import get_sport

    return get_sport(sport).stat_captions


def _txt(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _clean(s: str | None, max_len: int = 200) -> str | None:
    """Validate external text: strip, collapse whitespace, cap length."""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s[:max_len] or None


def _jersey(s: str | None) -> str | None:
    s = _clean(s, 16)
    return s if s and re.fullmatch(r"[0-9A-Za-z/]{1,6}", s) else None


class SidearmAdapter:
    name = "sidearm"

    def __init__(self, fetcher: PoliteFetcher | None = None):
        self.fetcher = fetcher or PoliteFetcher()

    # ------------------------------------------------------------ urls
    @staticmethod
    def roster_url(team: TeamRef, season: str | None = None) -> str:
        u = f"{team.base_url.rstrip('/')}/sports/{team.sport_path}/roster"
        return f"{u}/{season}" if season else u

    @staticmethod
    def stats_url(team: TeamRef, season: str) -> str:
        return f"{team.base_url.rstrip('/')}/sports/{team.sport_path}/stats/{season}"

    # ------------------------------------------------------------ roster
    def fetch_roster(self, team: TeamRef, season: str | None = None) -> RawRoster:
        res = self.fetcher.get(self.roster_url(team, season))
        return self.parse_roster(res, team)

    def parse_roster(self, res: FetchResult, team: TeamRef) -> RawRoster:
        if "/roster" not in res.landed_url:
            raise ParseError(f"roster request was redirected to {res.landed_url}")
        soup = BeautifulSoup(res.text, "lxml")
        title = _txt(soup.find("title"))
        m = SEASON_RE.search(title)
        season_label = m.group(1).replace("–", "-") if m else None
        warnings: list[str] = []
        if not season_label:
            warnings.append("season label not found in page title")

        players = self._parse_roster_cards(soup)
        if not players:
            players = self._parse_roster_table(soup)
        if not players:
            raise ParseError(f"no roster players recognised at {res.url}")

        src = SourceRecord(
            url=res.landed_url, kind="roster", tier="A", fetched_at=res.fetched_at, http_status=res.status,
            content_hash=res.content_hash, title=title[:300] or None, publisher=team.school_name,
            season_label=season_label, from_cache=res.from_cache,
        )
        return RawRoster(season_label=season_label, players=players, source=src, warnings=warnings)

    def _parse_roster_cards(self, soup: BeautifulSoup) -> list[RawRosterPlayer]:
        out: list[RawRosterPlayer] = []
        for li in soup.select("li.sidearm-roster-player"):
            a = li.select_one(".sidearm-roster-player-name h3 a, h3 a")
            name = _txt(a) or _txt(li.select_one(".sidearm-roster-player-name"))
            if not name:
                continue
            pos_spans = li.select(".sidearm-roster-player-position-long-short")
            pos_short = _txt(pos_spans[1]) if len(pos_spans) > 1 else None
            pos_long = _txt(pos_spans[0]) if pos_spans else None
            if not pos_spans:
                bold = li.select_one(".sidearm-roster-player-position .text-bold")
                pos_short = _txt(bold) or None
            # prefer the desktop "other" block (full words), else any
            other = li.select_one(".sidearm-roster-player-other.hide-on-medium-down") or li
            year = _txt(other.select_one(".sidearm-roster-player-academic-year")) or _txt(
                li.select_one(".sidearm-roster-player-academic-year")
            )
            bt = _txt(li.select_one(".sidearm-roster-player-custom1"))
            out.append(
                RawRosterPlayer(
                    name=_clean(name, 160),
                    site_player_id=_clean(li.get("data-player-id")),
                    jersey=_jersey(_txt(li.select_one(".sidearm-roster-player-jersey-number"))),
                    position_raw=_clean(pos_short) or _clean(pos_long),
                    position_long=_clean(pos_long),
                    class_year_raw=_clean(year),
                    height=_clean(_txt(li.select_one(".sidearm-roster-player-height"))),
                    weight=_clean(_txt(li.select_one(".sidearm-roster-player-weight"))),
                    bats_throws=bt if re.fullmatch(r"[RLSB]\s*/\s*[RL]", bt or "") else None,
                    hometown=_clean(_txt(other.select_one(".sidearm-roster-player-hometown"))),
                    high_school=_clean(_txt(other.select_one(".sidearm-roster-player-highschool"))),
                    previous_school=_clean(_txt(other.select_one(".sidearm-roster-player-previous-school"))),
                    profile_url=a.get("href") if a else None,
                )
            )
        return out

    _ROSTER_HEADER_MAP = {
        "#": "jersey", "no": "jersey", "no.": "jersey", "number": "jersey",
        "name": "name", "full name": "name", "player": "name",
        "pos": "position_raw", "pos.": "position_raw", "position": "position_raw",
        "cl": "class_year_raw", "cl.": "class_year_raw", "class": "class_year_raw", "yr": "class_year_raw",
        "yr.": "class_year_raw", "year": "class_year_raw", "academic year": "class_year_raw",
        "ht": "height", "ht.": "height", "height": "height", "wt": "weight", "wt.": "weight", "weight": "weight",
        "b/t": "bats_throws", "hometown": "hometown", "high school": "high_school",
        "previous school": "previous_school", "last school": "previous_school",
    }

    def _parse_roster_table(self, soup: BeautifulSoup) -> list[RawRosterPlayer]:
        for table in soup.find_all("table"):
            heads = [_txt(th).lower() for th in table.select("thead th")]
            cols = [self._ROSTER_HEADER_MAP.get(h) for h in heads]
            if "name" not in cols or "position_raw" not in cols:
                continue
            out = []
            for tr in table.select("tbody tr"):
                cells = tr.find_all(["td", "th"])
                rec: dict[str, str | None] = {}
                for c, cell in zip(cols, cells):
                    if c:
                        rec[c] = _clean(_txt(cell))
                if not rec.get("name"):
                    continue
                link = tr.find("a", href=True)
                pid = None
                if link:
                    mm = re.search(r"/(\d+)/?$", link["href"])
                    pid = mm.group(1) if mm else None
                bt = rec.get("bats_throws")
                out.append(RawRosterPlayer(
                    name=_clean(rec["name"], 160), site_player_id=pid, jersey=_jersey(rec.get("jersey")),
                    position_raw=rec.get("position_raw"), class_year_raw=rec.get("class_year_raw"),
                    height=rec.get("height"), weight=rec.get("weight"),
                    bats_throws=bt if bt and re.fullmatch(r"[RLSB]\s*/\s*[RL]", bt) else None,
                    hometown=rec.get("hometown"), high_school=rec.get("high_school"),
                    previous_school=rec.get("previous_school"),
                    profile_url=link["href"] if link else None,
                ))
            if out:
                return out
        return []

    # ------------------------------------------------------------ coach contact
    def fetch_head_coach(self, team: TeamRef) -> RawCoach | None:
        """Head coach name/title/email from the official site (see app/collectors/coaches.py).
        None when the site doesn't publish it. Never raises for a missing page."""
        tried: list[RawCoach] = []
        try:  # 1. roster page (normally already in the fetcher's cache)
            res = self.fetcher.get(self.roster_url(team))
            tried = parse_staff(res.text, res.landed_url)
        except SourceUnavailable:
            pass
        head = pick_head_coach(tried)
        if head and head.email:
            return head
        if head and head.bio_url and same_site(head.bio_url, team.base_url):  # 2. their bio page
            try:
                res = self.fetcher.get(head.bio_url)
                email = email_on_bio_page(res.text, head.name)
                if email:
                    return RawCoach(head.name, head.title, email, res.landed_url, head.bio_url)
            except SourceUnavailable:
                pass
        try:  # 3. coaching staff page
            res = self.fetcher.get(coaches_url(team.base_url, team.sport_path))
            if "/coaches" in res.landed_url:
                staff = pick_head_coach(parse_staff(res.text, res.landed_url))
                if staff and staff.email and (head is None or staff.name.lower() == head.name.lower()):
                    return staff
                head = head or staff
        except SourceUnavailable:
            pass
        return RawCoach(head.name, head.title, None, head.source_url, head.bio_url) if head else None

    # ------------------------------------------------------------ stats
    def fetch_stats(self, team: TeamRef, season: str) -> RawStats:
        res = self.fetcher.get(self.stats_url(team, season))
        return self.parse_stats(res, team, season)

    def parse_stats(self, res: FetchResult, team: TeamRef, season: str) -> RawStats:
        if "/stats" not in res.landed_url:
            # Sidearm redirects unknown seasons to the schedule page (seen live on 2026-09-28)
            raise ParseError(f"stats request was redirected to {res.landed_url}")
        soup = BeautifulSoup(res.text, "lxml")
        title = _txt(soup.find("title"))
        m = SEASON_RE.search(title)
        page_season = m.group(1).replace("–", "-") if m else None
        warnings: list[str] = []
        if page_season and start_year(page_season) != start_year(season):
            # Sidearm sometimes redirects an unknown season to the latest one.
            raise ParseError(f"stats page season {page_season} != requested {season} at {res.url}")

        captions = _captions_for(team.sport)
        tables: dict[str, list[RawStatRow]] = {}
        for table in soup.find_all("table"):
            cap = _txt(table.find("caption")).lower()
            # first kind whose caption fragment matches; kinds are listed most-specific first
            kind = next((k for k, needles in captions.items() if any(n in cap for n in needles)), None)
            if kind is None or kind in tables:
                continue
            rows = self._parse_stat_table(table)
            if rows:  # a team-summary table with the same caption has no player rows; keep looking
                tables[kind] = rows
        if not tables:
            raise ParseError(f"no individual stats tables recognised at {res.url} "
                             f"(looked for: {', '.join(captions)})")
        for k in captions:
            if k not in tables and k != "fielding":
                warnings.append(f"{k} table missing")

        src = SourceRecord(
            url=res.landed_url, kind="stats", tier="A", fetched_at=res.fetched_at, http_status=res.status,
            content_hash=res.content_hash, title=title[:300] or None, publisher=team.school_name,
            season_label=season, from_cache=res.from_cache,
        )
        return RawStats(season_label=season, tables=tables, source=src, warnings=warnings)

    @staticmethod
    def _parse_stat_table(table: Tag) -> list[RawStatRow]:
        heads = [_txt(th) for th in table.select("thead th")]
        rows: list[RawStatRow] = []
        for tr in table.select("tbody tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 3:
                continue
            if heads and len(cells) != len(heads):
                continue  # columns don't line up with the header (e.g. grouped headers): never guess
            player_cell = tr.find("th") or (cells[1] if len(cells) > 1 else None)
            link = player_cell.find("a", attrs={"data-player-id": True}) if player_cell else None
            if link is not None:
                name = _txt(link)
                pid = _clean(link.get("data-player-id"))
            else:
                a = player_cell.find("a") if player_cell else None
                name = _txt(a) if a else _txt(player_cell)
                pid = None
            name = re.sub(r"^\d+\s+", "", name).strip()
            if not name or name.lower() in SKIP_NAMES or not re.search(r"[A-Za-z]", name):
                continue  # totals rows, and unnamed lines some sites publish (e.g. just "99")
            values: dict[str, str] = {}
            for h, c in zip(heads, cells):
                if h and h.lower() not in ("player", "bio link"):
                    values[h] = _txt(c)
            jersey = _jersey(values.pop("#", None))
            values = {k[:40]: v[:40] for k, v in values.items()}
            rows.append(RawStatRow(name=_clean(name, 160) or name[:160], jersey=jersey, site_player_id=pid,
                                   values=values))
        return rows
