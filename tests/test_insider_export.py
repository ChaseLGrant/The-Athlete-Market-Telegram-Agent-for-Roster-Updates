"""Insider Plus export: only items the team's latest research still produces, and the current text (2026-10-31)."""
import json
from datetime import timedelta

from sqlalchemy import select

from app.cli import export_opportunities
from app.models import Opportunity, RosterSnapshot, Status
from app.pipeline.research import run_research


def _research(db, now):
    run_research(db, "baseball", now=now)
    for snap in db.scalars(select(RosterSnapshot)):  # snapshots carry the wall clock; align with the fixed now
        snap.collected_at = now
    db.commit()


def _export(tmp_path):
    out = tmp_path / "opps.json"
    assert export_opportunities(str(out)) == 0
    return json.loads(out.read_text())["opportunities"]


def test_export_has_current_report_text_and_gate_flag(db, now, tmp_path):
    _research(db, now)
    o = db.scalar(select(Opportunity))
    assert o.metrics["gates_passed"] is True
    # a published item keeps the text that went to Telegram; the export renders the current one
    o.status, o.telegram_text = Status.PUBLISHED, "OLD TEXT 99 of 99"
    db.commit()
    rows = _export(tmp_path)
    assert len(rows) == 1
    assert rows[0]["telegram_text"] == "OLD TEXT 99 of 99"
    assert rows[0]["report_text"] and "OLD TEXT" not in rows[0]["report_text"]
    assert "Roster analysis only." in rows[0]["report_text"]


def test_export_drops_published_item_that_failed_the_gates(db, now, tmp_path):
    _research(db, now)
    o = db.scalar(select(Opportunity))
    o.status = Status.PUBLISHED
    o.metrics = {**o.metrics, "gates_passed": False, "gate_failures": ["signal 30 < 45"]}
    db.commit()
    assert _export(tmp_path) == []


def test_export_drops_item_not_reproduced_by_latest_research(db, now, tmp_path):
    _research(db, now)
    o = db.scalar(select(Opportunity))
    o.status = Status.PUBLISHED
    o.last_analyzed_at = now - timedelta(days=3)  # the team's roster was read again since; this group wasn't
    db.commit()
    assert _export(tmp_path) == []
