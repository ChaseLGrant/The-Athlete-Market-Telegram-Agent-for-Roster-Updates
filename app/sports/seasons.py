"""Season labels, the way official athletics sites write them.

  spring  baseball, softball       "2026"     (played Feb–June 2026)
  fall    football, soccer         "2025"     (played Aug–Dec 2025)
  winter  basketball               "2025-26"  (played Nov 2025–Mar 2026)

Seasons are compared by their start year, which is the first four digits of every label.
"""
from __future__ import annotations

from datetime import date

STYLES = ("spring", "fall", "winter")


def start_year(label: str | None) -> int | None:
    """'2025-26' -> 2025, '2026' -> 2026, anything else -> None."""
    if label and len(label) >= 4 and label[:4].isdigit():
        return int(label[:4])
    return None


def label_for(style: str, year: int) -> str:
    if style == "winter":
        return f"{year}-{(year + 1) % 100:02d}"
    return str(year)


def next_season(label: str, style: str) -> str:
    y = start_year(label)
    return label_for(style, y + 1) if y is not None else label


def latest_completed_season(style: str, today: date) -> str:
    """The most recent season whose final stats are published."""
    if style == "spring":  # done by late June
        return label_for(style, today.year if today.month >= 7 else today.year - 1)
    if style == "fall":  # done by mid December; wait for January to be safe
        return label_for(style, today.year - 1)
    if style == "winter":  # done by early April
        return label_for(style, today.year - 1 if today.month >= 5 else today.year - 2)
    raise ValueError(f"unknown season style {style!r}")
