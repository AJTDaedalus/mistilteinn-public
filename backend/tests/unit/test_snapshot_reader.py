"""F.3 — the single reader of the committed snapshot, especially where it refuses.

Every lookup here raises rather than defaulting, and the refusals are the point: a growth
curve that quietly returned 1.0 would turn a level-90 character into a level-1 one and leave
every number downstream looking plausible. So the failure paths get tests, not just the
happy ones.
"""

from __future__ import annotations

import pytest

from app.data import snapshot

# ---- Growth curves --------------------------------------------------------

def test_a_curve_returns_the_published_multiplier():
    at_ninety = snapshot.growth_curve("avatar", "GROW_CURVE_HP_S5", 90)

    assert at_ninety == pytest.approx(8.739, abs=1e-3)
    assert snapshot.growth_curve("avatar", "GROW_CURVE_HP_S5", 1) == pytest.approx(1.0)


def test_the_three_curve_tables_are_separate_namespaces():
    """`GROW_CURVE_HP` is a monster curve and `GROW_CURVE_HP_S5` an avatar one; asking the
    wrong table must fail rather than silently find a same-named curve."""
    assert snapshot.growth_curve("monster", "GROW_CURVE_HP", 1) > 0

    with pytest.raises(snapshot.SnapshotUnavailableError, match="not in the snapshot"):
        snapshot.growth_curve("avatar", "GROW_CURVE_HP", 1)


def test_an_unknown_curve_table_names_the_ones_that_exist():
    with pytest.raises(snapshot.SnapshotUnavailableError, match="no curve table"):
        snapshot.growth_curve("vehicle", "GROW_CURVE_HP", 1)


def test_a_level_outside_the_published_range_raises_rather_than_clamping():
    """Clamping would make a level-200 typo return a real-looking number."""
    with pytest.raises(snapshot.SnapshotUnavailableError, match="has no level 200"):
        snapshot.growth_curve("avatar", "GROW_CURVE_HP_S5", 200)


def test_a_non_multiplier_curve_refuses_to_be_used_as_one():
    """`GROW_CURVE_STRIKE` is ARITH_ADD (E.5). Applying it as a multiplier would be wrong in
    a way nothing downstream could catch."""
    with pytest.raises(snapshot.SnapshotUnavailableError, match="not a multiplier"):
        snapshot.growth_curve("monster", "GROW_CURVE_STRIKE", 1)


# ---- Artifact tables ------------------------------------------------------

def test_main_stat_values_are_indexed_by_the_artifacts_own_level():
    """+0 is the first published row; the off-by-one lives in the reader, once."""
    plus_zero = snapshot.artifact_main_stat_value(5, 0, "FIGHT_PROP_CRITICAL_HURT")
    plus_twenty = snapshot.artifact_main_stat_value(5, 20, "FIGHT_PROP_CRITICAL_HURT")

    assert plus_twenty == pytest.approx(0.622, abs=1e-3)
    assert plus_zero < plus_twenty


def test_an_unknown_rarity_or_level_or_prop_raises():
    with pytest.raises(snapshot.SnapshotUnavailableError, match="no main-stat values"):
        snapshot.artifact_main_stat_value(9, 20, "FIGHT_PROP_HP")
    # +21 used to be refused as "no main-stat row" — the table simply ran out. Since G.9
    # derived the per-rarity caps it is refused earlier and more accurately: a five-star
    # *caps* at +20, which is a statement about the artifact rather than about the table.
    # The row-missing branch survives for a snapshot whose value table is shorter than the
    # cap it publishes, which would be an inconsistent rebuild rather than a caller error.
    with pytest.raises(snapshot.SnapshotUnavailableError, match=r"caps at \+20"):
        snapshot.artifact_main_stat_value(5, 21, "FIGHT_PROP_HP")
    with pytest.raises(snapshot.SnapshotUnavailableError, match="not a main stat"):
        snapshot.artifact_main_stat_value(5, 20, "FIGHT_PROP_LUNAR_CHARGE")


def test_the_substat_depot_for_five_star_pieces_is_joinable_without_a_guess():
    """E.5's review round committed `depot_ranks` so this needs no `501 == 5-star` folklore."""
    depots = snapshot.substat_depots_for_rarity(5)

    assert 501 in depots
    rolls = snapshot.substat_rolls(501)
    assert rolls
    assert all(roll["prop"].startswith("FIGHT_PROP_") for roll in rolls)


def test_an_unknown_depot_raises():
    with pytest.raises(snapshot.SnapshotUnavailableError, match="no substat depot"):
        snapshot.substat_rolls(999999)


# ---- Pools and provenance -------------------------------------------------

def test_the_pools_are_the_five_slots():
    pools = snapshot.main_stat_pools()

    assert sorted(pools) == [
        "equip_bracer", "equip_dress", "equip_necklace", "equip_ring", "equip_shoes",
    ]


def test_the_reader_can_say_which_commit_it_is_reading():
    """Provenance has to survive the trip from the file to whatever reports a number."""
    assert snapshot.pinned_commit().startswith("5445617e")


def test_a_missing_snapshot_file_says_how_to_rebuild_it(monkeypatch, tmp_path):
    """"file not found" is a worse message than the command that fixes it."""
    monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
    snapshot._load.cache_clear()
    try:
        with pytest.raises(snapshot.SnapshotUnavailableError, match="build_snapshot"):
            snapshot.growth_curve("avatar", "GROW_CURVE_HP_S5", 1)
    finally:
        snapshot._load.cache_clear()


def test_what_the_reader_hands_out_cannot_corrupt_the_cache():
    """Everything here is behind an `@cache`; a caller that edited a returned structure
    would corrupt the table for every later reader in the process, until restart."""
    pools = snapshot.main_stat_pools()
    pools["equip_bracer"] = ("FIGHT_PROP_CRITICAL_HURT",)

    assert snapshot.main_stat_pools()["equip_bracer"] == ("FIGHT_PROP_HP",)

    rolls = snapshot.substat_rolls(501)
    rolls[0]["value"] = -1

    assert snapshot.substat_rolls(501)[0]["value"] > 0


def test_rarity_one_publishes_fewer_upgrade_levels_than_the_rest():
    # Published rows, not reachable levels: rarity 1 caps at +4 with 16 rows on file.
    assert snapshot.artifact_level_count(1) == 16
    assert snapshot.artifact_max_level(1) == 4
    assert snapshot.artifact_level_count(5) == 21


def test_asking_the_level_count_for_an_unpublished_rarity_raises():
    with pytest.raises(snapshot.SnapshotUnavailableError, match="no main-stat values"):
        snapshot.artifact_level_count(9)
