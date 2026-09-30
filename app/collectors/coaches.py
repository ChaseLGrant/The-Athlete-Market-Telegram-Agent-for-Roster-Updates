"""Head coach contact from a program's OFFICIAL athletics site (Sidearm).

Players reading a post can email the coaching staff directly, so we show the head coach's work email
at the bottom, but only when the school itself publishes it. Never guessed, never built from a
pattern like first.last@school.edu. No email on the official pages means no email in the post.

Where Sidearm sites publish it (tried in this order, each page fetched politely and at most once):
  1. the roster page itself: newer sites show staff "person cards" with name, title and a mailto link
  2. the head coach's bio page, linked from older roster pages ("Full Bio")
  3. the coaching staff page: {base}/sports/{sport}/coaches
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}$")
HEAD_RE = re.compile(r"\bhead\b.{0,40}?\bcoach\b", re.I)
NOT_HEAD_RE = re.compile(r"\b(assistant|asst\.?|associate|assoc\.?|volunteer|graduate|student|strength|"
                         r"conditioning|athletic trainer|director of)\b", re.I)
SKIP_AREAS = ("footer", "header", "nav")


@dataclass
class RawCoach:
    name: str
    title: str
    email: str | None
    source_url: str
    bio_url: str | None = None


def _txt(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def is_head_coach(title: str | None) -> bool:
    """'Head Coach', 'Head Softball Coach', 'Associate AD for Administration/Head Coach' (one of several roles),
    but never 'Associate Head Coach' or 'Assistant Head Coach'."""
    return head_role(title) is not None


def head_role(title: str | None) -> str | None:
    """The head-coach part of a combined title ('Associate AD for Administration/Head Coach' -> 'Head Coach')."""
    return next((r for r in re.split(r"\s*[/;|]\s*|\s*,\s*", title or "")
                 if HEAD_RE.search(r) and not NOT_HEAD_RE.search(r)), None)


def _email(a: Tag) -> str | None:
    href = unquote(a.get("href", ""))
    if not href.lower().startswith("mailto:"):
        return None
    addr = href[7:].split("?", 1)[0].strip()
    return addr.lower() if EMAIL_RE.fullmatch(addr) else None


def _in_skipped_area(el: Tag) -> bool:
    for p in el.parents:
        if not isinstance(p, Tag):
            continue
        cls = " ".join(p.get("class", [])).lower()
        if p.name in SKIP_AREAS and not re.search(r"bio|coach|staff|person", cls):
            return True  # the site's own header/footer/nav (a coach bio's <header> block is fine)
        if re.search(r"(^|[\s_-])(footer|site-header|main-nav|navigation)([\s_-]|$)", cls):
            return True
    return False


def _cards(soup: BeautifulSoup, url: str) -> list[RawCoach]:
    """Newer Sidearm 's-person-card' blocks (roster pages and coaches pages)."""
    out = []
    for card in soup.find_all(class_="s-person-card"):
        title = _txt(card.find(class_=re.compile(r"s-person-details__position")))
        head = card.find(["h2", "h3", "h4"])
        name = _txt(head)
        mails = {e for a in card.select('a[href^="mailto:"], a[href^="MAILTO:"]') if (e := _email(a))}
        if not name or not title:
            continue
        bio = card.find("a", href=re.compile(r"/coaches/"))
        out.append(RawCoach(name[:120], title[:120], mails.pop() if len(mails) == 1 else None, url,
                            urljoin(url, bio["href"]) if bio else None))
    return out


def _classic_roster_coaches(soup: BeautifulSoup, url: str) -> list[RawCoach]:
    """Older roster pages: '.sidearm-roster-coach' list items (name, title, Full Bio link; no email)."""
    out = []
    for li in soup.select(".sidearm-roster-coach"):
        name = _txt(li.select_one(".sidearm-roster-coach-name"))
        title = _txt(li.select_one(".sidearm-roster-coach-title"))
        if not name or not title:
            continue
        mails = {e for a in li.select('a[href^="mailto:"]') if (e := _email(a))}
        link = li.select_one(".sidearm-roster-coach-link a[href]") or li.find("a", href=re.compile(r"/coaches/"))
        out.append(RawCoach(name[:120], title[:120], mails.pop() if len(mails) == 1 else None, url,
                            urljoin(url, link["href"]) if link else None))
    return out


def _table_rows(soup: BeautifulSoup, url: str) -> list[RawCoach]:
    """Coaching staff tables: one row per person with a title cell and (usually) a mailto link."""
    out = []
    for tr in soup.find_all("tr"):
        if _in_skipped_area(tr):
            continue
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        texts = [_txt(c) for c in cells]
        title = next((t for t in texts if "coach" in t.lower() and len(t) <= 80), None)
        if not title:
            continue
        mails = {e for a in tr.select('a[href^="mailto:"]') if (e := _email(a))}
        name_cell = next((c for c, t in zip(cells, texts) if t and t != title and "@" not in t
                          and not re.search(r"\d{3}", t)), None)
        name = _txt(name_cell)
        if not name:
            continue
        bio = tr.find("a", href=re.compile(r"/coaches/"))
        out.append(RawCoach(name[:120], title[:120], mails.pop() if len(mails) == 1 else None, url,
                            urljoin(url, bio["href"]) if bio else None))
    return out


def parse_staff(html: str, url: str) -> list[RawCoach]:
    """Every coach we can read on a page (roster page or coaching staff page), with emails when shown."""
    soup = BeautifulSoup(html, "lxml")
    seen, out = set(), []
    for c in _cards(soup, url) + _classic_roster_coaches(soup, url) + _table_rows(soup, url):
        key = c.name.lower()
        if key in seen:
            if c.email:  # keep the entry that has the email
                out = [c if o.name.lower() == key and not o.email else o for o in out]
            continue
        seen.add(key)
        out.append(c)
    return out


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]+", name.lower()) if len(t) >= 3]


def email_on_bio_page(html: str, coach_name: str) -> str | None:
    """The coach's own email on their bio page. Accept a mailto only if it is labelled as the email field
    of the bio, or its address contains the coach's last name, and it isn't in the header/footer.
    One unambiguous address or nothing."""
    soup = BeautifulSoup(html, "lxml")
    last = (_name_tokens(coach_name) or [""])[-1]
    found = set()
    for a in soup.select('a[href^="mailto:"], a[href^="MAILTO:"]'):
        e = _email(a)
        if not e or _in_skipped_area(a):
            continue
        labelled = False
        dd = a.find_parent("dd")
        if dd is not None:
            dt = dd.find_previous_sibling("dt")
            labelled = bool(dt and "mail" in _txt(dt).lower())
        box = a.find_parent(class_=re.compile(r"bio|coach|person|staff", re.I))
        if (labelled and box is not None) or (last and last in e.split("@")[0]):
            found.add(e)
    return found.pop() if len(found) == 1 else None


def pick_head_coach(coaches: list[RawCoach]) -> RawCoach | None:
    heads = [c for c in coaches if is_head_coach(c.title)]
    return heads[0] if len(heads) >= 1 else None


def coaches_url(base_url: str, sport_path: str) -> str:
    return f"{base_url.rstrip('/')}/sports/{sport_path}/coaches"


def same_site(url: str, base_url: str) -> bool:
    a, b = urlparse(url).netloc.lower(), urlparse(base_url).netloc.lower()
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    return strip(a) == strip(b)
