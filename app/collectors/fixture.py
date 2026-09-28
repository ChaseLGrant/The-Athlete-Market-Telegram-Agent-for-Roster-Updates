"""Offline adapter used in TEST_MODE and tests.

Reads saved HTML captured from real official pages (see tests/fixtures/*/manifest.json)
and runs it through the real Sidearm parser, so the whole workflow can be
previewed without touching the network. The original source URLs are kept.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.collectors.base import RawRoster, RawStats, SourceUnavailable, TeamRef
from app.collectors.http import FetchResult
from app.collectors.sidearm import SidearmAdapter

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sidearm"


class FixtureAdapter:
    name = "fixture"

    def __init__(self, fixture_dir: Path | str | None = None, overrides: dict[str, str] | None = None,
                 manifest: dict | None = None):
        self.dir = Path(fixture_dir or DEFAULT_DIR)
        self.overrides = overrides or {}  # test hook: {"csusm:baseball:roster": "<html>..."}
        path = self.dir / "manifest.json"
        self.manifest = manifest if manifest is not None else (json.loads(path.read_text()) if path.exists() else {})
        self._parser = SidearmAdapter(fetcher=None)  # type: ignore[arg-type]

    def has(self, team: TeamRef) -> bool:
        return f"{team.school_slug}:{team.sport}" in self.manifest

    def _load(self, key: str, file: str, url: str, captured: str) -> FetchResult:
        text = self.overrides.get(key)
        if text is None:
            p = self.dir / file
            if not p.exists():
                raise SourceUnavailable(url, f"fixture missing: {file}")
            text = p.read_text()
        return FetchResult(
            url=url, status=200, text=text, fetched_at=datetime.fromisoformat(captured),
            from_cache=True, content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )

    def fetch_roster(self, team: TeamRef, season: str | None = None) -> RawRoster:
        m = self.manifest.get(f"{team.school_slug}:{team.sport}")
        if not m:
            raise SourceUnavailable(team.base_url, "no fixture for team")
        if season is None:
            r, key = m["roster"], f"{team.school_slug}:{team.sport}:roster"
        else:  # an older season's roster (e.g. last season, to match stats)
            r = m.get("rosters", {}).get(season)
            if r is None:
                raise SourceUnavailable(team.base_url, f"no roster fixture for season {season}", 404)
            key = f"{team.school_slug}:{team.sport}:roster:{season}"
        res = self._load(key, r["file"], r["url"], m["captured_at"])
        return self._parser.parse_roster(res, team)

    def fetch_stats(self, team: TeamRef, season: str) -> RawStats:
        m = self.manifest.get(f"{team.school_slug}:{team.sport}")
        if not m or season not in m.get("stats", {}):
            raise SourceUnavailable(team.base_url, f"no stats fixture for season {season}", 404)
        st = m["stats"][season]
        res = self._load(f"{team.school_slug}:{team.sport}:stats:{season}", st["file"], st["url"], m["captured_at"])
        return self._parser.parse_stats(res, team, season)
