"""Volleyball (added 2026-10-30 for Insider Plus): position tokens and grouped-header stat columns.
Checked on the real CSUSM women's volleyball 2026 roster + 2025 stats pages (offense/defense tables)."""
from app.sports import volleyball as vb
from app.sports.registry import registry


def test_positions_fold_into_groups():
    assert vb.classify("OH").primary == "OH"
    assert vb.classify("Outside Hitter").primary == "OH"
    assert vb.classify("RS").primary == "OPP"
    assert vb.classify("Middle Blocker").primary == "MB"
    assert vb.classify("Libero/Defensive Spe").primary == "LDS"
    p = vb.classify("S/DS")
    assert (p.primary, p.secondary) == ("S", "LDS")


def test_grouped_header_columns():
    off = vb.normalize("offense", {"SP": "91", "MP": "26", "MS": "20", "ATTACK K": "3", "SET A": "863"})
    assert (off["sp"], off["ms"], off["k"], off["a"]) == (91, 20, 3, 863)
    d = vb.normalize("defense", {"SP": "46", "DIG DIG": "18", "BLOCK BLK": "31"})
    assert (d["dig"], d["blk"]) == (18, 31)


def test_not_live_verified():
    for k in ("womens_volleyball", "mens_volleyball"):
        assert registry()[k].live_verified is False
