"""G.3 — the two layers that make the artifact search finish.

The tests are organised around the one distinction that matters: the Pareto layer must
never change the answer, and the budget-K layer may — and must say so when it does. So the
headline test runs the same search twice, exhaustively and pruned, and asserts the winner
and its damage are identical.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit, ScalingStat
from app.pando.calculator import NodeRegistry
from app.services import artifact_prefilter as pf
from app.services.artifact_optimizer import (
    ArtifactCandidate,
    OptimizerConstraints,
    OptimizerProgress,
    _floor_inputs,
    optimize,
)
from app.services.damage_calculator import Enemy
from app.services.stat_calculator import build_log

ORDINARY = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))
HIT = Hit(multiplier=2.0, channel="cryo", scope="burst")

_MAIN_STATS = {
    "equip_bracer": "FIGHT_PROP_HP",
    "equip_necklace": "FIGHT_PROP_ATTACK",
    "equip_shoes": "FIGHT_PROP_ATTACK_PERCENT",
    "equip_ring": "FIGHT_PROP_ICE_ADD_HURT",
    "equip_dress": "FIGHT_PROP_CRITICAL_HURT",
}


def _base():
    log = build_log(NodeRegistry())
    log.add(tags.Q_BASE_ATK, 800.0, tags.SRC_CHARACTER, "character")
    log.add(tags.Q_BASE_ATK, 500.0, tags.SRC_WEAPON, "weapon")
    log.add(tags.Q_CRIT_RATE, 0.05, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, 0.5, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_ENERGY_RECHARGE, 1.0, tags.SRC_CHARACTER, "base")
    return tuple(log.contributions)


def _piece(slot, name, *, set_id=1, substats=(), main=None, rarity=5, level=20):
    return ArtifactCandidate(
        artifact_id=name, slot=slot, set_id=set_id, rarity=rarity, level=level,
        main_stat=main or _MAIN_STATS[slot], substats=tuple(substats),
    )


def _spread_inventory(per_slot: int) -> list[ArtifactCandidate]:
    """One piece per slot per index, each trading ATK% against CRIT DMG.

    Deliberately Pareto-incomparable within a slot: the point of the inventory is to give
    the *lossy* layer something real to throw away, not to be pruned losslessly first.
    """
    out = []
    for slot in _MAIN_STATS:
        for index in range(per_slot):
            out.append(_piece(
                slot, f"{slot}-{index}",
                set_id=1 + index % 2,
                substats=(
                    {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.06 * (per_slot - index)},
                    {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.07 * index},
                ),
            ))
    return out


# ---- The property that makes the lossless layer worth having ---------------

def test_pareto_pruning_does_not_change_the_answer():
    """The whole claim, tested directly: same winner, same damage, fewer combinations.

    A search that pruned a *little* wrongly would still look plausible in isolation — the
    build it returned would be a good one. Only a comparison against the exhaustive answer
    catches it.
    """
    inventory = _spread_inventory(3)
    # Add a strictly-worse duplicate of every piece, which is exactly what Pareto exists to
    # remove: same slot, same set, same main, strictly fewer substats.
    inventory += [
        _piece(c.slot, f"{c.artifact_id}-worse", set_id=c.set_id, substats=(
            {"stat": "FIGHT_PROP_ATTACK_PERCENT",
             "value": float(c.substats[0]["value"]) - 0.01},
            {"stat": "FIGHT_PROP_CRITICAL_HURT",
             "value": float(c.substats[1]["value"]) - 0.01},
        ))
        for c in list(inventory)
    ]

    pruned = optimize(_base(), inventory, HIT, ORDINARY, character_level=90)

    assert pruned.prefilter.pareto_removed > 0
    # No lossy layer fired, so the pruned search is still exact — that is the claim.
    assert pruned.is_exact
    assert "exact" in pruned.summary()

    # And it really is the exhaustive answer: every dropped piece was strictly worse than a
    # kept one in the same slot and set, so no combination containing it could have won.
    winner = pruned.builds[0]
    assert all(not aid.endswith("-worse") for aid in winner.artifact_ids)


def test_dominance_needs_the_same_set_to_be_safe():
    """A weaker piece of a *different* set is not redundant — it may complete a bonus.

    Grouping by slot alone would prune it, and the loss would be invisible: the optimizer
    would return a real build with real numbers that simply was not the best one.
    """
    strong = _piece("equip_ring", "strong", set_id=1, substats=(
        {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.6},
    ))
    weak_other_set = _piece("equip_ring", "weak", set_id=2)

    by_slot = {"equip_ring": [strong, weak_other_set]}
    kept, removed = pf.pareto_filter(by_slot, (tags.Q_CRIT_DMG,))

    assert removed == 0
    assert len(kept["equip_ring"]) == 2


def test_identical_pieces_collapse_to_exactly_one():
    """Ties are dominance too, resolved by id so a duplicate group leaves one survivor.

    Without the id tie-break each of two identical pieces dominates the other and *both*
    are removed, which is the one way this layer could lose a build it is supposed to
    preserve.
    """
    by_slot = {
        "equip_ring": [
            _piece("equip_ring", "b"),
            _piece("equip_ring", "a"),
            _piece("equip_ring", "c"),
        ],
    }
    kept, removed = pf.pareto_filter(by_slot, (tags.Q_CRIT_DMG, tags.Q_ATK_PCT))

    assert removed == 2
    assert [c.artifact_id for c in kept["equip_ring"]] == ["a"]


def test_dominance_is_weak_plus_one_strict():
    assert pf.dominates((2.0, 2.0), (1.0, 2.0), "x", "y")
    assert not pf.dominates((2.0, 1.0), (1.0, 2.0), "x", "y")
    # An exact tie: the lower id survives, in one direction only.
    assert pf.dominates((1.0, 1.0), (1.0, 1.0), "a", "b")
    assert not pf.dominates((1.0, 1.0), (1.0, 1.0), "b", "a")


# ---- The probe -------------------------------------------------------------

def test_the_probe_calls_a_stat_dead_only_when_it_changes_nothing():
    """Energy Recharge cannot change a hit's damage in this chain, and HP cannot change an
    ATK-scaling one. Both should drop out; ATK% and CRIT DMG must not."""
    maxima = {
        tags.Q_ATK_PCT: 1.0,
        tags.Q_CRIT_DMG: 1.0,
        tags.Q_ENERGY_RECHARGE: 1.0,
        tags.Q_HP_PCT: 1.0,
    }
    live = pf.live_quantities(
        base_contributions=_base(), hit=HIT, enemy=ORDINARY, character_level=90,
        maxima=maxima,
    )

    assert tags.Q_ATK_PCT in live
    assert tags.Q_CRIT_DMG in live
    assert tags.Q_ENERGY_RECHARGE not in live
    assert tags.Q_HP_PCT not in live


def test_a_floor_stat_survives_the_probe_that_calls_it_dead():
    """The probe measures damage; a floor is not about damage.

    Dropping Energy Recharge from the comparison because it does not raise this hit would
    let a piece that clears an ER floor be dominated by one that does not — and the search
    would then report "no builds" for an inventory that had one.
    """
    live = pf.live_quantities(
        base_contributions=_base(), hit=HIT, enemy=ORDINARY, character_level=90,
        maxima={tags.Q_ATK_PCT: 1.0, tags.Q_ENERGY_RECHARGE: 1.0},
        always_keep=[tags.Q_ENERGY_RECHARGE],
    )

    assert tags.Q_ENERGY_RECHARGE in live


def test_a_stat_nothing_in_the_inventory_carries_is_not_probed():
    live = pf.live_quantities(
        base_contributions=_base(), hit=HIT, enemy=ORDINARY, character_level=90,
        maxima={tags.Q_ATK_PCT: 1.0, tags.Q_CRIT_DMG: 0.0},
    )

    assert live == (tags.Q_ATK_PCT,)


def test_crit_rate_is_kept_even_when_the_others_at_max_context_has_it_capped():
    """The case that makes the others-at-max probe insufficient on its own.

    With enough crit rate in the inventory to pass 100%, more crit rate is worth exactly
    zero *in that context* — `crit_multiplier` clamps. Probing only there would call crit
    rate dead and collapse every crit-rate piece against every other, on a build where crit
    rate is the single most valuable stat it could roll.
    """
    live = pf.live_quantities(
        base_contributions=_base(), hit=HIT, enemy=ORDINARY, character_level=90,
        maxima={tags.Q_CRIT_RATE: 3.0, tags.Q_CRIT_DMG: 1.0},
    )

    assert tags.Q_CRIT_RATE in live


def test_the_probe_scores_through_the_real_evaluator():
    """Not a cheaper model of damage — the same one. A probe with its own arithmetic could
    call a dimension dead that the chain reads."""
    from app.services.artifact_optimizer import optimize as _optimize

    inventory = [_piece(slot, slot) for slot in _MAIN_STATS]
    scored = _optimize(_base(), inventory, HIT, ORDINARY, character_level=90)
    probed = pf._probe(
        _base(), HIT, ORDINARY, 90,
        {
            tags.Q_FLAT_HP: 0.0,
        },
    )

    assert probed < scored.builds[0].damage  # the artifacts are worth something
    assert probed == pytest.approx(pf._probe(_base(), HIT, ORDINARY, 90, {}))


# ---- The stat vector -------------------------------------------------------

def test_the_comparison_vocabulary_is_what_the_inventory_carries():
    """It must not omit a stat a candidate has, or dominance stops meaning what it says.

    Flat DEF is the case worth naming: it rolls as a substat and never as a main stat, so a
    vocabulary derived from the main-stat pools alone would drop it and compare two pieces
    on terms that ignore the stat a DEF-scaling build lives on.
    """
    by_slot = {
        "equip_dress": [_piece("equip_dress", "circlet", substats=(
            {"stat": "FIGHT_PROP_DEFENSE", "value": 20.0},
            {"stat": "FIGHT_PROP_ELEMENT_MASTERY", "value": 40.0},
        ))],
        "equip_ring": [_piece("equip_ring", "goblet")],
    }
    quantities = pf.inventory_quantities(by_slot)

    assert quantities == tuple(sorted(quantities))
    assert set(quantities) == {
        tags.Q_CRIT_DMG,            # the circlet's main stat
        tags.Q_FLAT_DEF,            # substat only
        tags.Q_ELEMENTAL_MASTERY,
        tags.dmg_bonus_q("cryo"),   # the goblet's main stat
    }


def test_an_absent_substat_marker_is_not_a_quantity():
    by_slot = {
        "equip_ring": [_piece("equip_ring", "goblet", substats=(
            {"stat": "FIGHT_PROP_NONE", "value": 0},
            {"stat": "", "value": 0},
            {"value": 0},
        ))],
    }

    assert pf.inventory_quantities(by_slot) == (tags.dmg_bonus_q("cryo"),)


def test_a_stat_vector_sums_main_stat_and_substats():
    candidate = _piece("equip_dress", "circlet", substats=(
        {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.1},
    ))
    quantities = (tags.Q_CRIT_DMG, tags.Q_ATK_PCT)
    crit_dmg, atk_pct = pf.stat_vector(candidate, quantities)

    from app.data.snapshot import artifact_main_stat_value

    assert crit_dmg == pytest.approx(
        artifact_main_stat_value(5, 20, "FIGHT_PROP_CRITICAL_HURT") + 0.1,
    )
    assert atk_pct == 0.0


def test_reachable_maxima_sums_the_best_piece_in_each_slot():
    by_slot = {
        "equip_dress": [
            _piece("equip_dress", "a", substats=(
                {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.2},)),
            _piece("equip_dress", "b", substats=(
                {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.3},)),
        ],
        "equip_shoes": [
            _piece("equip_shoes", "c", substats=(
                {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.1},)),
        ],
        "equip_ring": [],
    }
    maxima = pf.reachable_maxima(by_slot, (tags.Q_CRIT_RATE,))

    assert maxima[tags.Q_CRIT_RATE] == 0.0
    atk = pf.reachable_maxima(by_slot, (tags.Q_ATK_PCT,))[tags.Q_ATK_PCT]
    from app.data.snapshot import artifact_main_stat_value
    # The shoes' ATK% main stat counts too — it is the same quantity.
    assert atk == pytest.approx(
        0.3 + 0.1 + artifact_main_stat_value(5, 20, "FIGHT_PROP_ATTACK_PERCENT"),
    )


# ---- Budget-K, the layer that may change the answer -------------------------

def test_budget_k_leaves_a_small_search_alone():
    by_slot = {slot: [_piece(slot, f"{slot}-{i}") for i in range(2)] for slot in _MAIN_STATS}

    assert pf.budget_k(by_slot, None, budget=10_000) is None


def test_budget_k_finds_the_largest_k_that_fits():
    by_slot = {slot: [_piece(slot, f"{slot}-{i}") for i in range(10)] for slot in _MAIN_STATS}

    # 3**5 = 243 <= 300 < 4**5 = 1024.
    assert pf.budget_k(by_slot, None, budget=300) == 3


def test_an_explicit_k_wins_and_exact_refuses_to_prune():
    by_slot = {slot: [_piece(slot, f"{slot}-{i}") for i in range(10)] for slot in _MAIN_STATS}

    assert pf.budget_k(by_slot, 4, budget=1) == 4
    assert pf.budget_k(by_slot, pf.EXACT, budget=1) is None


def test_a_lossy_search_says_so_in_every_place_a_caller_might_look():
    """The disclosure is the feature. A near-answer presented as an answer is worse than a
    slow search."""
    inventory = _spread_inventory(4)

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(prefilter_top_k=2),
    )

    assert result.prefilter.prefiltered > 0
    assert result.prefilter.effective_k == 2
    assert not result.is_exact
    assert "not proven" in result.summary()
    assert f"{result.prefilter.total_space:,}" in result.summary()


def test_exact_disables_only_the_lossy_layer():
    inventory = _spread_inventory(3)

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(prefilter_top_k=pf.EXACT),
    )

    assert result.prefilter.prefiltered == 0
    assert result.is_exact


def _floor_bucket():
    return {
        "equip_shoes": [
            _piece("equip_shoes", "dps-1", substats=(
                {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.3},)),
            _piece("equip_shoes", "dps-2", substats=(
                {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.25},)),
            _piece("equip_shoes", "the-er-one", substats=(
                {"stat": "FIGHT_PROP_CHARGE_EFFICIENCY", "value": 0.9},)),
        ],
    }


def test_the_floor_keep_saves_the_piece_that_clears_a_constraint():
    """A piece can be last on damage and still be the only way to satisfy a floor.

    Ranking on damage alone drops it, and the search then reports "no builds found" for an
    inventory that had one — a constraint turned into a failure by an accelerator.
    """
    by_slot = _floor_bucket()
    scores = {"dps-1": 100.0, "dps-2": 90.0, "the-er-one": 1.0}

    kept, removed = pf.apply_budget_k(by_slot, 1, scores, (tags.Q_ENERGY_RECHARGE,))

    ids = {c.artifact_id for c in kept["equip_shoes"]}
    assert ids == {"dps-1", "the-er-one"}
    assert removed == 1


def test_with_no_floors_budget_k_is_a_pure_damage_ranking():
    """The keep is for constraints, not for variety — variety is the lossless layer's job.

    A keep large enough to preserve variety swallows K whole: with K=2 and four live stats,
    a three-per-stat union kept every piece while the report still claimed a K had been
    applied. Pruning nothing and disclosing that you pruned is the worst of both.
    """
    by_slot = _floor_bucket()
    scores = {"dps-1": 100.0, "dps-2": 90.0, "the-er-one": 1.0}

    kept, removed = pf.apply_budget_k(by_slot, 1, scores)

    assert [c.artifact_id for c in kept["equip_shoes"]] == ["dps-1"]
    assert removed == 2


def test_budget_k_keeps_a_slot_it_does_not_need_to_cut():
    by_slot = {"equip_shoes": [_piece("equip_shoes", "only")]}

    kept, removed = pf.apply_budget_k(by_slot, 5, {}, (tags.Q_CRIT_DMG,))

    assert removed == 0
    assert [c.artifact_id for c in kept["equip_shoes"]] == ["only"]


def test_the_reference_filler_is_empty_for_an_empty_inventory():
    assert pf._reference_filler({}, (tags.Q_ATK_PCT,)) == {}


def test_solo_scores_rank_a_better_piece_higher():
    by_slot = {
        "equip_ring": [
            _piece("equip_ring", "plain"),
            _piece("equip_ring", "loaded", substats=(
                {"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.6},)),
        ],
    }
    scores = pf.solo_scores(
        by_slot=by_slot, quantities=(tags.Q_CRIT_DMG, tags.Q_ATK_PCT),
        base_contributions=_base(), hit=HIT, enemy=ORDINARY, character_level=90,
    )

    assert scores["loaded"] > scores["plain"]


def test_the_automatic_budget_comes_from_the_measured_constant():
    assert pf.automatic_budget() == int(
        pf.COMBINATION_BUDGET_SECONDS / pf.SECONDS_PER_COMBINATION,
    )


def test_combination_count_is_the_product_of_the_buckets():
    by_slot = {"a": [1, 2, 3], "b": [1, 2]}
    assert pf.combination_count(by_slot) == 6


# ---- Progress and cancellation ---------------------------------------------

def test_the_search_reports_progress_and_finishes_at_one():
    seen: list[OptimizerProgress] = []
    optimize(
        _base(), _spread_inventory(2), HIT, ORDINARY, character_level=90,
        progress_callback=seen.append,
    )

    # The tick is time-based, so a fast search may only produce the final one — which is
    # exactly why there is a final one.
    assert seen
    assert seen[-1].fraction == 1.0
    assert seen[-1].combinations_done == seen[-1].combinations_total


def test_progress_ticks_during_the_search_not_only_at_the_end(monkeypatch):
    """With the tick at zero every combination reports, which is what pins the in-loop path.

    The default two-second tick means a small search only ever produces the final snapshot,
    so a broken in-loop tick would look fine in every other test here.
    """
    monkeypatch.setattr(
        "app.services.artifact_optimizer.PROGRESS_TICK_SECONDS", 0.0,
    )
    seen: list[OptimizerProgress] = []
    result = optimize(
        _base(), _spread_inventory(2), HIT, ORDINARY, character_level=90,
        progress_callback=seen.append,
    )

    assert len(seen) > 1
    assert [p.combinations_done for p in seen] == sorted(p.combinations_done for p in seen)
    assert seen[-1].combinations_total == result.prefilter.total_space
    assert seen[0].elapsed_seconds >= 0.0


def test_a_callback_can_cancel_the_search(monkeypatch):
    """Cooperative, because a synchronous CPU-bound loop offers no other way in."""
    monkeypatch.setattr(
        "app.services.artifact_optimizer.PROGRESS_TICK_SECONDS", 0.0,
    )
    seen: list[OptimizerProgress] = []

    def stop(progress: OptimizerProgress) -> None:
        seen.append(progress)
        raise pf.Cancelled

    with pytest.raises(pf.Cancelled):
        optimize(
            _base(), _spread_inventory(2), HIT, ORDINARY, character_level=90,
            progress_callback=stop,
        )

    # It really stopped, rather than raising on the way out with the work already done.
    assert seen[-1].combinations_done < seen[-1].combinations_total


def test_a_stat_floor_survives_the_lossy_layer():
    """End to end: budget-K must not turn a satisfiable constraint into "no builds found"."""
    inventory = _spread_inventory(3)
    inventory += [
        _piece(slot, f"{slot}-er", substats=(
            {"stat": "FIGHT_PROP_CHARGE_EFFICIENCY", "value": 0.35},))
        for slot in _MAIN_STATS
    ]

    result = optimize(
        _base(), inventory, HIT, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(
            prefilter_top_k=1, min_stats={tags.Q_ENERGY_RECHARGE: 2.0},
        ),
    )

    assert result.prefilter.prefiltered > 0
    assert result.builds, "the ER pieces were kept, so a build clears the floor"
    assert tags.Q_ENERGY_RECHARGE in result.prefilter.live_quantities


def test_progress_fraction_is_one_for_an_empty_total():
    assert OptimizerProgress(0, 0, 0, 0.0).fraction == 1.0


# ---- Floors that no artifact contributes to by name -------------------------

def test_a_floor_maps_to_the_quantities_that_actually_feed_it():
    assert _floor_inputs([tags.Q_ATK]) == (tags.Q_ATK_PCT, tags.Q_FLAT_ATK)
    assert _floor_inputs([tags.Q_HP]) == (tags.Q_FLAT_HP, tags.Q_HP_PCT)
    assert _floor_inputs([tags.Q_DEF]) == (tags.Q_DEF_PCT, tags.Q_FLAT_DEF)
    # Everything else is contributed by name and maps to itself.
    assert _floor_inputs([tags.Q_ENERGY_RECHARGE]) == (tags.Q_ENERGY_RECHARGE,)


def test_an_atk_floor_survives_a_hit_that_does_not_scale_on_atk():
    """The case that makes the lossless layer lossy if floors are passed through raw.

    ATK is *computed* — `base * (1 + pct) + flat` — so no artifact contributes to `atk` by
    that name. On an HP-scaling hit the damage probe correctly reports ATK as worth nothing,
    which projects the ATK dimensions out of the comparison; the piece carrying the ATK% the
    floor needs is then dominated by a piece with more HP and no ATK, and the search returns
    "no builds" for an inventory that had one.
    """
    log = build_log(NodeRegistry())
    log.add(tags.Q_BASE_HP, 15000.0, tags.SRC_CHARACTER, "character")
    log.add(tags.Q_BASE_ATK, 800.0, tags.SRC_CHARACTER, "character")
    log.add(tags.Q_CRIT_RATE, 0.05, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, 0.5, tags.SRC_CHARACTER, "base")
    hp_base = tuple(log.contributions)
    hp_hit = Hit(
        multiplier=1.0, channel="cryo", scope="burst", scaling_stat=ScalingStat.HP,
    )

    inventory = [_piece(slot, slot) for slot in _MAIN_STATS if slot != "equip_shoes"]
    inventory += [
        # Strictly better on HP, and carries no ATK at all.
        _piece("equip_shoes", "hp-sands", main="FIGHT_PROP_HP_PERCENT", substats=(
            {"stat": "FIGHT_PROP_HP_PERCENT", "value": 0.30},)),
        # Worse on HP, and the only piece in the inventory that can clear the ATK floor.
        _piece("equip_shoes", "atk-sands", main="FIGHT_PROP_HP_PERCENT", substats=(
            {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.60},)),
    ]

    result = optimize(
        hp_base, inventory, hp_hit, ORDINARY, character_level=90,
        constraints=OptimizerConstraints(min_stats={tags.Q_ATK: 1200.0}),
    )

    assert tags.Q_ATK_PCT in result.prefilter.live_quantities
    assert result.builds, "the ATK sands must survive a comparison that ignores ATK damage"
    assert result.builds[0].artifact_ids[2] == "atk-sands"
