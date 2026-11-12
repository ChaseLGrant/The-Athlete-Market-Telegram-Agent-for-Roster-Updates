"""Fulfillment Engine Phase 0: build CSVs of programs, coaches and roster-turnover opportunities from the roster
engine's own export (exports/opportunities.json.gz), for `fulfillment/load_public.sql`.

Rules (same as fulfillment-engine/mvp/engine.py):
- no record without a source URL; roster turnover is NEVER 'Verified Open Need'
- HIGH confidence + observed departures = 'Likely Future Need'; everything else 'Possible Fit'; expired = 'Unknown'
- coaches only when the export has name + email + an official staff/coach page URL on the roster's own site
Public data only (official rosters, stats and staff directories). No family data here.
"""
import csv, gzip, json, re, sys, urllib.parse
from datetime import datetime, timezone, timedelta

SPORT_MAP = {"baseball": ("baseball", "M"), "softball": ("softball", "F"), "football": ("football", "M"),
             "mens_basketball": ("basketball", "M"), "womens_basketball": ("basketball", "F"),
             "mens_soccer": ("soccer", "M"), "womens_soccer": ("soccer", "F"),
             "mens_volleyball": ("volleyball", "M"), "womens_volleyball": ("volleyball", "F")}
_HUMAN = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2}) (AM|PM) \w+ \(UTC([+-])(\d{2}):(\d{2})\)")


def ts(s):
    if not s:
        return None
    m = _HUMAN.search(str(s))
    if m:
        d, hh, mm, ap, sg, oh, om = m.groups()
        h = int(hh) % 12 + (12 if ap == "PM" else 0)
        off = timedelta(hours=int(oh), minutes=int(om)) * (1 if sg == "+" else -1)
        return datetime.fromisoformat(f"{d}T{h:02d}:{mm}:00").replace(tzinfo=timezone(off))
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


def official_coach(o, roster):
    c = o.get("coach") or {}
    src = c.get("source_url") or ""
    if not (c.get("email") and c.get("name") and src and roster):
        return None
    if urllib.parse.urlparse(src).netloc.lower() != urllib.parse.urlparse(roster).netloc.lower():
        return None
    if not re.search(r"/(coaches|staff|staff-directory)(/|$)", urllib.parse.urlparse(src).path.lower()):
        return None
    return c


def main(export_path, outdir):
    raw = json.load(gzip.open(export_path))
    gen = raw.get("generated_at")
    now = datetime.now(timezone.utc)
    progs, coaches, opps = {}, {}, []
    stats = {"records": 0, "skipped_sport": 0, "skipped_no_source": 0}
    for o in raw["opportunities"]:
        stats["records"] += 1
        if o.get("sport") not in SPORT_MAP:
            stats["skipped_sport"] += 1
            continue
        urls = [s["url"] for s in o.get("sources") or [] if s.get("url")]
        if not urls:
            stats["skipped_no_source"] += 1
            continue
        sport, gender = SPORT_MAP[o["sport"]]
        roster = next((s["url"] for s in o["sources"] if s.get("kind") == "roster"), None)
        statsu = next((s["url"] for s in o["sources"] if s.get("kind") == "stats"), None)
        key = (o["school_slug"], o["sport"])
        if key not in progs:
            progs[key] = [o["school"], o["school_slug"], sport, o["sport"], gender, o["division"], o.get("conference") or "",
                          o.get("state") or "", roster or "", statsu or "", "engine-export:" + str(gen),
                          roster or urls[0], iso(ts(o.get("last_verified_at")) or now)]
        c = official_coach(o, roster)
        if c and (key, c["name"]) not in coaches:
            coaches[(key, c["name"])] = [o["school_slug"], o["sport"], c["name"], c.get("title") or "",
                                         c["email"].strip().lower(), c["source_url"]]
        exp = ts(o.get("expires_at"))
        if exp and exp < now:
            status = "Unknown"
        elif o.get("confidence") == "HIGH" and o.get("departure_basis") == "observed":
            status = "Likely Future Need"
        else:
            status = "Possible Fit"
        opps.append([o["school_slug"], o["sport"], o["position_group"], o.get("position_label") or "",
                     o.get("target_season") or "", status, o.get("signal") if o.get("signal") is not None else "",
                     o.get("confidence") or "", (o.get("reason") or "")[:2000], urls[0], json.dumps(urls),
                     iso(ts(o.get("last_verified_at")) or now), "roster-pipeline:engine-export", iso(exp),
                     str(o.get("id")), "t" if status == "Unknown" else "f"])
    for name, rows in (("programs", progs.values()), ("coaches", coaches.values()), ("opportunities", opps)):
        with open(f"{outdir}/{name}.csv", "w", newline="") as f:
            csv.writer(f).writerows(rows)
    stats.update(programs=len(progs), coaches=len(coaches), opportunities=len(opps), generated_at=gen)
    print(json.dumps(stats))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
