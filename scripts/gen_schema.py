"""Generate db/schema.sql (PostgreSQL / Supabase) from the SQLAlchemy models.

Run: python scripts/gen_schema.py
Then paste db/schema.sql into Supabase → SQL Editor → Run (or let the app create tables itself).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.models import Base  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "db" / "schema.sql"

HEADER = """-- ============================================================
-- The Athlete Market — Roster Intelligence
-- PostgreSQL / Supabase schema (generated from app/models.py by scripts/gen_schema.py)
-- Safe to run on an empty database. Re-generate after changing models.
-- ============================================================
"""

FOOTER = """
-- Supabase: this app connects with the database password from the server only.
-- Enable Row Level Security with no policies so the public anon/REST API can't read or write these tables.
""" + "\n".join(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;" for t in [
    "schools", "teams", "seasons", "sources", "roster_snapshots", "players", "roster_entries", "player_stats",
    "opportunities", "opportunity_evidence", "opportunity_sources", "score_history", "telegram_channels",
    "publishing_queue", "published_posts", "event_log",
]) + "\n"


def render() -> str:
    d = postgresql.dialect()
    parts = [HEADER]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=d)).strip() + ";\n")
        for idx in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(idx).compile(dialect=d)).strip() + ";\n")
    parts.append(FOOTER)
    return "\n".join(parts)


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT}")
