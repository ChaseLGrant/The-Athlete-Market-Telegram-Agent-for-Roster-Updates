import pytest

from app.analysis.common import name_key
from app.sports.baseball.positions import classify_position, normalize_class_year, parse_bats_throws
from app.sports.baseball.stats import ip_to_outs, normalize_batting, normalize_pitching


@pytest.mark.parametrize("raw,throws,primary,hit,pitch,two_way,conf", [
    ("C", None, "C", "C", None, False, 1.0),
    ("Catcher", None, "C", "C", None, False, 1.0),
    ("SS", None, "MIF", "MIF", None, False, 1.0),
    ("1B", None, "CIF", "CIF", None, False, 1.0),
    ("INF", None, "INF", "INF", None, False, 0.8),
    ("INF/OF", None, "INF", "INF", None, False, 0.7),
    ("INF/RHP", "R", "INF", "INF", "RHP", True, 0.7),
    ("RHP/1B", "R", "RHP", "CIF", "RHP", True, 0.7),
    ("Right-Handed Pitcher", None, "RHP", None, "RHP", False, 1.0),
    ("P", "L", "LHP", None, "LHP", False, 0.8),
    ("P", None, "P", None, "P", False, 0.5),
    ("UTL", None, "UT", "UT", None, False, 0.5),
    ("Water Boy", None, None, None, None, False, 0.0),
    ("", None, None, None, None, False, 0.0),
])
def test_classify_position(raw, throws, primary, hit, pitch, two_way, conf):
    r = classify_position(raw, throws)
    assert (r.primary, r.hitter_group, r.pitcher_group, r.is_two_way, r.confidence) == (
        primary, hit, pitch, two_way, conf)


@pytest.mark.parametrize("raw,expected", [
    ("Senior", ("SR", False)), ("Sr.", ("SR", False)), ("R-Sr.", ("SR", True)),
    ("Redshirt Senior", ("SR", True)), ("Graduate Student", ("GR", False)), ("Gr.", ("GR", False)),
    ("5th", ("GR", False)), ("Freshman", ("FR", False)), ("R-Fr.", ("FR", True)),
    ("Redshirt Sophomore", ("SO", True)), ("Junior", ("JR", False)),
    ("", ("UNKNOWN", None)), (None, ("UNKNOWN", None)), ("Walk-on", ("UNKNOWN", None)),
])
def test_class_year(raw, expected):
    assert normalize_class_year(raw) == expected


def test_bats_throws():
    assert parse_bats_throws("R/R") == ("R", "R")
    assert parse_bats_throws("S/L") == ("S", "L")
    assert parse_bats_throws("6-2") == (None, None)


def test_name_key():
    assert name_key("Samayoa, Zech") == name_key("Zech Samayoa") == "zech samayoa"
    assert name_key("Jaden St. Cyr") == "jaden st cyr"
    assert name_key("O'Neil, Tom Jr.") == "tom oneil"


def test_ip_to_outs():
    assert ip_to_outs("61.1") == 184
    assert ip_to_outs("52.2") == 158
    assert ip_to_outs("9.0") == 27
    assert ip_to_outs("3.4") is None  # invalid notation -> unknown, not guessed
    assert ip_to_outs("") is None


def test_normalize_batting_and_pitching():
    b = normalize_batting({"GP-GS": "47-40", "AB": "123", "BB": "19", "HBP": "9", "SF": "2", "SH": "3",
                           "TB": "43", "OPS": ".762", "SB-ATT": "1-2"})
    assert (b["gp"], b["gs"], b["pa"], b["production"], b["sb"], b["sb_att"], b["ops"]) == (
        47, 40, 156, 71, 1, 2, 0.762)
    partial = normalize_batting({"GP-GS": "3-0", "AB": "5"})
    assert partial["pa"] is None and partial["production"] is None  # unknown, not zero
    p = normalize_pitching({"APP-GS": "15-11", "IP": "61.1", "SV": "1", "SO": "52", "ERA": "4.55", "W-L": "7-2"})
    assert (p["app"], p["gs"], p["outs"], p["sv"], p["w"], p["l"]) == (15, 11, 184, 1, 7, 2)
