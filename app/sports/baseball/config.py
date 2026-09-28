"""Baseball configuration. Tune weights/targets here (see docs/BASEBALL_METHODOLOGY.md)."""
from app.sports.base import PositionGroupSpec, QualityWeights, SignalWeights

POSITIONS = (
    PositionGroupSpec("C", "Catcher", "hitter", target_depth=3, target_experienced=1, min_volume=10),
    PositionGroupSpec("INF", "Infield", "hitter", target_depth=6, target_experienced=3, min_volume=10),
    PositionGroupSpec("MIF", "Middle Infield", "hitter", target_depth=3, target_experienced=2, min_volume=10),
    PositionGroupSpec("CIF", "Corner Infield", "hitter", target_depth=3, target_experienced=2, min_volume=10),
    PositionGroupSpec("OF", "Outfield", "hitter", target_depth=5, target_experienced=3, min_volume=10),
    PositionGroupSpec("RHP", "Right-Handed Pitcher", "pitcher", target_depth=10, target_experienced=4, min_volume=30),
    PositionGroupSpec("LHP", "Left-Handed Pitcher", "pitcher", target_depth=4, target_experienced=1, min_volume=30),
)

WEIGHTS = SignalWeights(
    turnover=0.15,
    usage_departing=0.30,
    production_departing=0.20,
    depth_gap=0.20,
    experience_gap=0.15,
    incoming_penalty=0.15,
    transfer_penalty=0.0,  # transfers-in are counted inside "incoming" for baseball v1
)

QUALITY_WEIGHTS = QualityWeights()

# experienced returner thresholds
HITTER_EXPERIENCED_GS = 15
HITTER_EXPERIENCED_PA = 60
PITCHER_EXPERIENCED_IP = 20.0
PITCHER_EXPERIENCED_GS = 5
STARTER_GS_RATIO = 0.5

MIN_CANDIDATE_SIGNAL = 45.0
