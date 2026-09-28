"""Find programs to watch from the NCAA's official member directory (instead of typing URLs by hand).

    python -m app.cli discover --sport baseball --probe      # print what the directory returns
    python -m app.cli discover --sport baseball [--limit 60] # check new schools' sites, add the readable ones

For each school the directory lists (with its official athletics site), the site is checked with the
same code as `verify`. PASS -> the program is added as an active team; anything else -> it's recorded as
inactive with the reason, so it isn't checked again every night. Nothing is guessed, and every request
goes through PoliteFetcher (robots.txt, crawl delay). Programs live in the database; the CSV files still
work for hand-added programs.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import SourceUnavailable
from app.collectors.http import PoliteFetcher
from app.collectors.sidearm import SidearmAdapter
from app.logging_setup import record_event
from app.models import School, Team

DIRECTORY = "https://web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode={code}"
SPORT_CODES = {
    "baseball": "MBA", "softball": "WSB", "football": "MFB", "mens_basketball": "MBB",
    "womens_basketball": "WBB", "mens_soccer": "MSO", "womens_soccer": "WSO",
}
# Sidearm's path segment for each sport (/sports/<path>/roster)
SPORT_PATHS = {
    "baseball": "baseball", "softball": "softball", "football": "football",
    "mens_basketball": "mens-basketball", "womens_basketball": "womens-basketball",
    "mens_soccer": "mens-soccer", "womens_soccer": "womens-soccer",
}


def fetch_directory(sport: str, fetcher: PoliteFetcher | None = None) -> list[dict]:
    f = fetcher or PoliteFetcher()
    res = f.get(DIRECTORY.format(code=SPORT_CODES[sport]))
    data = json.loads(res.text)
    if isinstance(data, dict):  # some APIs wrap the list
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return [d for d in data if isinstance(d, dict)]


def probe(sport: str, echo=print) -> int:
    try:
        rows = fetch_directory(sport)
    except (SourceUnavailable, ValueError) as e:
        echo(f"✗ could not read the NCAA directory: {getattr(e, 'reason', None) or e}")
        return 1
    echo(f"{len(rows)} records")
    for r in rows[:3]:
        echo(json.dumps(r, default=str)[:1500])
    keys: dict[str, int] = {}
    for r in rows:
        for k in r:
            keys[k] = keys.get(k, 0) + 1
    echo("keys: " + ", ".join(f"{k}({n})" for k, n in sorted(keys.items())))
    return 0


# ------------------------------------------------------------------ candidates
def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:120]


def base_url(athletic_url: str | None) -> str | None:
    """'www.acusports.com' / 'https://x.com/' -> 'https://www.acusports.com'. None if unusable."""
    u = (athletic_url or "").strip()
    if not u:
        return None
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    p = urlsplit(u)
    if not p.netloc or "." not in p.netloc:
        return None
    return f"https://{p.netloc.lower()}"


def host(url: str | None) -> str:
    h = urlsplit(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


@dataclass
class Candidate:
    slug: str
    name: str
    base_url: str
    division: str | None
    conference: str | None
    state: str | None

    def row(self, sport: str) -> dict:
        return {"slug": self.slug, "name": self.name, "base_url": self.base_url, "adapter": "sidearm",
                "sport_path": SPORT_PATHS[sport], "division": self.division or "",
                "conference": self.conference or ""}


def candidates(records: list[dict]) -> list[Candidate]:
    out, seen = [], set()
    for r in records:
        if str(r.get("deactive", "N")).upper() == "Y":
            continue
        url = base_url(r.get("athleticWebUrl"))
        name = (r.get("nameOfficial") or "").strip()
        if not url or not name or host(url) in seen:
            continue
        seen.add(host(url))
        div = r.get("division")
        out.append(Candidate(
            slug=slugify(name), name=name, base_url=url,
            division=f"NCAA D{div}" if str(div) in ("1", "2", "3") else None,
            conference=(r.get("conferenceName") or "").strip() or None,
            state=((r.get("memberOrgAddress") or {}).get("state") or None),
        ))
    return out


# ------------------------------------------------------------------ discover
def _check(c: Candidate, sport: str, now: datetime) -> tuple[Candidate, str, str]:
    """Worker thread: verify one school's live pages. Returns (candidate, verdict, short reason)."""
    from app.pipeline.verify import verify_program

    try:
        rep = verify_program(c.row(sport), sport, SidearmAdapter(PoliteFetcher()), now=now)
    except Exception as e:  # noqa: BLE001 - one school never stops the batch
        return c, "FAIL", f"{type(e).__name__}: {e}"[:300]
    problems = [ln.strip() for ln in rep.lines if ln.strip().startswith("✗")]
    return c, rep.verdict, ("; ".join(problems) or "ok")[:300]


def discover(session: Session, sport: str, *, limit: int = 60, workers: int = 8, records: list[dict] | None = None,
             now: datetime | None = None, echo=print) -> dict[str, int]:
    """Check up to `limit` directory schools not seen before; add the ones whose pages read correctly."""
    now = now or datetime.now(timezone.utc)
    if records is None:
        records = fetch_directory(sport)
    known_hosts = {host(t.base_url) for t in session.scalars(select(Team).where(Team.sport == sport))}
    todo = [c for c in candidates(records) if host(c.base_url) not in known_hosts][:limit]
    echo(f"{len(records)} schools in the directory; checking {len(todo)} new ones "
         f"({len(known_hosts)} already known)")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda c: _check(c, sport, now), todo))

    counts = {"PASS": 0, "CHECK": 0, "FAIL": 0}
    for c, verdict, reason in results:
        counts[verdict] = counts.get(verdict, 0) + 1
        school = session.scalar(select(School).where(School.slug == c.slug))
        if school is None:
            school = School(slug=c.slug, name=c.name)
            session.add(school)
        school.division = school.division or c.division
        school.conference = school.conference or c.conference
        school.state = school.state or c.state
        school.athletics_domain = school.athletics_domain or c.base_url
        session.flush()
        team = session.scalar(select(Team).where(Team.school_id == school.id, Team.sport == sport))
        if team is None:
            team = Team(school_id=school.id, sport=sport, adapter="sidearm", base_url=c.base_url,
                        sport_path=SPORT_PATHS[sport])
            session.add(team)
        team.active = verdict == "PASS"
        team.notes = f"discover {now.date()}: {verdict} — {reason}"
        echo(f"{verdict:<5} {c.name} ({c.base_url}){'' if verdict == 'PASS' else ' — ' + reason[:160]}")
    record_event(session, "discover", f"{sport}: checked {len(results)}, added {counts['PASS']}", sport=sport,
                 **counts)
    session.flush()
    return counts
