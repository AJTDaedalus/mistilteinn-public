"""F.1/F.2 — the Genshin tag vocabulary and the stat graph.

Pure DAG tests: register contributions, evaluate a node, check the arithmetic. No database,
no ORM, no importer. What they pin is the *shape* of the stat layer, which DESIGN §1 A6
makes a first-class concern — a formula that quietly grows a second stage, or a channel that
gets summed into the wrong pool, is exactly the kind of drift nobody notices from a damage
figure alone.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.genshin import stats, tags
from app.formula.genshin.explain import ContributionLog
from app.formula.tags import Tag
from app.pando.calculator import Calculator, NodeRegistry


def _calc(**contributions: float) -> Calculator:
    """A calculator with one constant registered per quantity."""
    registry = NodeRegistry()
    for quantity, value in contributions.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return Calculator(registry=registry)


def _value(node, **contributions: float) -> float:
    return _calc(**contributions).compute(node)


# ---- The stat formula -----------------------------------------------------

def test_atk_is_base_times_one_plus_percent_plus_flat():
    """gcsim stats.go:45 — `s[BaseATK]*(1+s[ATKP]) + s[ATK]`."""
    result = _value(stats.ATK_NODE, base_atk=800.0, atk_pct=0.5, flat_atk=311.0)

    assert result == pytest.approx(800.0 * 1.5 + 311.0)


def test_hp_and_def_share_that_shape():
    assert _value(stats.HP_NODE, base_hp=10000.0, hp_pct=0.2, flat_hp=4780.0) == pytest.approx(
        10000.0 * 1.2 + 4780.0,
    )
    assert _value(stats.DEF_NODE, base_def=600.0, def_pct=0.6, flat_def=100.0) == pytest.approx(
        600.0 * 1.6 + 100.0,
    )


def test_the_percentage_applies_to_the_summed_base_not_to_each_source():
    """`(character + weapon) * (1 + atk%)`, not `character * (1 + atk%) + weapon`.

    Both base ATK sources register into one pool, so the ordering is a property of the graph
    rather than of whoever registers first. Getting this backwards is worth ~10% of a real
    build's ATK and would look entirely plausible in a damage figure.
    """
    registry = NodeRegistry()
    log = ContributionLog(registry=registry)
    log.add(tags.Q_BASE_ATK, 300.0, tags.SRC_CHARACTER, "Ayaka at 90/6")
    log.add(tags.Q_BASE_ATK, 500.0, tags.SRC_WEAPON, "Mistsplitter Reforged")
    log.add(tags.Q_ATK_PCT, 1.0, tags.SRC_ARTIFACT, "sands main stat")

    result = Calculator(registry=registry).compute(stats.ATK_NODE)

    assert result == pytest.approx((300.0 + 500.0) * 2.0)


def test_there_is_no_second_stage():
    """The ZZZ layer had `pre` then `final`; Genshin does not, and inventing it would give
    every future kit a place to put a wrong answer."""
    single_stage = _value(stats.ATK_NODE, base_atk=1000.0, atk_pct=0.5, flat_atk=100.0)

    assert single_stage == pytest.approx(1600.0)


def test_contributions_to_one_quantity_add():
    """Four artifacts' worth of ATK% is one pool, not four competing values."""
    registry = NodeRegistry()
    log = ContributionLog(registry=registry)
    for index, percentage in enumerate((0.05, 0.10, 0.15, 0.466)):
        log.add(tags.Q_ATK_PCT, percentage, tags.SRC_ARTIFACT, f"substat {index}")
    log.add(tags.Q_BASE_ATK, 1000.0, tags.SRC_CHARACTER)

    assert Calculator(registry=registry).compute(stats.ATK_NODE) == pytest.approx(1766.0)


def test_an_unregistered_stat_resolves_to_zero_rather_than_raising():
    """A partially specified build must be evaluable; complaining is the damage chain's job.

    If this raised, every optimizer candidate would have to be fully populated before it
    could be scored, which is the opposite of what a search wants.
    """
    assert _value(stats.CRIT_RATE_NODE) == 0
    assert _value(stats.ATK_NODE) == 0


def test_the_flat_stats_are_single_pools():
    for node, quantity in (
        (stats.ELEMENTAL_MASTERY_NODE, tags.Q_ELEMENTAL_MASTERY),
        (stats.ENERGY_RECHARGE_NODE, tags.Q_ENERGY_RECHARGE),
        (stats.CRIT_DMG_NODE, tags.Q_CRIT_DMG),
        (stats.HEALING_BONUS_NODE, tags.Q_HEALING_BONUS),
    ):
        assert _value(node, **{quantity: 0.25}) == pytest.approx(0.25)


def test_crit_rate_has_no_implicit_base():
    """The character source registers the payload's 0.05; the graph does not invent it.

    A graph that hard-coded 5% would report a fictitious crit rate for a build with no
    character loaded — and would double it the moment the character source started
    registering its own, which is what F.3 does.
    """
    assert _value(stats.CRIT_RATE_NODE) == 0
    assert _value(stats.CRIT_RATE_NODE, crit_rate=0.05) == pytest.approx(0.05)


# ---- Damage channels ------------------------------------------------------

def test_each_damage_channel_has_its_own_bonus_pool():
    pyro = stats.dmg_bonus_node("pyro")
    cryo = stats.dmg_bonus_node("cryo")

    calculator = _calc(pyro_dmg_bonus=0.466, cryo_dmg_bonus=0.15)

    assert calculator.compute(pyro) == pytest.approx(0.466)
    assert calculator.compute(cryo) == pytest.approx(0.15)


def test_the_generic_dmg_bonus_is_not_folded_into_a_channel():
    """It is added once by the damage chain, to the channel the hit uses (F.5).

    Summing it here would make it invisible in an explained figure and double-counted on a
    hit that touches two channels.
    """
    assert _value(stats.dmg_bonus_node("pyro"), dmg_bonus=0.4) == 0


def test_the_shred_pool_holds_shred_and_not_the_enemys_own_resistance():
    """**The PR #7 HIGH finding, pinned.** The enemy's base RES lives on the enemy profile,
    not in this pool; adding both read a 10% enemy as 20% and understated every hit by ~11%.

    Contributions here are the build's: Deepwood's 4pc is -30%, and nothing else.
    """
    registry = NodeRegistry()
    log = ContributionLog(registry=registry)
    log.add(tags.res_shred_q("dendro"), -0.3, tags.SRC_ARTIFACT_SET, "Deepwood Memories 4pc")

    total = Calculator(registry=registry).compute(stats.res_shred_node("dendro"))

    assert total == pytest.approx(-0.3)


def test_every_channel_has_a_total_and_there_are_eight_of_them():
    channels = [name for name in stats.TOTALS if name.endswith("_dmg_bonus")]

    assert len(channels) == 8
    assert set(channels) == {tags.dmg_bonus_q(c) for c in tags.DAMAGE_CHANNELS}


# ---- Vocabulary -----------------------------------------------------------

def test_physical_is_a_damage_channel_but_not_a_vision():
    """C.2's distinction, carried into the DAG: seven visions, eight channels."""
    assert len(tags.VISIONS) == 7
    assert "physical" not in tags.VISIONS
    assert len(tags.DAMAGE_CHANNELS) == 8
    assert "physical" in tags.DAMAGE_CHANNELS


def test_a_channel_name_cannot_be_invented_at_a_call_site():
    """Adding a channel is an edit to one tuple, not a string built somewhere far away."""
    with pytest.raises(ValueError, match="not a damage channel"):
        tags.dmg_bonus_q("quantum")
    with pytest.raises(ValueError, match="not a damage channel"):
        tags.res_shred_q("imaginary")
    with pytest.raises(ValueError, match="not a damage channel"):
        tags.self_res_q("imaginary")


def test_a_scope_name_cannot_be_invented_either():
    with pytest.raises(ValueError, match="not an attack scope"):
        tags.scoped_stat_tag(tags.Q_DMG_BONUS, "ultimate")
    assert tags.scoped_stat_tag(tags.Q_DMG_BONUS, "charged").get("scope") == "charged"


def test_the_quantity_list_has_no_duplicates():
    """`ALL_QUANTITIES` is what the tests and the translator check membership against; a
    duplicate there means two things share a pool and would silently add together."""
    assert len(tags.ALL_QUANTITIES) == len(set(tags.ALL_QUANTITIES))


def test_attribution_does_not_hide_the_contribution_it_attributes():
    """The bug this design exists to prevent, pinned.

    `gather` returns registrations that are a **subset** of the read context, so putting the
    source in the tag — `{q: elemental_mastery, src: artifact}` — makes the contribution
    invisible to a plain `{q: elemental_mastery}` read. It would not error; the stat would
    silently be 0. Attribution therefore rides beside the registry, not inside the tag.
    """
    registry = NodeRegistry()
    log = ContributionLog(registry=registry)
    log.add(tags.Q_ELEMENTAL_MASTERY, 187.0, tags.SRC_ARTIFACT, "goblet main stat")

    assert Calculator(registry=registry).compute(stats.ELEMENTAL_MASTERY_NODE) == 187.0

    # …and the tag-in-registration version is the trap, demonstrated rather than described.
    trap = NodeRegistry()
    trap.register(Tag.of(q=tags.Q_ELEMENTAL_MASTERY, src=tags.SRC_ARTIFACT), const(187.0))
    assert Calculator(registry=trap).compute(stats.ELEMENTAL_MASTERY_NODE) == 0


def test_a_hit_cannot_be_evaluated_under_an_invented_scope():
    """The one place scope enters an evaluation must reject a scope nothing could register."""
    with pytest.raises(ValueError, match="not an attack scope"):
        stats.scoped(stats.ATK_NODE, "ultimate")


def test_the_wearers_own_resistance_has_its_own_pool():
    """Nothing reads it yet — there is no incoming-damage model — but the import path needs
    somewhere correct to put `FIGHT_PROP_*_SUB_HURT`, and that somewhere is not enemy shred.
    """
    registry = NodeRegistry()
    log = ContributionLog(registry=registry)
    log.add(tags.self_res_q("pyro"), 0.4, tags.SRC_ARTIFACT_SET, "2pc: +40% Pyro RES")
    calculator = Calculator(registry=registry)

    assert calculator.compute(stats.self_res_node("pyro")) == pytest.approx(0.4)
    assert calculator.compute(stats.res_shred_node("pyro")) == 0
