"""Shrink a saved official page into a test fixture: drop scripts, styles, images, SVG, nav/header/footer.
Roster cards and stats tables are kept exactly as served.

    python scripts/slim_fixture.py captured/*.html --out tests/fixtures/sidearm/
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment

# (not <form> or <header>: these sites wrap the whole page in a <form>)
DROP = ["script", "style", "noscript", "svg", "img", "picture", "source", "iframe", "link", "meta", "footer",
        "nav", "button", "video", "input", "select"]


def slim(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(DROP):
        if tag.name == "button" and tag.find_parent("th"):
            continue  # Sidearm puts the mobile player name in a <button> inside the stats <th>
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for tag in soup.find_all(True):
        for attr in [a for a in tag.attrs if a.startswith(("data-bind", "style", "onclick", "aria-"))]:
            del tag[attr]
    return re.sub(r"\n\s*\n+", "\n", str(soup))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        p = Path(f)
        (out / p.name).write_text(slim(p.read_text()))
        print(f"{p.name}: {p.stat().st_size // 1024} KB -> {(out / p.name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
