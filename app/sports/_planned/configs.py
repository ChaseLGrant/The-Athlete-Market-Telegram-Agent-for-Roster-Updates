"""Configs for the six sports that come after baseball.

Positions, key stats and weights are defined now so the database, queue,
channels and admin already support them. Their analyzers are intentionally NOT
implemented yet (implemented=False): research skips them and logs why, rather
than producing unreliable output.
"""
from app.sports.base import PositionGroupSpec as P, SignalWeights

# ---------------------------------------------------------------- football
FOOTBALL_POSITIONS = tuple(
    P(k, label, "field", depth, exp, min_volume=3)
    for k, label, depth, exp in [
        ("QB", "Quarterback", 4, 1), ("RB", "Running Back", 4, 2), ("WR", "Wide Receiver", 8, 3),
        ("TE", "Tight End", 4, 2), ("OT", "Offensive Tackle", 5, 2), ("OG", "Offensive Guard", 5, 2),
        ("C", "Center", 3, 1), ("EDGE", "Edge Rusher", 6, 2), ("DL", "Defensive Line", 7, 3),
        ("LB", "Linebacker", 7, 3), ("CB", "Cornerback", 7, 3), ("S", "Safety", 6, 2),
        ("K", "Kicker", 2, 1), ("P", "Punter", 2, 1),
    ]
)
FOOTBALL_KEY_STATS = {
    "passing": ("att", "cmp", "yds", "td", "int", "gs"),
    "rushing": ("car", "yds", "td"),
    "receiving": ("rec", "yds", "td", "tgt"),
    "defense": ("tkl", "tfl", "sacks", "int", "pd", "gs"),
    "kicking": ("fgm", "fga", "punts", "avg"),
}
FOOTBALL_WEIGHTS = SignalWeights(0.10, 0.30, 0.20, 0.20, 0.20, 0.15, 0.10)

# ---------------------------------------------------------------- softball
SOFTBALL_POSITIONS = (
    P("C", "Catcher", "hitter", 3, 1, 10), P("INF", "Infield", "hitter", 6, 3, 10),
    P("MIF", "Middle Infield", "hitter", 3, 2, 10), P("CIF", "Corner Infield", "hitter", 3, 2, 10),
    P("OF", "Outfield", "hitter", 5, 3, 10), P("UT", "Utility", "hitter", 3, 1, 10),
    P("RHP", "Right-Handed Pitcher", "pitcher", 4, 2, 30), P("LHP", "Left-Handed Pitcher", "pitcher", 2, 1, 30),
)
SOFTBALL_KEY_STATS = {
    "batting": ("gp", "gs", "ab", "pa", "h", "bb", "hbp", "tb", "avg", "obp", "slg"),
    "pitching": ("app", "gs", "ip", "era", "whip", "so", "sv"),
}
SOFTBALL_WEIGHTS = SignalWeights(0.15, 0.30, 0.20, 0.20, 0.15, 0.15)

# ---------------------------------------------------------------- basketball (M & W separate sports)
BASKETBALL_POSITIONS = (
    P("PG", "Point Guard", "court", 2, 1, 100), P("SG", "Shooting Guard", "court", 2, 1, 100),
    P("SF", "Small Forward", "court", 2, 1, 100), P("PF", "Power Forward", "court", 2, 1, 100),
    P("C", "Center", "court", 2, 1, 100),
)
BASKETBALL_KEY_STATS = {"overall": ("gp", "gs", "min", "pts", "reb", "ast", "usg")}
# minutes & starts dominate
BASKETBALL_WEIGHTS = SignalWeights(0.10, 0.40, 0.15, 0.20, 0.15, 0.15, 0.10)

# ---------------------------------------------------------------- soccer (M & W separate sports)
SOCCER_POSITIONS = (
    P("GK", "Goalkeeper", "gk", 3, 1, 180), P("CB", "Center Back", "field", 4, 2, 180),
    P("FB", "Fullback / Wingback", "field", 4, 2, 180), P("DM", "Defensive Midfielder", "field", 3, 1, 180),
    P("CM", "Central Midfielder", "field", 4, 2, 180), P("AM", "Attacking Midfielder", "field", 3, 1, 180),
    P("W", "Winger", "field", 4, 2, 180), P("ST", "Striker / Forward", "field", 4, 2, 180),
)
SOCCER_KEY_STATS = {
    "field": ("gp", "gs", "min", "g", "a"),
    "goalkeeping": ("gp", "gs", "min", "saves", "ga", "shutouts"),
}
# returning minutes + positional depth heavily weighted
SOCCER_WEIGHTS = SignalWeights(0.10, 0.35, 0.10, 0.25, 0.20, 0.15, 0.10)
