"""Potential tagging in the nanoka importer (#90, DESIGN_potential_toggle.md §4.2).

Two things are proven here, and the second is the reason this file exists.

1. The three-way classifier. `potential: []` -> None (present in both), `[0]` -> "base",
   `[<aid>00..05]` -> "unlocked". The predicate is "contains 0", never "is empty": a
   positive "keep only empty" reading deletes all 18 live Potential-only move names
   roster-wide, which is the mis-implementation #85 nearly shipped.

2. **The `hit_index` invariant.** `_import_attacks` numbers hits with a running counter
   over the surviving param stream. Emitting both variants in a single pass therefore
   numbers their *union*, which reproduces the exact artefact #85 was filed to remove:
   Soldier 0 - Anby stored as a 7-hit string that exists in neither kit, with
   1381004/005/006 at indices 4/5/6 instead of 3/4/5. Each variant must be numbered on
   its own pass, and shared rows must land on the same index under both.

The two moves used here are the only two in the roster whose base params carry *different
multipliers* rather than being absent, so they exercise the whole mechanism:
Jane "Basic Attack: Salchow Jump" (1261007 @ 30080 vs 1261030 @ 48210) and
Soldier 0 - Anby "Basic Attack: Penetrating Shock" (1381003 @ 8010 vs 1381022 @ 10010).
Payloads are the real nanoka shapes, trimmed to the fields the importer reads.
"""

from __future__ import annotations

import pytest

from app.data.importers.nanoka_importer import (
    _plan_move_hits,
    _potential_tag,
    _visible_in,
)
from app.models.enums import PotentialTag, PotentialVariant


def _for_variant(plans: list, variant: PotentialVariant) -> list:
    """The rows one kit actually sees, in hit order."""
    return sorted(
        (p for p in plans if _visible_in(p.potential, variant)),
        key=lambda p: p.hit_index,
    )


def _param(name: str, sid: str, dmg: int, potential: list[int] | None = None) -> dict:
    entry = {
        "name": name,
        "param": {sid: {"damage_percentage": dmg, "damage_percentage_growth": 1}},
    }
    if potential is not None:
        entry["potential"] = potential
    return entry


# Soldier 0 - Anby, "Basic Attack: Penetrating Shock". Six hits in either kit; the third
# is 1381003 (base) or 1381022 (Potential), and 004/005/006 follow it in both.
PENETRATING_SHOCK = {
    "name": "Basic Attack: Penetrating Shock",
    "param": [
        _param("1st-Hit DMG Multiplier", "1381001", 3270),
        _param("2nd-Hit DMG Multiplier", "1381002", 6220),
        _param("3rd-Hit DMG Multiplier", "1381003", 8010, potential=[0]),
        _param("3rd-Hit DMG Multiplier", "1381022", 10010, potential=[138100, 138105]),
        _param("4th-Hit DMG Multiplier", "1381004", 3990),
        _param("5th-Hit DMG Multiplier", "1381005", 15450),
        _param("6th-Hit DMG Multiplier", "1381006", 14850),
    ],
}

# Jane, "Basic Attack: Salchow Jump". Two hits in either kit.
SALCHOW_JUMP = {
    "name": "Basic Attack: Salchow Jump",
    "param": [
        _param("Consecutive Attack DMG Multiplier", "1261007", 30080, potential=[0]),
        _param(
            "Consecutive Attack DMG Multiplier", "1261030", 48210, potential=[126100, 126105]
        ),
        _param("Follow-Up DMG Multiplier", "1261008", 16130),
    ],
}


class TestClassifier:
    def test_empty_list_is_shared(self) -> None:
        assert _potential_tag({"potential": []}) is None

    def test_missing_key_is_shared(self) -> None:
        assert _potential_tag({}) is None

    def test_zero_list_is_base(self) -> None:
        assert _potential_tag({"potential": [0]}) is PotentialTag.BASE

    def test_node_id_list_is_unlocked(self) -> None:
        node_ids = [119100, 119101, 119102, 119103, 119104, 119105]
        assert _potential_tag({"potential": node_ids}) is PotentialTag.UNLOCKED

    def test_predicate_is_contains_zero_not_is_empty(self) -> None:
        """The #85 mis-implementation: 'keep only empty' deletes live Potential moves."""
        unlocked = {"potential": [126100, 126101, 126102, 126103, 126104, 126105]}
        assert _potential_tag(unlocked) is not PotentialTag.BASE
        assert _visible_in(_potential_tag(unlocked), PotentialVariant.UNLOCKED)


class TestVisibility:
    @pytest.mark.parametrize(
        ("tag", "variant", "expected"),
        [
            (None, PotentialVariant.LOCKED, True),
            (None, PotentialVariant.UNLOCKED, True),
            (None, PotentialVariant.BOTH, True),
            (PotentialTag.BASE, PotentialVariant.LOCKED, True),
            (PotentialTag.BASE, PotentialVariant.UNLOCKED, False),
            (PotentialTag.BASE, PotentialVariant.BOTH, True),
            (PotentialTag.UNLOCKED, PotentialVariant.LOCKED, False),
            (PotentialTag.UNLOCKED, PotentialVariant.UNLOCKED, True),
            (PotentialTag.UNLOCKED, PotentialVariant.BOTH, True),
        ],
    )
    def test_matrix(
        self, tag: PotentialTag | None, variant: PotentialVariant, expected: bool
    ) -> None:
        assert _visible_in(tag, variant) is expected


class TestForRank:
    def test_rank_zero_is_locked(self) -> None:
        assert PotentialVariant.for_rank(0) is PotentialVariant.LOCKED

    @pytest.mark.parametrize("rank", [1, 2, 3, 4, 5])
    def test_any_unlocked_rank_selects_the_potential_kit(self, rank: int) -> None:
        assert PotentialVariant.for_rank(rank) is PotentialVariant.UNLOCKED


class TestHitIndexInvariant:
    """DESIGN_potential_toggle.md §4.2 — each kit is numbered on its own pass.

    A single merged pass would number the *union* of both variants, which is the
    7-hit Penetrating Shock that exists in neither kit. These tests fail against that
    implementation, which is what makes them worth having.
    """

    @pytest.mark.parametrize(
        ("move", "expected_hits"),
        [(PENETRATING_SHOCK, 6), (SALCHOW_JUMP, 2)],
    )
    @pytest.mark.parametrize(
        "variant", [PotentialVariant.LOCKED, PotentialVariant.UNLOCKED]
    )
    def test_each_kit_is_contiguous_from_zero(
        self, move: dict, expected_hits: int, variant: PotentialVariant
    ) -> None:
        rows = _for_variant(_plan_move_hits(move["param"]), variant)
        assert [r.hit_index for r in rows] == list(range(expected_hits))

    def test_shared_rows_agree_across_variants(self) -> None:
        plans = _plan_move_hits(PENETRATING_SHOCK["param"])
        shared = {p.skill_id: p.hit_index for p in plans if p.potential is None}
        # 004/005/006 follow the variant-specific 3rd hit in BOTH kits, so they sit at
        # 3/4/5 either way. Under a merged pass they would be at 4/5/6.
        assert shared["1381004"] == 3
        assert shared["1381005"] == 4
        assert shared["1381006"] == 5

    def test_the_variant_specific_hit_occupies_the_same_slot_in_both_kits(self) -> None:
        plans = _plan_move_hits(PENETRATING_SHOCK["param"])
        by_id = {p.skill_id: p for p in plans}
        assert by_id["1381003"].potential is PotentialTag.BASE
        assert by_id["1381022"].potential is PotentialTag.UNLOCKED
        assert by_id["1381003"].hit_index == by_id["1381022"].hit_index == 2

    def test_no_phantom_row_survives_in_either_kit(self) -> None:
        """The filed #85 bug: 7 rows stored for a 6-hit move, 3 for a 2-hit move."""
        plans = _plan_move_hits(PENETRATING_SHOCK["param"])
        assert len(_for_variant(plans, PotentialVariant.LOCKED)) == 6
        assert len(_for_variant(plans, PotentialVariant.UNLOCKED)) == 6

        jane = _plan_move_hits(SALCHOW_JUMP["param"])
        assert len(_for_variant(jane, PotentialVariant.LOCKED)) == 2
        assert len(_for_variant(jane, PotentialVariant.UNLOCKED)) == 2

    def test_the_two_kits_carry_different_multipliers(self) -> None:
        """Locked is not a subset of unlocked — these rows differ in value, not presence."""
        plans = _plan_move_hits(SALCHOW_JUMP["param"])
        locked = _for_variant(plans, PotentialVariant.LOCKED)
        unlocked = _for_variant(plans, PotentialVariant.UNLOCKED)
        assert locked[0].values["damage_percentage"] == 30080
        assert unlocked[0].values["damage_percentage"] == 48210

    def test_an_untagged_move_is_entirely_shared(self) -> None:
        move = [
            _param("1st-Hit DMG Multiplier", "9001", 100),
            _param("2nd-Hit DMG Multiplier", "9002", 200),
        ]
        plans = _plan_move_hits(move)
        assert all(p.potential is None for p in plans)
        assert [p.hit_index for p in plans] == [0, 1]

    def test_daze_params_are_skipped(self) -> None:
        move = [
            _param("1st-Hit DMG Multiplier", "9001", 100),
            _param("1st-Hit Daze Multiplier", "9001", 100),
        ]
        assert len(_plan_move_hits(move)) == 1


class TestIncludesAcceptsRawStrings:
    """The column is String(16), so rows read from Postgres carry plain `str`.

    An identity (`is`) comparison passes every in-memory test — the importer builds
    real enum members — and then silently excludes every tagged row loaded from the
    DB, which 404s legitimate moves on the by-ID damage path. Same shape as
    `Attack.hit_mode`, which `_classify_move` coerces for exactly this reason.
    """

    @pytest.mark.parametrize(
        ("raw", "variant", "expected"),
        [
            ("base", PotentialVariant.LOCKED, True),
            ("base", PotentialVariant.UNLOCKED, False),
            ("unlocked", PotentialVariant.UNLOCKED, True),
            ("unlocked", PotentialVariant.LOCKED, False),
            ("base", PotentialVariant.BOTH, True),
            (None, PotentialVariant.LOCKED, True),
        ],
    )
    def test_raw_str_tags_behave_like_enum_members(
        self, raw: str | None, variant: PotentialVariant, expected: bool
    ) -> None:
        assert variant.includes(raw) is expected

    def test_enum_and_str_agree(self) -> None:
        for variant in PotentialVariant:
            for tag in PotentialTag:
                assert variant.includes(tag) is variant.includes(str(tag.value))
