"""Static disc data constants.

Per-roll base values for each substat type (basis points for percentages,
absolute units for flat stats). Used to derive roll counts when the raw
substat entry does not store them explicitly.
"""

from __future__ import annotations

# Per-roll base value for each substat, by disc rarity. Percentages are in
# basis points (300 = 3.00%); flats are absolute. Rarities below S sourced
# from the ZO reference (`/tmp/genshin-optimizer/libs/zzz/consts/src/disc.ts`
# `subData`, itself marked "TODO: use dm values" there — treat A/B rows as
# community-sourced pending an official datamine cross-check) since this
# repo previously only carried the S-rank row and used it unconditionally
# for every rarity (issue #65).
SUBSTAT_BASE_PER_ROLL_BY_RARITY: dict[str, dict[str, int]] = {
    "S": {
        "hp_pct": 300,
        "atk_pct": 300,
        "def_pct": 480,
        "crit_rate": 240,
        "crit_dmg": 480,
        "pen_flat": 9,
        "anomaly_proficiency": 9,
        "hp": 112,
        "atk": 19,
        "def": 15,
    },
    "A": {
        "hp_pct": 200,
        "atk_pct": 200,
        "def_pct": 320,
        "crit_rate": 160,
        "crit_dmg": 320,
        "pen_flat": 6,
        "anomaly_proficiency": 6,
        "hp": 79,
        "atk": 15,
        "def": 10,
    },
    "B": {
        "hp_pct": 100,
        "atk_pct": 100,
        "def_pct": 160,
        "crit_rate": 80,
        "crit_dmg": 160,
        "pen_flat": 3,
        "anomaly_proficiency": 3,
        "hp": 39,
        "atk": 7,
        "def": 5,
    },
}

# Convenience alias for the S-rank row. No production caller reads this any
# more — every roll-count/roll-value path is rarity-aware as of #65. Kept only
# as the documented "default rarity" row; prefer indexing the table above by an
# explicit rarity so new callers can't silently inherit S-rank bases.
SUBSTAT_BASE_PER_ROLL: dict[str, int] = SUBSTAT_BASE_PER_ROLL_BY_RARITY["S"]


def compute_rolls(stat_type: str, value: int, rarity: str = "S") -> int:
    """Return the number of rolls for a substat given its total value.

    Falls back to 1 if the stat type or rarity is unknown, or the base is
    zero.
    """
    table = SUBSTAT_BASE_PER_ROLL_BY_RARITY.get(rarity, SUBSTAT_BASE_PER_ROLL_BY_RARITY["S"])
    base = table.get(stat_type, 0)
    if base <= 0:
        return 1
    return max(1, round(value / base))
