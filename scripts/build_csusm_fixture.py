"""Builds the CSUSM baseball test fixtures from values captured on 2026-09-28 from
the official Cal State San Marcos athletics site (Sidearm Sports):

  roster: https://csusmcougars.com/sports/baseball/roster   (page title "2026 Baseball Roster")
  stats:  https://csusmcougars.com/sports/baseball/stats/2026

The values below are copied from those pages. The HTML is re-rendered using the
exact Sidearm class names / table structure seen on the live pages (images,
scripts, navigation and ads removed to keep the fixture small).

Run:  python scripts/build_csusm_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sidearm"

# id | long position | short | ht | wt | B/T | jersey | name | year | hometown | previous school
ROSTER = """
7619|Infielder|INF|6'1"|220 lbs|R/R|1|Michael Weber|Senior|Pittsburg, Calif.|UC Riverside
7615|Infielder/Outfielder|INF/OF|6'1"|190 lbs|R/R|2|Rees Kent|Graduate Student|Clovis, Calif.|Saint Mary's College (CA)
7581|Infielder|INF|5'10"|175 lbs|L/R|3|Jake Callahan|Senior|Canyon Country, Calif.|Los Angeles Mission College
7622|Infielder|INF|6'1"|190 lbs|R/R|4|Jake Larson|Redshirt Junior|Farmington, Utah|Fullerton College
8402|Infielder|INF|6'3"|195 lbs|R/R|5|Devin Munoz|Junior|La Puente, Calif.|Pasadena City College
8401|Outfielder|OF|6'0"|185 lbs|R/R|6|Jacob Embleton|Junior|El Cajon, Calif.|Grossmont College
7578|Catcher|C|5'9"|195 lbs|R/R|7|Jake Adams|Senior|Moreno Valley, Calif.|Murrieta Valley HS
8383|Catcher|C|5'10"|195 lbs|R/R|8|Max Shor|Graduate Student|Palm Desert, Calif.|Fresno State
7620|Right-Handed Pitcher|RHP|6'4"|225 lbs|R/R|9|Mason Ali|Redshirt Junior|Elk Grove, Calif.|Butte CC
7582|Outfielder|OF|5'7"|170 lbs|L/R|10|Victor Castaneda|Junior|Chula Vista, Calif.|Bonita Vista HS
8406|Right-Handed Pitcher|RHP|6'4"|220 lbs|R/R|11|Jack Smith|Senior|Huntington Beach, Calif.|Central Michigan
7621|Infielder|INF|6'2"|205 lbs|R/R|12|Stephen Espinoza|Redshirt Senior|Lompoc, Calif.|San Francisco State
7587|Outfielder|OF|6'2"|220 lbs|R/R|13|Zech Samayoa|Redshirt Senior|Cerritos, Calif.|Long Beach State
7583|Left-Handed Pitcher|LHP|5'11"|175 lbs|L/L|14|Jack Clark|Sophomore|San Diego, Calif.|University City HS
8384|Infielder|INF|5'10"|180 lbs|L/R|15|Christopher Tampoya|Freshman|Westlake Village, Calif.|Oaks Christian School
8378|Right-Handed Pitcher|RHP|5'10"|175 lbs|R/R|16|Trevor Morgan|Redshirt Junior|San Diego, Calif.|Grossmont College
8391|Right-Handed Pitcher|RHP|6'0"|205 lbs|R/R|17|Espn Simpson|Sophomore|Riverside, Calif.|Butler
8400|Right-Handed Pitcher|RHP|6'5"|225 lbs|R/R|18|Isaac Cota|Junior|La Mesa, Calif.|Grossmont College
8379|Infielder/Right-Handed Pitcher|INF/RHP|6'2"|215 lbs|L/R|20|Mikey Gray|Freshman|Rancho Santa Margarita, Calif.|Trabuco Hills HS
8398|Right-Handed Pitcher/First Base|RHP/1B|6'1"|225 lbs|L/R|21|Ben Pernetti|Redshirt Junior|Elk Grove, Calif.|Cosumnes River College
7586|Right-Handed Pitcher|RHP|6'1"|195 lbs|R/R|22|Luke Higgins|Redshirt Senior|Laguna Beach, Calif.|Golden West College
8376|Left-Handed Pitcher|LHP|6'0"|170 lbs|L/L|23|Dylan Escobar|Redshirt Sophomore|Rancho Cucamonga, Calif.|Riverside City College
8404|Outfielder|OF|5'10"|195 lbs|R/R|24|Michael Ryan|Junior|Gridley, Calif.|Folsom Lake College
8377|Right-Handed Pitcher|RHP|6'2"|200 lbs|L/R|25|PJ Wendler|Graduate Student|Fullerton, Calif.|Claremont-Mudd-Scripps
8399|Infielder/Outfielder|INF/OF|6'0"|185 lbs|L/R|26|Owen Bolich|Junior|Bakersfield, Calif.|Allan Hancock College
8407|Outfielder|OF|5'11"|215 lbs|R/R|27|Blake Browning|Senior|Palm Desert, Calif.|College of the Redwoods
8394|Infielder|INF|6'2"|210 lbs|R/R|28|Collin Taylor|Redshirt Junior|Tarzana, Calif.|Los Angeles Valley College
7588|Right-Handed Pitcher|RHP|6'2"|185 lbs|R/R|29|Jack Swanberg|Freshman|Del Mar, Calif.|Torrey Pines HS
8396|Outfielder|OF|5'10"|195 lbs|L/R|30|Canon King|Freshman|Los Angeles, Calif.|Venice HS
8405|Right-Handed Pitcher|RHP|6'2"|175 lbs|R/R|32|Dylan Schmitt|Junior|Roseville, Calif.|Sierra College
8403|Right-Handed Pitcher|RHP|6'5"|230 lbs|R/R|33|Zach Romero|Senior|Chatsworth, Calif.|UC Davis
8387|Right-Handed Pitcher|RHP|6'1"|205 lbs|R/R|34|Micah Billings|Junior|Union City, Calif.|Laney College
8393|Outfielder|OF|6'0"|200 lbs|R/R|37|Leighton Helfrick|Graduate Student|Discovery Bay, Calif.|UC Davis
8382|Outfielder|OF|5'10"|165 lbs|R/R|39|Jaden St. Cyr|Redshirt Junior|Winchester, Calif.|Chaffey College
8392|Catcher|C|5'9"|180 lbs|R/R|40|Ethan Munoz|Junior|Simi Valley, Calif.|Cal State Fullerton
7614|RHP|RHP|5'9"|175 lbs|R/R|41|Shawn McBroom|Junior|Antioch, Calif.|Saint Mary's College (CA)
8389|Catcher|C|6'0"|185 lbs|R/R|42|Daniel Troncale|Freshman|Anaheim Hills, Calif.|Foothill HS
"""

BAT_HEAD = "#|Player|AVG|OPS|GP-GS|AB|R|H|2B|3B|HR|RBI|TB|SLG%|BB|HBP|SO|GDP|OB%|SF|SH|SB-ATT|Bio Link"
BATTING = """
13|Samayoa, Zech|.362|1.297|50-43|174|53|63|17|1|23|78|151|.868|18|4|28|0|.429|2|3|2-2
15|Tampoya, Christopher|.357|.978|43-40|126|33|45|13|1|1|25|63|.500|19|13|12|1|.478|3|3|3-4
4|Larson, Jake|.348|.926|42-26|92|22|32|8|0|2|21|46|.500|9|5|15|1|.426|2|5|2-3
30|King, Canon|.339|1.162|50-44|171|49|58|12|3|14|58|118|.690|32|11|26|2|.472|0|1|2-3
37|Helfrick, Leighton|.325|.784|46-41|154|32|50|7|2|1|24|64|.416|6|7|22|2|.368|4|6|6-8
12|Espinoza, Stephen|.314|.844|48-47|172|38|54|6|2|5|34|79|.459|19|2|25|3|.385|2|6|4-7
6|Embleton, Jacob|.313|.868|50-43|166|43|52|10|1|5|28|79|.476|16|6|16|3|.392|1|2|7-9
24|Ryan, Michael|.306|.784|41-25|98|29|30|3|0|0|14|33|.337|15|10|17|4|.447|0|4|2-4
1|Weber, Michael|.288|.790|50-49|156|29|45|7|1|2|30|60|.385|24|8|36|2|.405|2|4|4-5
8|Shor, Max|.285|.762|47-40|123|26|35|8|0|0|19|43|.350|19|9|26|3|.412|2|3|1-2
2|Kent, Rees|.263|.655|47-32|118|24|31|3|0|1|21|37|.314|10|4|21|2|.341|0|4|1-1
27|Browning, Blake|.571|1.953|8-0|7|1|4|2|0|1|2|9|1.286|2|0|2|0|.667|0|0|0-0
5|Munoz, Devin|.400|.971|6-1|5|2|2|0|0|0|1|2|.400|1|1|0|0|.571|0|0|0-0
3|Callahan, Jake|.333|.756|27-1|21|5|7|0|0|0|3|7|.333|4|0|5|1|.423|1|0|1-1
10|Castaneda, Victor|.293|.813|38-13|75|17|22|4|0|2|16|32|.427|8|4|19|0|.386|1|0|4-6
7|Adams, Jake|.269|.775|25-8|26|8|7|2|0|0|2|9|.346|8|0|6|0|.429|1|1|0-0
20|Gray, Mikey|.200|.672|38-9|30|12|6|2|0|0|10|8|.267|9|2|8|0|.405|1|0|1-2
28|Taylor, Collin|.200|.833|8-2|10|4|2|0|0|1|2|5|.500|2|0|3|0|.333|0|0|0-0
21|Pernetti, Ben|.200|.733|19-12|5|1|1|1|0|0|1|2|.400|1|0|3|0|.333|0|0|0-0
42|Troncale, Daniel|.077|.327|11-4|13|2|1|0|0|0|2|1|.077|3|0|7|1|.250|0|0|0-0
"""
BAT_FOOT = [
    "|Totals|.314|.900|52-52|1742|430|547|105|11|58|391|848|.487|225|86|297|25|.413|22|42|40-57",
    "|Opponents|.290|.828|52-52|1726|335|501|102|5|46|308|751|.435|219|96|324|39|.393|35|15|41-54",
]

PIT_HEAD = "#|Player|ERA|WHIP|W-L|APP-GS|CG|SHO|SV|IP|H|R|ER|BB|SO|2B|3B|HR|AB|B/AVG|WP|HBP|BK|SFA|SHA|Bio Link"
PITCHING = """
14|Clark, Jack|4.55|1.43|7-2|15-11|0|0-1|1|61.1|57|37|31|31|52|13|1|6|238|.239|1|6|0|3|4
25|Wendler, PJ|5.93|1.52|9-3|15-15|0|0-0|0|74.1|82|60|49|31|59|12|1|6|295|.278|8|15|0|7|1
21|Pernetti, Ben|6.25|1.78|1-4|15-11|0|0-1|2|59.0|79|46|41|26|40|13|0|6|245|.322|3|15|1|6|1
22|Higgins, Luke|6.32|1.69|3-3|13-12|1|0-1|0|52.2|63|40|37|26|34|14|1|4|205|.307|2|18|0|5|1
23|Escobar, Dylan|1.80|1.40|0-0|3-2|0|0-0|0|10.0|9|3|2|5|8|3|0|0|38|.237|1|2|1|0|1
32|Schmitt, Dylan|3.55|1.66|2-0|11-0|0|0-0|0|12.2|9|5|5|12|11|0|0|1|45|.200|3|9|0|0|1
33|Romero, Zach|4.11|1.29|4-3|20-0|0|0-1|3|35.0|33|18|16|12|23|8|0|3|132|.250|1|4|1|3|2
18|Cota, Isaac|5.20|1.66|2-0|12-0|0|0-0|0|27.2|36|18|16|10|23|10|0|3|111|.324|2|5|0|0|2
20|Gray, Mikey|5.96|1.95|1-0|11-1|0|0-0|1|25.2|32|18|17|18|18|6|1|1|103|.311|2|9|0|2|1
16|Morgan, Trevor|8.14|2.05|3-3|13-0|0|0-1|3|21.0|31|21|19|12|18|7|0|3|93|.333|3|2|0|2|0
11|Smith, Jack|8.31|2.00|0-0|11-0|0|0-1|0|13.0|19|17|12|7|8|3|0|3|54|.352|5|2|0|2|0
29|Swanberg, Jack|9.31|1.86|1-0|8-0|0|0-1|0|9.2|8|11|10|10|13|1|0|3|36|.222|5|1|0|1|0
9|Ali, Mason|9.64|1.61|0-1|11-0|0|0-0|1|18.2|23|22|20|7|10|5|0|6|77|.299|5|4|0|2|0
17|Simpson, Espn|10.13|2.38|0-0|5-0|0|0-0|0|8.0|13|12|9|6|6|5|1|1|36|.361|3|2|0|0|1
24|Ryan, Michael|10.80|2.70|0-0|4-0|0|0-0|0|3.1|4|4|4|5|1|2|0|0|12|.333|0|2|0|1|0
2|Kent, Rees|18.00|4.00|0-0|1-0|0|0-0|0|1.0|3|3|2|1|0|0|0|0|6|.500|0|0|0|1|0
"""

ROSTER_URL = "https://csusmcougars.com/sports/baseball/roster"
STATS_URL = "https://csusmcougars.com/sports/baseball/stats/2026"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slugify(name: str) -> str:
    return "-".join("".join(ch for ch in w.lower() if ch.isalnum()) for w in name.split())


def build_roster() -> tuple[str, dict[str, str]]:
    lis, ids = [], {}
    for line in ROSTER.strip().splitlines():
        pid, plong, pshort, ht, wt, bt, num, name, yr, home, prev = line.split("|")
        ids[name] = pid
        href = f"/sports/baseball/roster/{slugify(name)}/{pid}"
        lis.append(
            f'<li class="sidearm-roster-player" data-player-id="{pid}" data-player-url="{href}">'
            f'<div class="sidearm-roster-player-container flex row flex-wrap flex-align-center">'
            f'<div class="sidearm-roster-player-details flex flex-align-center large-6 x-small-12 full columns">'
            f'<div class="sidearm-roster-player-pertinents flex-item-1 column">'
            f'<div class="sidearm-roster-player-position"><span class="text-bold">'
            f'<span class="sidearm-roster-player-position-long-short hide-on-small-down"> {esc(plong)} </span>'
            f'<span class="sidearm-roster-player-position-long-short hide-on-medium"> {esc(pshort)} </span></span>'
            f'<span class="sidearm-roster-player-height">{esc(ht)}</span>'
            f'<span class="sidearm-roster-player-weight">{esc(wt)}</span>'
            f'<span class="sidearm-roster-player-custom1">{bt}</span></div>'
            f'<div class="sidearm-roster-player-name"><span class="sidearm-roster-player-jersey flex flex-inline">'
            f'<span class="sidearm-roster-player-jersey-number"> {num} </span></span><p></p>'
            f'<h3><a href="{href}" aria-label="{esc(name)} - View Full Bio">{esc(name)}</a></h3><p></p></div>'
            f'<div class="sidearm-roster-player-other hide-on-large"><div class="sidearm-roster-player-class-hometown">'
            f'<span class="sidearm-roster-player-academic-year hide-on-large">{esc(yr[:3])}.</span>'
            f'<span class="sidearm-roster-player-hometown">{esc(home)}</span>'
            f'<span class="sidearm-roster-player-previous-school">{esc(prev)}</span></div></div>'
            f'</div></div>'
            f'<div class="sidearm-roster-player-other flex-item-1 columns hide-on-medium-down">'
            f'<div class="sidearm-roster-player-class-hometown">'
            f'<span class="sidearm-roster-player-academic-year">{esc(yr)}</span>'
            f'<span class="sidearm-roster-player-hometown">{esc(home)}</span>'
            f'<span class="sidearm-roster-player-previous-school">{esc(prev)}</span></div></div>'
            f'</div></li>'
        )
    html = (
        "<!doctype html><html><head><title>2026 Baseball Roster - Cal State San Marcos Athletics</title></head>"
        '<body><div class="sidearm-roster-players-container"><ul class="sidearm-roster-players">'
        + "\n".join(lis)
        + "</ul></div></body></html>"
    )
    return html, ids


def _stat_table(caption: str, head: str, body: str, foot: list[str], ids: dict[str, str]) -> str:
    cols = head.split("|")
    th = "".join(f'<th scope="col">{esc(c)}</th>' for c in cols)
    rows = []
    for line in body.strip().splitlines():
        vals = line.split("|")
        num, pname = vals[0], vals[1]
        last, first = [x.strip() for x in pname.split(",", 1)]
        pid = ids[f"{first} {last}"]
        tds = "".join(
            f'<td data-label="{esc(c)}" class="text-center">{esc(v)}</td>' for c, v in zip(cols[2:], vals[2:])
        )
        rows.append(
            f'<tr class="stat_meets_min" role="row"><td class="text-center hide-on-medium-down" data-order="{num}">{num}</td>'
            f'<th class="text-no-wrap" scope="row"><a href="#" class="hide-on-medium-down" data-player-id="{pid}">'
            f'{esc(pname)}</a><button type="button" class="hide-on-large"><span class="mobile-jersey-number">{num}</span>'
            f' {esc(pname)}</button></th>{tds}'
            f'<td data-label="BIO" class="hide-on-large" aria-hidden="true"><a href="/sports/baseball/roster/{pid}">View Bio</a></td></tr>'
        )
    frows = []
    for line in foot:
        vals = line.split("|")
        frows.append("<tr><td></td><th>" + esc(vals[1]) + "</th>" + "".join(f"<td>{esc(v)}</td>" for v in vals[2:]) + "</tr>")
    return (
        f'<table class="sidearm-table highlight-column-hover"><caption>{esc(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody><tfoot>{''.join(frows)}</tfoot></table>"
    )


def build_stats(ids: dict[str, str]) -> str:
    return (
        "<!doctype html><html><head><title>2026 Baseball Cumulative Statistics - Cal State San Marcos Athletics</title>"
        "</head><body><section id=\"individual-overall-batting\">"
        + _stat_table("Individual Overall Batting Statistics", BAT_HEAD, BATTING, BAT_FOOT, ids)
        + "</section><section id=\"individual-overall-pitching\">"
        + _stat_table("Individual Overall Pitching Statistics", PIT_HEAD, PITCHING, [], ids)
        + "</section></body></html>"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    roster_html, ids = build_roster()
    (OUT / "csusm_baseball_roster.html").write_text(roster_html)
    (OUT / "csusm_baseball_stats_2026.html").write_text(build_stats(ids))
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest["csusm:baseball"] = {
        "school_name": "Cal State San Marcos",
        "captured_at": "2026-09-28T16:00:00+00:00",
        "roster": {"file": "csusm_baseball_roster.html", "url": ROSTER_URL},
        "stats": {"2026": {"file": "csusm_baseball_stats_2026.html", "url": STATS_URL}},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()
