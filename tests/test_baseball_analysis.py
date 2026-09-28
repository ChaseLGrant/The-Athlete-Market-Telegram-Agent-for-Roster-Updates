"""The analyzer on real CSUSM 2026 data + synthetic 'new roster' scenarios."""
import copy

import pytest

from app.analysis.common import compute_signal, confidence_label, fingerprint
from app.collectors.base import RawRosterPlayer
from app.collectors.fixture import FixtureAdapter
from app.sports.baseball.team_input import FINAL_YEAR, INCOMING, NOT_ON_ROSTER, RETURNING, build_team_input
from app.sports.registry import get_sport


@pytest.fixture
def raw(csusm_team_ref):
    fx = FixtureAdapter()
    return fx.fetch_roster(csusm_team_ref), fx.fetch_stats(csusm_team_ref, "2026")


def _analyze(roster, stats, now, prev=None):
    ti = build_team_input(school_slug="csusm", school_name="Cal State San Marcos", division="NCAA D2",
                          conference="CCAA", current_roster=roster, stats=stats, stats_season_roster=prev)
    cfg = get_sport("baseball")
    return ti, {a.position_group: a for a in cfg.analyzer(ti, cfg, now=now)}


def test_catcher_opportunity_matches_hand_math(raw, now):
    ti, res = _analyze(*raw, now)
    assert ti.match_rate == 1.0 and ti.basis == "class_year_projection"
    c = res["C"]
    m = c.metrics
    # 4 listed catchers: Adams (Sr, 8 GS), Shor (Gr, 40 GS), Munoz (Jr, no stats), Troncale (Fr, 4 GS)
    assert (m["roster_count"], m["departing_count"], m["returning_count"]) == (4, 2, 2)
    assert (m["starts_departing"], m["starts_total"]) == (48, 52)
    assert (m["pa_departing"], m["pa_total"]) == (192, 208)
    assert (m["production_departing"], m["production_total"]) == (88, 92)
    assert m["returning_experienced_count"] == 0
    assert c.components["usage_departing"] == pytest.approx(0.9231, abs=1e-4)
    assert c.components["depth_gap"] == pytest.approx(1 / 3, abs=1e-3)
    assert c.passes_gates
    assert 70 <= c.signal <= 80
    assert c.confidence == "MEDIUM"  # class-year projection can never be HIGH
    assert c.target_season == "2027"
    statuses = {r["name"]: r["status"] for r in c.player_rows}
    assert statuses == {"Max Shor": FINAL_YEAR, "Jake Adams": FINAL_YEAR, "Ethan Munoz": RETURNING,
                        "Daniel Troncale": RETURNING}


def test_generic_infield_is_not_split(raw, now):
    _, res = _analyze(*raw, now)
    assert "INF" in res and "MIF" not in res and "CIF" not in res
    # two-way Pernetti (RHP/1B) counts in both infield and RHP groups
    assert any(r["name"] == "Ben Pernetti" for r in res["INF"].player_rows)
    assert any(r["name"] == "Ben Pernetti" for r in res["RHP"].player_rows)


def test_only_catcher_passes_gates_for_csusm(raw, now):
    _, res = _analyze(*raw, now)
    assert [k for k, a in res.items() if a.passes_gates] == ["C"]
    assert "no departing players" in res["LHP"].gate_failures


def test_observed_mode_with_new_roster(raw, now):
    roster26, stats = raw
    roster27 = copy.deepcopy(roster26)
    roster27.season_label = "2027"
    departed = {"Max Shor", "Jake Adams", "Zech Samayoa"}
    roster27.players = [p for p in roster27.players if p.name not in departed]
    roster27.players.append(RawRosterPlayer(name="New Catcher", site_player_id="9999", jersey="44",
                                            position_raw="C", class_year_raw="Freshman", bats_throws="R/R"))
    ti, res = _analyze(roster27, stats, now, prev=roster26)
    assert ti.basis == "observed"
    c = res["C"]
    st = {r["name"]: r["status"] for r in c.player_rows}
    assert st["Max Shor"] == NOT_ON_ROSTER and st["Jake Adams"] == NOT_ON_ROSTER
    assert st["New Catcher"] == INCOMING
    assert c.metrics["known_incoming_count"] == 1
    assert c.components["incoming"] == pytest.approx(1 / 3, abs=1e-3)
    assert c.confidence == "HIGH"  # observed departures + perfect match + tier A + fresh
    assert "no longer listed on the current roster" in c.reason


def test_unmatched_stats_lower_quality(raw, now):
    roster, stats = raw
    stats = copy.deepcopy(stats)
    for row in stats.tables["batting"][:8]:
        row.site_player_id, row.name = None, "Mystery, Player" + row.name
    ti, res = _analyze(roster, stats, now)
    assert ti.match_rate < 0.8
    assert len(ti.unmatched_stats) == 8
    assert res["C"].data_quality < _analyze(*raw, now)[1]["C"].data_quality


def test_stale_fetch_lowers_quality(raw, now):
    from datetime import timedelta

    _, fresh = _analyze(*raw, now)
    _, old = _analyze(*raw, now + timedelta(days=60))
    assert old["C"].quality_parts["recency"] < fresh["C"].quality_parts["recency"]
    assert old["C"].signal < fresh["C"].signal


def test_signal_helpers():
    cfg = get_sport("baseball")
    full = compute_signal({"turnover": 1, "usage_departing": 1, "production_departing": 1, "depth_gap": 1,
                           "experience_gap": 1, "incoming": 0}, cfg.weights, 1.0)
    assert full.signal == 100
    unknown = compute_signal({"turnover": None, "usage_departing": None}, cfg.weights, 1.0)
    assert unknown.signal == 0  # unknown never inflates a score
    assert confidence_label(0.95, 0.95, "class_year_projection") == "MEDIUM"
    assert confidence_label(0.95, 0.95, "observed") == "HIGH"
    assert confidence_label(0.6, 1.0, "observed") == "LOW"
    assert fingerprint("baseball", "csusm", "C", "2027", "roster_opportunity") == \
        fingerprint("Baseball", "CSUSM ", "c", "2027", "roster_opportunity")


def test_all_seven_sports_registered_with_own_weights():
    from app.sports.registry import registry

    r = registry()
    assert set(r) == {"baseball", "football", "softball", "mens_basketball", "womens_basketball",
                      "mens_soccer", "womens_soccer"}
    assert r["baseball"].implemented and not r["football"].implemented
    assert r["mens_basketball"].weights.usage_departing != r["baseball"].weights.usage_departing
    assert r["mens_basketball"] is not r["womens_basketball"]
