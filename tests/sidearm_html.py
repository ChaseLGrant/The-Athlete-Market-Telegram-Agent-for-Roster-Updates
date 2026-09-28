"""Render SYNTHETIC Sidearm-style pages for tests of the non-baseball sports.

The markup copies the class names / table layout of the real CSUSM pages (see
scripts/build_csusm_fixture.py). The school ("Example State", example.edu) and every player and
number are made up: they exist only to exercise the parsers and analyzers, never to publish.
Real-page fixtures for these sports come from `python -m app.cli verify --save-pages`.
"""
from __future__ import annotations

from app.collectors.fixture import FixtureAdapter

BASE = "https://example.edu"
CAPTURED = "2026-09-28T16:00:00+00:00"


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def roster_html(title: str, players: list[tuple]) -> str:
    """players: (id, position, jersey, name, class_year)"""
    lis = []
    for pid, pos, num, name, yr in players:
        lis.append(
            f'<li class="sidearm-roster-player" data-player-id="{pid}">'
            f'<div class="sidearm-roster-player-position"><span class="text-bold">'
            f'<span class="sidearm-roster-player-position-long-short hide-on-small-down"> {esc(pos)} </span>'
            f'<span class="sidearm-roster-player-position-long-short hide-on-medium"> {esc(pos)} </span></span></div>'
            f'<div class="sidearm-roster-player-name"><span class="sidearm-roster-player-jersey-number"> {num} </span>'
            f'<h3><a href="/roster/{pid}">{esc(name)}</a></h3></div>'
            f'<div class="sidearm-roster-player-other hide-on-medium-down">'
            f'<span class="sidearm-roster-player-academic-year">{esc(yr)}</span></div></li>'
        )
    return (f"<!doctype html><html><head><title>{esc(title)}</title></head><body>"
            f'<ul class="sidearm-roster-players">{"".join(lis)}</ul></body></html>')


def stat_table(caption: str, head: list[str], rows: list[tuple], ids: dict[str, str]) -> str:
    """head starts with '#', 'Player'; rows are (jersey, 'Last, First', *values)."""
    th = "".join(f'<th scope="col">{esc(c)}</th>' for c in head)
    body = []
    labels = head[2:]
    for num, pname, *vals in rows:
        last, _, first = pname.partition(",")
        pid = ids.get(f"{first.strip()} {last.strip()}", "")
        tds = "".join(f'<td data-label="{esc(labels[i] if i < len(labels) else "")}">{esc(v)}</td>'
                      for i, v in enumerate(vals))
        body.append(f'<tr><td>{num}</td><th scope="row"><a href="#" data-player-id="{pid}">{esc(pname)}</a></th>'
                    f"{tds}</tr>")
    return (f'<table class="sidearm-table"><caption>{esc(caption)}</caption><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def stats_html(title: str, tables: list[str]) -> str:
    return f"<!doctype html><html><head><title>{esc(title)}</title></head><body>{''.join(tables)}</body></html>"


def adapter(sport: str, sport_path: str, current: tuple[str, str], stats: tuple[str, str],
            previous: tuple[str, str] | None = None, slug: str = "exst") -> FixtureAdapter:
    """current/previous = (season, roster html); stats = (season, stats html)."""
    base = f"{BASE}/sports/{sport_path}"
    m = {"school_name": "Example State", "captured_at": CAPTURED,
         "roster": {"file": "-", "url": f"{base}/roster"},
         "stats": {stats[0]: {"file": "-", "url": f"{base}/stats/{stats[0]}"}}}
    overrides = {f"{slug}:{sport}:roster": current[1], f"{slug}:{sport}:stats:{stats[0]}": stats[1]}
    if previous:
        m["rosters"] = {previous[0]: {"file": "-", "url": f"{base}/roster/{previous[0]}"}}
        overrides[f"{slug}:{sport}:roster:{previous[0]}"] = previous[1]
    return FixtureAdapter(manifest={f"{slug}:{sport}": m}, overrides=overrides)


def add_program(db, sport: str, sport_path: str, slug: str = "exst"):
    """Register the synthetic school/team directly (no CSV needed)."""
    from app.models import School, Team

    school = School(slug=slug, name="Example State", short_name="EXST", division="NCAA D2")
    db.add(school)
    db.flush()
    team = Team(school_id=school.id, sport=sport, adapter="sidearm", base_url=BASE, sport_path=sport_path)
    db.add(team)
    db.commit()
    return team
