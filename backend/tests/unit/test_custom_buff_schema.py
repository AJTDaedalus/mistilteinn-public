"""Task B1 — `CustomBuff` accepts only what the calc can actually honour (issue #64).

A stage buff the server accepts and the calc then drops is worse than a rejected one: the
user sees their numbers not move and has no way to tell "the buff did nothing" from "the
buff is not modelled". So every field is validated against the engine's own vocabulary and
an unknown value is a 422.

The allowlist is imported from `buff_resolver`, not restated, so a stat added to the engine
becomes authorable with no second edit — and, more importantly, a stat *removed* from the
engine stops being offered instead of silently becoming a no-op.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.damage import CUSTOM_BUFF_STATS, BuffContext, CustomBuff
from app.services.buff_resolver import _COMBAT_STATS, _DMG_BONUS_STATS, _STAT_TO_INPUT


def test_a_plain_stage_buff_round_trips() -> None:
    buff = CustomBuff(label="DA Stage 3: Ice DMG", stat="ice_dmg", value=1500)
    assert (buff.target, buff.conditions, buff.scopes, buff.max_stacks) == (
        "team",
        ["always"],
        ["all"],
        1,
    )


def test_debuffs_are_expressible() -> None:
    """Stage effects go both ways; a negative value must not be rejected as invalid."""
    assert CustomBuff(label="Stage: DEF up", stat="dmg_bonus", value=-1000).value == -1000


@pytest.mark.parametrize("stat", ["atk", "def", "hp"])
def test_disc_substat_keys_are_rejected_with_the_key_to_use_instead(stat: str) -> None:
    """The headline finding of B2: these three are `StatType` members that no buff
    consumer reads, so a picker built from `StatType` would offer three controls that do
    nothing. Rejecting them silently would be almost as bad — the error names the key that
    works."""
    with pytest.raises(ValidationError, match=f"flat_{stat}"):
        CustomBuff(label="x", stat=stat, value=1000)


def test_unknown_stat_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown buff stat"):
        CustomBuff(label="x", stat="ice_dmg_bonus_pct", value=1000)


def test_unknown_condition_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown condition"):
        CustomBuff(label="x", stat="ice_dmg", value=1, conditions=["enemy_is_asleep"])


def test_unknown_scope_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown scope"):
        CustomBuff(label="x", stat="ice_dmg", value=1, scopes=["parry"])


def test_real_conditions_and_scopes_are_accepted() -> None:
    buff = CustomBuff(
        label="Stage: stunned-only Ice DMG",
        stat="ice_dmg",
        value=2000,
        conditions=["enemy_stunned"],
        scopes=["chain"],
        target="self",
        max_stacks=3,
    )
    assert buff.conditions == ["enemy_stunned"]
    assert buff.scopes == ["chain"]


def test_label_and_stacks_are_bounded() -> None:
    with pytest.raises(ValidationError):
        CustomBuff(label="", stat="ice_dmg", value=1)
    with pytest.raises(ValidationError):
        CustomBuff(label="x", stat="ice_dmg", value=1, max_stacks=0)


def test_allowlist_is_the_resolver_vocabulary() -> None:
    """Pins the derivation, not the contents. If someone hardcodes a list here later, or a
    stat leaves the resolver, this fails instead of the feature quietly shrinking. The
    three dead keys are absent because the resolver never had them — nothing subtracts
    them, and nothing should have to."""
    resolver_vocabulary = set(_STAT_TO_INPUT) | set(_DMG_BONUS_STATS) | set(_COMBAT_STATS)
    assert resolver_vocabulary == CUSTOM_BUFF_STATS
    assert CUSTOM_BUFF_STATS.isdisjoint({"atk", "def", "hp"})
    # Spot-check the buckets a stage buff actually uses.
    for stat in ("ice_dmg", "crit_rate", "flat_atk", "vulnerability", "res_reduction"):
        assert stat in CUSTOM_BUFF_STATS


def test_context_defaults_to_no_custom_buffs() -> None:
    """Phase A callers send no `custom_buffs`; they must keep behaving identically."""
    assert BuffContext().custom_buffs == []


def test_context_carries_custom_buffs() -> None:
    ctx = BuffContext(custom_buffs=[{"label": "DA: ATK", "stat": "atk_pct", "value": 1000}])
    assert ctx.custom_buffs[0].stat == "atk_pct"


def test_colliding_labels_are_a_422_not_a_500() -> None:
    """The synthesiser raises on this too, but a validation error here names both labels
    and reaches the user as a 422. See `test_custom_buff_synthesis` for why colliding
    slugs are rejected rather than suffixed."""
    with pytest.raises(ValidationError, match="distinguishable names"):
        BuffContext(
            custom_buffs=[
                {"label": "DA Stage 3: Ice DMG", "stat": "ice_dmg", "value": 1500},
                {"label": "DA stage 3 — ice dmg", "stat": "ice_dmg", "value": 1500},
            ]
        )


def test_a_label_that_slugifies_to_nothing_is_a_422_not_a_500() -> None:
    """`min_length=1` accepts `"!!!"`, which slugifies to the empty string and would be
    addressable only as `custom:`. Same rejection as the synthesiser's, one layer up."""
    with pytest.raises(ValidationError, match="slugifies to nothing"):
        BuffContext(custom_buffs=[{"label": "!!!", "stat": "ice_dmg", "value": 1500}])


def test_distinguishable_labels_are_fine() -> None:
    ctx = BuffContext(
        custom_buffs=[
            {"label": "DA Stage 3: Ice DMG", "stat": "ice_dmg", "value": 1500},
            {"label": "DA Stage 3: ATK", "stat": "atk_pct", "value": 1000},
        ]
    )
    assert len(ctx.custom_buffs) == 2
