"""Task B1 — F-31: canonical per-roll substat base table (unit tests).

Also covers Task B4/B5 (issue #65) — pins, then verifies the fix for, the
disagreement between the two backend roll counters,
`disc_constants.compute_rolls` and `disc_scorer._count_rolls`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.data.importers import scanner_importer
from app.services.disc_constants import (
    SUBSTAT_BASE_PER_ROLL,
    SUBSTAT_BASE_PER_ROLL_BY_RARITY,
    compute_rolls,
)
from app.services.disc_optimizer import DiscCandidate
from app.services.disc_scorer import _count_rolls


def test_flat_stat_bases_present() -> None:
    assert SUBSTAT_BASE_PER_ROLL["hp"] == 112
    assert SUBSTAT_BASE_PER_ROLL["atk"] == 19
    assert SUBSTAT_BASE_PER_ROLL["def"] == 15


def test_compute_rolls_flat_atk_five_rolls() -> None:
    assert compute_rolls("atk", 95) == 5


def test_compute_rolls_flat_atk_one_roll_falls_back_correctly() -> None:
    assert compute_rolls("atk", 19) == 1


def test_scanner_importer_shares_canonical_table() -> None:
    """The importer must read the rarity-aware table, not the S-rank alias —
    it imports discs of every rarity.
    """
    assert scanner_importer.SUBSTAT_BASE_PER_ROLL_BY_RARITY is SUBSTAT_BASE_PER_ROLL_BY_RARITY


def test_compute_rolls_a_rank_atk_uses_a_rank_base() -> None:
    """A real A-rank ATK roll is +15 (ZO reference:
    `/tmp/genshin-optimizer/libs/zzz/consts/src/disc.ts` `subData.atk.A`).
    Two A-rank rolls (+30) must resolve to 2, not `round(30/19) == 2` by
    coincidence — three rolls (+45) is the case that tells them apart:
    against the S-rank base that's `round(45/19) == 2`, undercounting.
    """
    assert compute_rolls("atk", 15, rarity="A") == 1
    assert compute_rolls("atk", 45, rarity="A") == 3


def test_compute_rolls_b_rank_def_uses_b_rank_base() -> None:
    """A real B-rank DEF roll is +5 (ZO reference: `subData.def.B`)."""
    assert compute_rolls("def", 5, rarity="B") == 1
    assert compute_rolls("def", 15, rarity="B") == 3


def test_s_rank_disc_roll_count_agrees_across_both_counters() -> None:
    """B4(a) — an S-rank disc's total, summed per-substat via
    `compute_rolls`, must match what `disc_scorer._count_rolls` counts for
    the same disc. Both modules use S-rank bases (`hp: 112, atk: 19,
    def: 15`), so for exact-multiple S-rank values (the only values the
    game can actually produce — every roll adds exactly one base
    increment, never a partial one) the two implementations should never
    diverge. This held even before B5's fix; kept as an invariant guard.
    """
    disc = DiscCandidate(
        disc_id="s-rank-1",
        slot=1,
        set_id=1,
        main_stat_type="hp",
        main_stat_value=2200,
        substats=[
            {"stat": "atk", "value": 19 * 3},  # 3 rolls
            {"stat": "def", "value": 15 * 2},  # 2 rolls
            {"stat": "crit_rate", "value": 240 * 1},  # 1 roll
        ],
    )
    expected = (
        compute_rolls("atk", 19 * 3)
        + compute_rolls("def", 15 * 2)
        + compute_rolls("crit_rate", 240 * 1)
    )
    assert expected == 6
    assert _count_rolls(disc, "S") == expected


def test_a_rank_flat_atk_substat_counts_the_real_roll() -> None:
    """B4(b)/B5 — a real A-rank flat ATK roll is +15 (ZO reference:
    `/tmp/genshin-optimizer/libs/zzz/consts/src/disc.ts` `subData.atk.A`),
    smaller than the S-rank base (+19) `_count_rolls` used to floor-divide
    by regardless of rarity (`15 // 19 == 0`, losing the roll entirely).
    Now rarity-aware, it must count exactly 1.
    """
    disc = DiscCandidate(
        disc_id="a-rank-1",
        slot=2,
        set_id=1,
        main_stat_type="hp",
        main_stat_value=1468,
        substats=[{"stat": "atk", "value": 15}],
    )
    assert _count_rolls(disc, "A") == 1


def test_b_rank_flat_def_substat_counts_the_real_roll() -> None:
    """B4(b)/B5 — a real B-rank flat DEF roll is +5 (ZO reference:
    `/tmp/genshin-optimizer/libs/zzz/consts/src/disc.ts` `subData.def.B`),
    smaller than the S-rank base (+15) `_count_rolls` used to floor-divide
    by unconditionally (`5 // 15 == 0`). Now rarity-aware, it must count
    exactly 1.
    """
    disc = DiscCandidate(
        disc_id="b-rank-1",
        slot=3,
        set_id=1,
        main_stat_type="hp",
        main_stat_value=734,
        substats=[{"stat": "def", "value": 5}],
    )
    assert _count_rolls(disc, "B") == 1


@pytest.mark.parametrize(
    ("rarity", "level", "upgrades"),
    [
        ("A", 12, (2, 2, 1)),  # A-rank: 3 substats, 5 total rolls
        ("B", 9, (1, 1, 1)),  # B-rank: 3 substats, 3 total rolls
    ],
)
def test_scanner_imported_disc_round_trips_through_count_rolls(
    rarity: str,
    level: int,
    upgrades: tuple[int, int, int],
) -> None:
    """B5 regression — the scanner writes each substat's *value* and its
    *roll count*, and `_count_rolls` re-derives the count from the value.
    The two must agree, or the disc's remaining upgrade budget
    (`max_rolls - rolls_used`) is wrong.

    This is the guard for the coupling B5 exposed: making `_count_rolls`
    rarity-aware while the importer still scaled every rarity's value by
    the S-rank base turned two bugs that used to cancel into an
    overcount, silently zeroing upgrade potential for scanned A/B discs.
    """
    stat_keys = ("crit_", "atk_", "atk")
    draft = scanner_importer._zod_disc_to_draft(
        {
            "setKey": "MoonlightLullaby",
            "slotKey": "1",
            "level": level,
            "rarity": rarity,
            "mainStatKey": "hp",
            "substats": [
                {"key": key, "upgrades": n} for key, n in zip(stat_keys, upgrades, strict=True)
            ],
        },
        set_lookup={"moonlightlullaby": SimpleNamespace(id="set-1", name="Moonlight Lullaby")},
    )
    assert not isinstance(draft, tuple), draft

    disc = DiscCandidate(
        disc_id=f"{rarity}-scanned",
        slot=1,
        set_id=1,
        main_stat_type=draft.main_stat_type.value,
        main_stat_value=draft.main_stat_value,
        substats=[{"stat": s["stat"], "value": s["value"]} for s in draft.substats],
    )
    stored_rolls = sum(s["rolls"] for s in draft.substats)
    assert stored_rolls == sum(upgrades)
    assert _count_rolls(disc, rarity) == stored_rolls
