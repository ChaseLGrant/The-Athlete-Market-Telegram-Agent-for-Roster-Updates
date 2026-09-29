from app.content.guardrails import DISCLAIMER, check_telegram, check_x, x_length
from app.content.telegram_post import build_roster_post, build_verified_post, build_x_teaser

METRICS = {"roster_count": 4, "departing_count": 2, "returning_count": 2, "returning_experienced_count": 0,
           "known_incoming_count": 0, "starts_departing_share": 0.9231, "starts_departing": 48, "starts_total": 52}
COMP = {"usage_departing": 0.92, "experience_gap": 1.0, "depth_gap": 0.33}


def post(**kw):
    args = dict(school_name="Cal State San Marcos", division="NCAA D2", sport_name="Baseball", group="C",
                position_label="Catcher", basis="class_year_projection", stats_season="2026", target_season="2027",
                metrics=METRICS, components=COMP,
                sources=[("Official Roster", "https://csusmcougars.com/sports/baseball/roster"),
                         ("Official Statistics", "https://csusmcougars.com/sports/baseball/stats/2026")])
    args.update(kw)
    return build_roster_post(**args)


def test_roster_post_format_and_guardrails():
    t = post()
    assert t.startswith("📋 <b>TAM SCOUTING REPORT</b>")
    assert "NCAA D2 BASEBALL" in t and "<b>Position:</b> Catcher" in t
    assert "• 4 catchers listed in 2026\n• 2 of them are seniors/grad students" in t
    assert "• They made 92% of the starts by listed catchers (48 of 52)" in t
    assert ("The bulk of the work behind the plate could be walking out the door, with little proven experience "
            "left on the depth chart. Reps behind the plate may be up for grabs in 2027.") in t
    assert "🔵 ROSTER OPPORTUNITY" in t and DISCLAIMER in t
    assert '<a href="https://csusmcougars.com/sports/baseball/roster">Official Roster</a>' in t
    assert "some listed seniors could return" in t  # projection caveat
    # projection only knows they aren't seniors; never claim they "remain"
    assert "• 2 other catchers listed, 0 with significant 2026 experience" in t
    assert check_telegram(t, "roster_opportunity").ok
    observed = post(basis="observed")
    assert "• 2 of the 4 are on the current roster, 0 with significant 2026 experience" in observed
    assert "• 2 of them are off the current roster" in observed and "could return" not in observed


def test_one_remaining_player_reads_as_singular():
    one = dict(METRICS, returning_count=1, returning_experienced_count=1)
    t = post(group="RHP", position_label="Right-Handed Pitcher", metrics=one)
    assert "• 1 other right-handed pitcher listed, with significant 2026 experience" in t
    assert "Innings among the right-handed arms" in t
    assert "without significant" in post(metrics=dict(METRICS, returning_count=1))
    assert "• 1 of the 4 is on the current roster" in post(basis="observed", metrics=one)
    solo = post(metrics=dict(METRICS, departing_count=1))
    assert "• That player made 92% of the starts" in solo


def test_school_names_are_escaped():
    t = post(school_name="Texas A&M <Test>")
    assert "Texas A&amp;M &lt;Test&gt;" in t
    assert check_telegram(t, "roster_opportunity").ok


def test_guardrails_block_misleading_claims():
    base = post()
    for bad in ["This school needs a catcher.", "They are recruiting catchers.", "Scholarship available!",
                "There is an open roster spot.", "Coaches are interested in you."]:
        r = check_telegram(base.replace("🧠", bad + "\n🧠"), "roster_opportunity")
        assert not r.ok, bad
    assert not check_telegram(base.replace(DISCLAIMER, ""), "roster_opportunity").ok
    assert not check_telegram(base.replace("🔵 ROSTER OPPORTUNITY", "🟢 VERIFIED NEED"), "roster_opportunity").ok
    assert not check_telegram(base + "<script>x</script>", "roster_opportunity").ok
    assert not check_telegram(base + "<b>unclosed", "roster_opportunity").ok


def test_x_teaser():
    x = build_x_teaser(sport_name="Baseball", division="NCAA D2", group="C", basis="class_year_projection",
                       stats_season="2026", metrics=METRICS, join_link="https://t.me/tam_baseball")
    assert x.startswith("📋 COLLEGE BASEBALL SCOUTING REPORT")
    assert "One NCAA D2 program could lose the players who made ~92% of its catcher starts in 2026." in x
    assert "Full scouting report free in Telegram ↓" in x
    assert x_length(x) <= 280
    assert check_x(x, "roster_opportunity", ["Cal State San Marcos"]).ok
    assert not check_x(x + " Cal State San Marcos", "roster_opportunity", ["Cal State San Marcos"]).ok


def test_verified_post():
    t = build_verified_post(school_name="Example U", division="NCAA D3", sport_name="Baseball",
                            position_label="Catcher", summary="Head coach posted that the program is recruiting "
                            "2027 catchers.", source_label="Official program post", source_url="https://ex.edu/n")
    assert "🟢 VERIFIED NEED" in t and check_telegram(t, "verified_need").ok


def test_teaser_must_not_reveal_short_name_either():
    names = ["Cal State San Marcos", "CSUSM"]
    assert not check_x("Big turnover at catcher for CSUSM.", "roster_opportunity", names).ok
    assert check_x("Big turnover at catcher for a D2 program.", "roster_opportunity", names).ok
    # whole words only: a 2-letter short name like "UC" must not flag ordinary words
    assert check_x("Lucky program with turnover.", "roster_opportunity", ["UC"]).ok
