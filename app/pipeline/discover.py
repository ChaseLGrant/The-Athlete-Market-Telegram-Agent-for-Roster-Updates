"""Find programs to watch from the NCAA's official member directory (instead of typing URLs by hand).

    python -m app.cli discover --sport baseball --probe      # print what the directory returns
    python -m app.cli discover --sport baseball [--limit 50] # check sites, add the ones we can read

Every candidate site is checked with the same code as `verify` before it is added; nothing is guessed.
All requests go through PoliteFetcher (robots.txt, crawl delay).
"""
from __future__ import annotations

import json

from app.collectors.base import SourceUnavailable
from app.collectors.http import PoliteFetcher

DIRECTORY = "https://web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode={code}"
SPORT_CODES = {
    "baseball": "MBA", "softball": "WSB", "football": "MFB", "mens_basketball": "MBB",
    "womens_basketball": "WBB", "mens_soccer": "MSO", "womens_soccer": "WSO",
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
