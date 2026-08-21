"""Tasks B3/B4 — custom buffs become ordinary `Modifier` rows (issue #64).

The design's claim is that a stage buff needs *no* special case: synthesize it into a
`Modifier` and condition gating, scope filtering, stacking, attribution and
`disabled_buffs` all work on it for free (DESIGN_buff_context.md §2.3). A claim like that
is only worth what its test is worth, so the load-bearing assertion here is the
**equivalence** one: a custom buff carrying the same stat/value/conditions as a kit
modifier must move the resolved stats by exactly the same amount. If it ever doesn't,
the synthesis has quietly become a second implementation of the modifier path.

The rest guards the slug, which is what `disabled_buffs` holds *between* requests — an
id that is not stable is a toggle that does not stay toggled.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.build_damage_service import BuildSnapshot, resolve_build_stats
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    DuplicateCustomBuffError,
    Modifier,
    ModifierSource,
    ModifierTarget,
    UnslugifiableCustomBuffError,
    custom_buff_label,
    synthesize_custom_buffs,
)


class _Buff:
    """Structural stand-in for `schemas.damage.CustomBuff` (the synthesiser is
    duck-typed so `services` need not import `schemas`)."""

    def __init__(
        self,
        label: str,
        stat: str = "ice_dmg",
        value: int = 1500,
        target: str = "team",
        conditions: list[str] | None = None,
        scopes: list[str] | None = None,
        max_stacks: int = 1,
    ) -> None:
        self.label = label
        self.stat = stat
        self.value = value
        self.target = target
        self.conditions = conditions or ["always"]
        self.scopes = scopes or ["all"]
        self.max_stacks = max_stacks


def test_maps_every_field_onto_the_modifier() -> None:
    (mod,) = synthesize_custom_buffs(
        [
            _Buff(
                "DA Stage 3: Ice DMG",
                stat="ice_dmg",
                value=1500,
                target="self",
                conditions=["enemy_stunned"],
                scopes=["chain"],
                max_stacks=3,
            )
        ]
    )
    assert mod.stat == "ice_dmg"
    assert mod.value == 1500
    assert mod.source is ModifierSource.EXTERNAL
    assert mod.source_label == "custom:da_stage_3_ice_dmg"
    assert mod.target is ModifierTarget.SELF
    assert mod.conditions == (Condition.ENEMY_STUNNED,)
    assert mod.scopes == (AttackScope.CHAIN,)
    assert mod.max_stacks == 3


def test_team_is_the_default_target() -> None:
    """A stage buff is granted to the squad, not to whoever is on field."""
    (mod,) = synthesize_custom_buffs([_Buff("DA: squad ATK", stat="atk_pct")])
    assert mod.target is ModifierTarget.TEAM


def test_no_new_modifier_source_member() -> None:
    """`EXTERNAL` is already documented as this concept, and a new enum member would need
    handling in every match over it (DESIGN §2.3). The `custom:` prefix carries the
    distinction instead."""
    (mod,) = synthesize_custom_buffs([_Buff("x")])
    assert mod.source is ModifierSource.EXTERNAL
    assert mod.source_label.startswith("custom:")


def test_the_slug_is_derived_from_the_label_not_assigned() -> None:
    """`disabled_buffs` holds this string between requests: a random id would mean a
    stage buff switched off comes back on the next calculation."""
    first = synthesize_custom_buffs([_Buff("DA Stage 3: Ice DMG")])[0].source_label
    second = synthesize_custom_buffs([_Buff("DA Stage 3: Ice DMG")])[0].source_label
    assert first == second == custom_buff_label("DA Stage 3: Ice DMG")


def test_colliding_slugs_are_rejected_not_suffixed() -> None:
    """B3 asks for this decision to be made rather than left to chance. A suffix would
    make the id depend on list order, so reordering — which nobody reads as a semantic
    change — would silently move which buff a `disabled_buffs` entry refers to. That
    swaps a visible error for an invisible one."""
    with pytest.raises(DuplicateCustomBuffError, match="distinguishable names"):
        synthesize_custom_buffs([_Buff("DA Stage 3: Ice DMG"), _Buff("DA stage 3 — ice dmg")])


@pytest.mark.parametrize("label", ["!!!", "🔥", "   ", "---"])
def test_a_label_that_slugifies_to_nothing_is_rejected(label: str) -> None:
    """`min_length=1` is not the same guarantee as "has a usable id". These all clear it
    and slugify to the empty string, so every one of them would be addressable only as
    `custom:` — the duplicate problem in a different shape, and unaddressable even alone.
    """
    with pytest.raises(UnslugifiableCustomBuffError, match="slugifies to nothing"):
        synthesize_custom_buffs([_Buff(label)])


def test_a_label_with_one_alphanumeric_is_enough() -> None:
    """The rejection is narrow on purpose: it fires only when there is nothing to slug,
    not on decorated labels. `custom_buff_label` strips the rest."""
    assert synthesize_custom_buffs([_Buff("🔥 3")])[0].source_label == "custom:3"


def test_unknown_condition_raises_rather_than_silently_dropping() -> None:
    with pytest.raises(ValueError, match="not a valid Condition"):
        synthesize_custom_buffs([_Buff("x", conditions=["enemy_is_asleep"])])


# ---------------------------------------------------------------------------
# B4 — the equivalence assertion
# ---------------------------------------------------------------------------

_BASE = BuildSnapshot(
    agent_name="Equivalence",
    agent_element="ice",
    agent_specialty="attack",
    agent_level=60,
    agent_base_atk=1000,
    agent_crit_rate=500,
    agent_crit_dmg=5000,
    modifiers=[],
)
_COND = ActiveConditions(active={Condition.ALWAYS})


@pytest.mark.parametrize(
    ("stat", "value"),
    [("ice_dmg", 1500), ("atk_pct", 2000), ("crit_rate", 800), ("flat_atk", 400)],
)
def test_a_custom_buff_and_an_equal_kit_modifier_resolve_identically(
    stat: str, value: int
) -> None:
    """The claim being tested is DESIGN §2.3's: synthesis is not a parallel path.

    A kit modifier and a custom buff with the same stat, value, conditions and scopes
    must produce the same resolved stat block — differing only in provenance, which is
    what `source`/`source_label` are for.
    """
    kit = Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label="Core Passive: Equivalent",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
    )
    (custom,) = synthesize_custom_buffs(
        [_Buff("Equivalent", stat=stat, value=value, target="self")]
    )

    from_kit = resolve_build_stats(replace(_BASE, modifiers=[kit]), _COND)
    from_custom = resolve_build_stats(replace(_BASE, modifiers=[custom]), _COND)
    assert from_custom == from_kit
    # …and both actually moved something, or the equality above is vacuous.
    assert from_kit != resolve_build_stats(_BASE, _COND)


def test_an_inactive_condition_gates_a_custom_buff_like_any_other() -> None:
    (custom,) = synthesize_custom_buffs(
        [_Buff("Stunned-only", stat="ice_dmg", value=2000, target="self",
               conditions=["enemy_stunned"])]
    )
    gated = replace(_BASE, modifiers=[custom])
    assert resolve_build_stats(gated, _COND) == resolve_build_stats(_BASE, _COND)
    live = ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED})
    assert resolve_build_stats(gated, live) != resolve_build_stats(_BASE, _COND)
