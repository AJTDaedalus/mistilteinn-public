"""G.1/G.2 — the artifact search.

The property that matters most here is not "it finds a good build" but **"it agrees with the
calculator"**. An optimizer with its own scoring shortcut recommends builds its own damage
figure disagrees with, and nobody notices until a user does the sum by hand. So the first
test asserts exactly that, and the module has no damage math of its own for it to drift from.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit
from app.pando.calculator import NodeRegistry
from app.services.artifact_optimizer import (
    ArtifactCandidate,
    OptimizerConstraints,
    OptimizerInputError,
    SetBonus,
    optimize,
    slot_main_stat_pool,
)
from app.services.damage_calculator import BuildEvaluator, Enemy
from app.services.stat_calculator import add_artifact, build_log

ORDINARY = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))
HIT = Hit(multiplier=1.0, channel="cryo", scope="burst")

#: A minimal character-and-weapon half, as `stat_calculator` would have produced it.
def _base():
    log = build_log(NodeRegistry())
    log.add(tags.Q_BASE_ATK, 800.0, tags.SRC_CHARACTER, "character")
    log.add(tags.Q_BASE_ATK, 500.0, tags.SRC_WEAPON, "weapon")
    log.add(tags.Q_CRIT_RATE, 0.05, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, 0.5, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_ENERGY_RECHARGE, 1.0, tags.SRC_CHARACTER, "base")
    return tuple(log.contributions)


def _piece(slot: str, name: str, main: str, set_id: int = 1, **kwargs) -> ArtifactCandidate:
    return ArtifactCandidate(
        artifact_id=name, slot=slot, set_id=set_id, rarity=5, level=20, main_stat=main,
        substats=tuple(kwargs.pop("substats", ())),
        **kwargs,
    )


def _one_of_each(**overrides: ArtifactCandidate) -> list[ArtifactCandidate]:
    """One legal artifact per slot, so a test can vary exactly one of them."""
    pieces = {
        "equip_bracer": _piece("equip_bracer", "flower", "FIGHT_PROP_HP"),
        "equip_necklace": _piece("equip_necklace", "plume", "FIGHT_PROP_ATTACK"),
        "equip_shoes": _piece("equip_shoes", "sands", "FIGHT_PROP_ATTACK_PERCENT"),
        "equip_ring": _piece("equip_ring", "goblet", "FIGHT_PROP_ICE_ADD_HURT"),
        "equip_dress": _piece("equip_dress", "circlet", "FIGHT_PROP_CRITICAL_HURT"),
    }
    pieces.update(overrides)
    return list(pieces.values())


# ---- The property the module exists for -----------------------------------

def test_the_optimizers_score_is_the_calculators_answer():
    """No second scoring path. If these ever disagree, the tool is lying to someone."""
    inventory = _one_of_each()
    result = optimize(_base(), inventory, HIT, ORDINARY, character_level=90)
    (winner,) = result.builds

    # Rebuild the same combination by hand, through the ordinary calculator path.
    log = build_log(NodeRegistry())
    for contribution in _base():
        log.add(
            contribution.quantity, contribution.value, contribution.source,
            contribution.note, tag=contribution.tag,
        )
    for candidate in inventory:
        add_artifact(log, candidate.as_stats())
    expected = BuildEvaluator(
        registry=log.registry, enemy=ORDINARY, character_level=90,
    ).evaluate(HIT).expected

    assert winner.damage == pytest.approx(expected)


def test_the_winning_build_can_account_for_itself():
    """A6 reaches the optimizer: a recommendation nobody can interrogate is one nobody
    should act on."""
    result = optimize(_base(), _one_of_each(), HIT, ORDINARY, character_level=90)

    sources = {c.source for c in result.builds[0].contributions}
    assert tags.SRC_ARTIFACT in sources
    assert tags.SRC_CHARACTER in sources


# ---- The search -----------------------------------------------------------

def test_it_picks_the_better_of_two_goblets():
    inventory = _one_of_each()
    inventory.append(_piece("equip_ring", "better-goblet", "FIGHT_PROP_ICE_ADD_HURT", set_id=2))
    # Same main stat, but one carries crit damage substats.
    inventory[-1] = ArtifactCandidate(
        artifact_id="better-goblet", slot="equip_ring", set_id=2, rarity=5, level=20,
        main_stat="FIGHT_PROP_ICE_ADD_HURT",
        substats=({"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.6},),
    )

    result = optimize(_base(), inventory, HIT, ORDINARY, character_level=90)

    assert result.builds[0].artifact_ids[3] == "better-goblet"
    assert result.evaluated == 2


def test_top_n_bounds_what_is_kept_not_what_is_scored():
    inventory = _one_of_each()
    for index in range(5):
        inventory.append(ArtifactCandidate(
            artifact_id=f"circlet-{index}", slot="equip_dress", set_id=1, rarity=5,
            level=20, main_stat="FIGHT_PROP_CRITICAL_HURT",
            substats=({"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.05 * index},),
        ))

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(top_n=3),
    )

    assert result.evaluated == 6
    assert len(result.builds) == 3
    # Descending, so the caller can read the first as the answer.
    assert [b.damage for b in result.builds] == sorted(
        [b.damage for b in result.builds], reverse=True,
    )


def test_a_locked_slot_pins_that_piece():
    inventory = _one_of_each()
    inventory.append(ArtifactCandidate(
        artifact_id="other-flower", slot="equip_bracer", set_id=2, rarity=5, level=20,
        main_stat="FIGHT_PROP_HP",
    ))

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(locked_slots={"equip_bracer": "other-flower"}),
    )

    assert result.evaluated == 1
    assert result.builds[0].artifact_ids[0] == "other-flower"


def test_an_empty_slot_says_so_instead_of_returning_nothing():
    """The Cartesian product of an empty bucket is empty, so the search would otherwise
    return no builds and no reason. A user missing a goblet should be told that."""
    inventory = [c for c in _one_of_each() if c.slot != "equip_ring"]

    with pytest.raises(OptimizerInputError, match="no candidates for"):
        optimize(_base(), inventory, HIT, ORDINARY, character_level=90)


def test_locking_a_slot_to_a_piece_that_is_not_there_is_an_error():
    with pytest.raises(OptimizerInputError, match="not in the candidates"):
        optimize(
            _base(), _one_of_each(), HIT, ORDINARY, character_level=90,
            constraints=OptimizerConstraints(locked_slots={"equip_bracer": "ghost"}),
        )


def test_an_unknown_slot_is_rejected():
    bad = ArtifactCandidate(
        artifact_id="cape", slot="equip_cape", set_id=1, rarity=5, level=20,
        main_stat="FIGHT_PROP_HP",
    )

    with pytest.raises(OptimizerInputError, match="the five are"):
        optimize(_base(), [*_one_of_each(), bad], HIT, ORDINARY, character_level=90)


# ---- Constraints ----------------------------------------------------------

def test_a_required_set_rejects_combinations_before_scoring():
    inventory = _one_of_each()
    inventory.append(ArtifactCandidate(
        artifact_id="other-set-goblet", slot="equip_ring", set_id=99, rarity=5, level=20,
        main_stat="FIGHT_PROP_ICE_ADD_HURT",
    ))

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(required_sets={1: 5}),
    )

    assert result.evaluated == 1
    assert result.rejected_by_sets == 1


def test_a_stat_floor_rejects_builds_that_miss_it():
    """An energy-recharge floor is the common case: the highest-damage build is useless if
    the burst never comes up."""
    inventory = _one_of_each()

    without = optimize(_base(), inventory, HIT, ORDINARY, character_level=90)
    with_floor = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(min_stats={tags.Q_ENERGY_RECHARGE: 2.0}),
    )

    assert without.builds
    assert with_floor.builds == ()
    assert with_floor.rejected_by_stats == 1


def test_a_floor_on_an_unsupported_stat_says_which_ones_work():
    with pytest.raises(ValueError, match="not stats this optimizer"):
        optimize(
            _base(), _one_of_each(), HIT, ORDINARY, character_level=90,
            constraints=OptimizerConstraints(min_stats={"vitality": 1.0}),
        )


# ---- Set bonuses ----------------------------------------------------------

def test_a_two_piece_bonus_applies_at_two_pieces_and_not_at_one():
    bonus = SetBonus(
        set_id=1, pieces_required=2,
        add_props=({"prop_type": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.18},),
    )
    two_pieces = _one_of_each()
    one_piece = _one_of_each(
        equip_necklace=_piece("equip_necklace", "plume", "FIGHT_PROP_ATTACK", set_id=2),
        equip_shoes=_piece("equip_shoes", "sands", "FIGHT_PROP_ATTACK_PERCENT", set_id=2),
        equip_ring=_piece("equip_ring", "goblet", "FIGHT_PROP_ICE_ADD_HURT", set_id=2),
        equip_dress=_piece("equip_dress", "circlet", "FIGHT_PROP_CRITICAL_HURT", set_id=2),
    )

    with_bonus = optimize(
        _base(), two_pieces, HIT, ORDINARY, character_level=90, set_bonuses=[bonus],
    )
    without = optimize(
        _base(), one_piece, HIT, ORDINARY, character_level=90, set_bonuses=[bonus],
    )

    assert with_bonus.builds[0].damage > without.builds[0].damage


def test_a_one_piece_set_bonus_applies_at_one_piece():
    """The five "Prayers" circlets are genuine one-piece sets (C.5). A model hardcoding
    2pc/4pc makes them invisible to the optimizer."""
    prayers = SetBonus(
        set_id=15009, pieces_required=1,
        add_props=({"prop_type": "FIGHT_PROP_CRITICAL_HURT", "value": 0.5},),
    )
    inventory = _one_of_each(
        equip_dress=_piece(
            "equip_dress", "prayers", "FIGHT_PROP_CRITICAL_HURT", set_id=15009,
        ),
    )

    with_bonus = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90, set_bonuses=[prayers],
    )
    without = optimize(_base(), inventory, HIT, ORDINARY, character_level=90)

    assert with_bonus.builds[0].damage > without.builds[0].damage


def test_a_conditional_bonus_is_skipped_and_counted():
    """Its numbers live in `param_list` and its effect is kit text — Chunk H's. Guessing at
    it here would score builds on an effect this repo cannot model, silently."""
    conditional = SetBonus(
        set_id=1, pieces_required=4,
        add_props=({"prop_type": "FIGHT_PROP_NONE", "value": 0},),
    )

    result = optimize(
        _base(), _one_of_each(), HIT, ORDINARY, character_level=90,
        set_bonuses=[conditional],
    )

    assert result.skipped_conditional_bonuses == 1
    assert result.builds


def test_a_bonus_for_a_set_the_build_does_not_wear_does_nothing():
    bonus = SetBonus(
        set_id=99, pieces_required=2,
        add_props=({"prop_type": "FIGHT_PROP_ATTACK_PERCENT", "value": 5.0},),
    )

    with_bonus = optimize(
        _base(), _one_of_each(), HIT, ORDINARY, character_level=90, set_bonuses=[bonus],
    )
    without = optimize(_base(), _one_of_each(), HIT, ORDINARY, character_level=90)

    assert with_bonus.builds[0].damage == pytest.approx(without.builds[0].damage)


# ---- G.2: the pools are data ----------------------------------------------

def test_the_slot_pools_come_from_the_committed_snapshot():
    assert slot_main_stat_pool("equip_bracer") == ("FIGHT_PROP_HP",)
    assert slot_main_stat_pool("equip_necklace") == ("FIGHT_PROP_ATTACK",)
    assert len(slot_main_stat_pool("equip_ring")) == 12
    assert "FIGHT_PROP_CRITICAL" in slot_main_stat_pool("equip_dress")


def test_an_unknown_slot_has_no_pool():
    with pytest.raises(OptimizerInputError, match="not an artifact slot"):
        slot_main_stat_pool("equip_cape")


def test_locking_a_slot_that_does_not_exist_is_an_error():
    with pytest.raises(OptimizerInputError, match="cannot lock unknown slot"):
        optimize(
            _base(), _one_of_each(), HIT, ORDINARY, character_level=90,
            constraints=OptimizerConstraints(locked_slots={"equip_cape": "anything"}),
        )


def test_a_partly_conditional_bonus_applies_only_its_static_props():
    """Real affixes carry three prop slots and pad the unused ones with `FIGHT_PROP_NONE`
    (C.5), so "has a `NONE` prop" cannot mean "skip the whole tier"."""
    mixed = SetBonus(
        set_id=1, pieces_required=2,
        add_props=(
            {"prop_type": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.18},
            {"prop_type": "FIGHT_PROP_NONE", "value": 0},
            {"prop_type": "FIGHT_PROP_NONE", "value": 0},
        ),
    )

    with_bonus = optimize(
        _base(), _one_of_each(), HIT, ORDINARY, character_level=90, set_bonuses=[mixed],
    )
    without = optimize(_base(), _one_of_each(), HIT, ORDINARY, character_level=90)

    assert with_bonus.skipped_conditional_bonuses == 0
    assert with_bonus.builds[0].damage > without.builds[0].damage


# ---- The PR #9 review's findings, each pinned -----------------------------

def test_asking_for_zero_builds_is_rejected_rather_than_crashing():
    """`0 < 0` skipped the heap push and the elif then indexed an empty list. G.6 exposes
    `top_n` as a request parameter, where `?topN=0` would have been a 500."""
    with pytest.raises(OptimizerInputError, match="top_n must be at least 1"):
        OptimizerConstraints(top_n=0)


def test_the_skipped_bonus_count_counts_tiers_not_combinations():
    """It used to accumulate per combination, so one conditional 4pc over a real inventory
    reported millions — a number that stops answering the question it exists for.

    The single-combination test above cannot see this; this one has three.
    """
    conditional = SetBonus(
        set_id=1, pieces_required=4,
        add_props=({"prop_type": "FIGHT_PROP_NONE", "value": 0},),
    )
    inventory = _one_of_each()
    for index in range(2):
        inventory.append(ArtifactCandidate(
            artifact_id=f"extra-circlet-{index}", slot="equip_dress", set_id=1, rarity=5,
            level=20, main_stat="FIGHT_PROP_CRITICAL_HURT",
        ))

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90, set_bonuses=[conditional],
    )

    assert result.evaluated == 3
    assert result.skipped_conditional_bonuses == 1


def test_a_blank_prop_slot_does_not_abort_the_search():
    """"Absent" has more than one spelling (C.2). Testing only for `FIGHT_PROP_NONE` meant
    an affix padded with an empty string raised and killed the whole `optimize()` call."""
    padded_with_blanks = SetBonus(
        set_id=1, pieces_required=2,
        add_props=(
            {"prop_type": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.18},
            {"prop_type": "", "value": 0},
        ),
    )

    result = optimize(
        _base(), _one_of_each(), HIT, ORDINARY, character_level=90,
        set_bonuses=[padded_with_blanks],
    )

    assert result.builds
    assert result.skipped_conditional_bonuses == 0


def test_a_wholly_blank_tier_counts_as_conditional():
    blank = SetBonus(
        set_id=1, pieces_required=2, add_props=({"prop_type": "", "value": 0},),
    )

    result = optimize(
        _base(), _one_of_each(), HIT, ORDINARY, character_level=90, set_bonuses=[blank],
    )

    assert result.skipped_conditional_bonuses == 1


def test_an_illegal_candidate_is_named_before_the_search_starts():
    """It used to raise from inside the product loop, after arbitrary work, without saying
    which artifact was at fault."""
    inventory = _one_of_each()
    inventory.append(ArtifactCandidate(
        artifact_id="impossible-flower", slot="equip_bracer", set_id=1, rarity=5, level=20,
        main_stat="FIGHT_PROP_CRITICAL_HURT",
    ))

    with pytest.raises(OptimizerInputError, match="impossible-flower cannot be searched"):
        optimize(_base(), inventory, HIT, ORDINARY, character_level=90)


def test_a_candidate_level_beyond_its_rarity_is_named_too():
    inventory = _one_of_each()
    inventory.append(ArtifactCandidate(
        artifact_id="overlevelled", slot="equip_bracer", set_id=1, rarity=1, level=20,
        main_stat="FIGHT_PROP_HP",
    ))

    with pytest.raises(OptimizerInputError, match="overlevelled cannot be searched"):
        optimize(_base(), inventory, HIT, ORDINARY, character_level=90)


def test_a_misspelled_stat_floor_is_reported_even_when_nothing_survives_the_set_filter():
    """The lookup used to sit inside the loop, so a typo went unreported whenever the set
    filter rejected every combination — leaving "why did I get no builds" unanswered."""
    with pytest.raises(ValueError, match="not stats this optimizer"):
        optimize(
            _base(), _one_of_each(), HIT, ORDINARY, character_level=90,
            constraints=OptimizerConstraints(
                required_sets={999: 1}, min_stats={"vitality": 1.0},
            ),
        )


def test_a_tier_with_no_props_at_all_is_conditional():
    """The importer stores `add_props: []` when the payload has none; there is nothing to
    apply, so the tier is reported as skipped rather than treated as a silent zero."""
    empty = SetBonus(set_id=1, pieces_required=2, add_props=())

    result = optimize(
        _base(), _one_of_each(), HIT, ORDINARY, character_level=90, set_bonuses=[empty],
    )

    assert result.skipped_conditional_bonuses == 1
    assert result.builds
