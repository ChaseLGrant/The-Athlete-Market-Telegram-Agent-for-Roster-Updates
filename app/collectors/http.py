"""PoliteFetcher: the only way the app touches the network for data collection.

* obeys robots.txt (with * and $ wildcards, longest-match wins, per RFC 9309)
* honors Crawl-delay and a global minimum delay per host
* identifies itself with a descriptive User-Agent
* caches responses on disk
* NEVER bypasses CAPTCHAs, logins, paywalls or bot protection — those raise
  SourceUnavailable and the pipeline moves on.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

from app.collectors.base import SourceUnavailable
from app.settings import get_settings

BOT_CHALLENGE_MARKERS = (
    "captcha",
    "cf-challenge",
    "challenge-platform",
    "are you a robot",
    "verify you are human",
    "access denied",
    "request unsuccessful. incapsula",
    "px-captcha",
)


# ---------------------------------------------------------------- robots.txt
@dataclass
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern


class RobotsPolicy:
    def __init__(self, text: str | None, user_agent: str):
        self.rules: list[_Rule] = []
        self.crawl_delay: float | None = None
        if text:
            self._parse(text, user_agent)

    @staticmethod
    def _compile(path: str) -> re.Pattern:
        anchored = path.endswith("$")
        if anchored:
            path = path[:-1]
        rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in path)
        return re.compile("^" + rx + ("$" if anchored else ""))

    def _parse(self, text: str, user_agent: str) -> None:
        ua_token = user_agent.split("/")[0].strip().lower()
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        lines: list[tuple[str, str]] = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, val = line.split(":", 1)
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if not last_was_agent and agents:
                    groups.append((agents, lines))
                    agents, lines = [], []
                agents.append(val.lower())
                last_was_agent = True
            else:
                last_was_agent = False
                if agents:
                    lines.append((key, val))
        if agents:
            groups.append((agents, lines))

        specific = [g for g in groups if any(a != "*" and a in ua_token for a in g[0])]
        chosen = specific or [g for g in groups if "*" in g[0]]
        for _, glines in chosen:
            for key, val in glines:
                if key in ("allow", "disallow"):
                    if key == "disallow" and val == "":
                        continue  # empty disallow == allow all
                    self.rules.append(_Rule(key == "allow", val, self._compile(val)))
                elif key == "crawl-delay":
                    try:
                        self.crawl_delay = max(self.crawl_delay or 0.0, float(val))
                    except ValueError:
                        pass

    def allowed(self, path: str) -> bool:
        best: _Rule | None = None
        for r in self.rules:
            if r.regex.match(path):
                if best is None or len(r.pattern) > len(best.pattern) or (
                    len(r.pattern) == len(best.pattern) and r.allow and not best.allow
                ):
                    best = r
        return True if best is None else best.allow


# ---------------------------------------------------------------- fetcher
@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    fetched_at: datetime
    from_cache: bool
    content_hash: str


class PoliteFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        cache_dir: str | None = None,
        use_cache: bool = True,
    ):
        s = get_settings()
        self.user_agent = s.crawler_user_agent
        self.min_delay = s.crawler_min_delay_seconds
        self.cache_ttl = s.cache_ttl_hours * 3600
        self.cache_dir = Path(cache_dir or s.cache_dir)
        self.use_cache = use_cache
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        # always identify ourselves, even on an injected client
        self.client.headers.update({"User-Agent": self.user_agent, "Accept": "text/html,*/*;q=0.5"})
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, RobotsPolicy] = {}
        self._last_hit: dict[str, float] = {}

    # -- helpers
    def _host(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def _wait_turn(self, host: str, delay: float) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            remaining = delay - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_hit[host] = self._clock()

    def robots_for(self, url: str) -> RobotsPolicy:
        host = self._host(url)
        if host in self._robots:
            return self._robots[host]
        robots_url = host + "/robots.txt"
        self._wait_turn(host, self.min_delay)
        try:
            r = self.client.get(robots_url)
        except httpx.HTTPError as e:
            raise SourceUnavailable(robots_url, f"robots.txt unreachable: {e}") from e
        if r.status_code in (401, 403):
            # RFC 9309: unreachable due to auth → treat as full disallow
            raise SourceUnavailable(robots_url, "robots.txt access denied", r.status_code)
        if r.status_code >= 500:
            raise SourceUnavailable(robots_url, "robots.txt server error", r.status_code)
        policy = RobotsPolicy(r.text if r.status_code == 200 else None, self.user_agent)
        self._robots[host] = policy
        return policy

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def _read_cache(self, url: str) -> FetchResult | None:
        if not self.use_cache:
            return None
        p = self._cache_path(url)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text())
            fetched = datetime.fromisoformat(d["fetched_at"])
            if (datetime.now(timezone.utc) - fetched).total_seconds() > self.cache_ttl:
                return None
            return FetchResult(d["url"], d["status"], d["text"], fetched, True, d["hash"])
        except Exception:
            return None

    def _write_cache(self, res: FetchResult) -> None:
        if not self.use_cache:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(res.url).write_text(
            json.dumps({"url": res.url, "status": res.status, "text": res.text,
                        "fetched_at": res.fetched_at.isoformat(), "hash": res.content_hash})
        )

    # -- main entry
    def get(self, url: str, *, force_refresh: bool = False) -> FetchResult:
        if not force_refresh:
            cached = self._read_cache(url)
            if cached:
                return cached

        policy = self.robots_for(url)
        parts = urlsplit(url)
        path = parts.path + (("?" + parts.query) if parts.query else "")
        if not policy.allowed(path):
            raise SourceUnavailable(url, "disallowed by robots.txt")

        delay = max(self.min_delay, policy.crawl_delay or 0.0)
        host = self._host(url)
        attempts = 0
        while True:
            attempts += 1
            self._wait_turn(host, delay)
            try:
                r = self.client.get(url)
            except httpx.HTTPError as e:
                if attempts < 2:
                    continue
                raise SourceUnavailable(url, f"network error: {e}") from e
            if r.status_code >= 500 and attempts < 2:
                continue
            break

        if r.status_code in (401, 402, 403, 407, 429, 451):
            raise SourceUnavailable(url, f"access restricted (HTTP {r.status_code})", r.status_code)
        if r.status_code == 404:
            raise SourceUnavailable(url, "not found (HTTP 404)", 404)
        if r.status_code != 200:
            raise SourceUnavailable(url, f"unexpected HTTP {r.status_code}", r.status_code)

        text = r.text
        head = text[:20000].lower()
        if any(m in head for m in BOT_CHALLENGE_MARKERS) and "sidearm" not in head:
            raise SourceUnavailable(url, "bot-protection / challenge page detected; not bypassing", r.status_code)

        res = FetchResult(
            url=url,
            status=r.status_code,
            text=text,
            fetched_at=datetime.now(timezone.utc),
            from_cache=False,
            content_hash=hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(),
        )
        self._write_cache(res)
        return res
