"""Task B5 — the optimizer's context cache must not collide across custom buffs (#64).

`optimize_discs` caches per set-distribution (`_ctx_cache`, keyed on
`frozenset(set_counts.items())`) and its step signatures carry
`frozenset(conditions.active)` / `frozenset(conditions.stack_counts.items())`. Neither
mentions custom buffs, which is what B5 asks to check: if a custom buff could land on the
wrong side of a cache key, two optimizations differing only in their stage buffs would
return the same answer, and the feature would appear to work while doing nothing.

It cannot, and the reason is structural rather than lucky: custom buffs are synthesized
into `base_build.modifiers` (B4), the cache is a **local** built fresh per call, and the
contexts it caches are derived from that same `base_build`. So the snapshot *is* part of
the key by construction. This module pins that, because "structural" is a property that
survives only as long as someone keeps checking it — the cache could be lifted to module
scope in a future optimisation pass and nothing else here would notice.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
    optimize_discs,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    synthesize_custom_buffs,
)


class _Buff:
    """Structural stand-in for `schemas.damage.CustomBuff`."""

    def __init__(self, label: str, stat: str, value: int) -> None:
        self.label = label
        self.stat = stat
        self.value = value
        self.target = "self"
        self.conditions = ["always"]
        self.scopes = ["all"]
        self.max_stacks = 1


def _base() -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        agent_crit_rate=500,
        agent_crit_dmg=5000,
    )


def _six_slots() -> list[DiscCandidate]:
    return [DiscCandidate(disc_id=f"d{s}", slot=s, set_id=1, substats=[]) for s in range(1, 7)]


def _combo() -> list[ComboStep]:
    return [
        ComboStep(
            label="BA1",
            attack_id="att-1",
            attack_name="Basic 1",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        )
    ]


def _run(build: BuildSnapshot):
    return optimize_discs(
        base_build=build,
        enemy=EnemySnapshot(level=60, base_def=50, element_res=0),
        combo_steps=_combo(),
        inventory=_six_slots(),
        disc_set_modifiers={},
        constraints=OptimizerConstraints(top_n=1),
        conditions=ActiveConditions(active={Condition.ALWAYS}),
    )


def test_two_runs_differing_only_in_custom_buffs_do_not_collide() -> None:
    """The assertion B5 asks for, stated exactly: same everything, different stage buff,
    different total damage."""
    plain = _run(_base())
    buff = synthesize_custom_buffs([_Buff("DA: Ice DMG", "ice_dmg", 3000)])
    buffed = _run(replace(_base(), modifiers=buff))
    assert plain.builds
    assert buffed.builds
    assert buffed.builds[0].total_damage > plain.builds[0].total_damage


def test_the_same_custom_buff_twice_is_reproducible() -> None:
    """The other half of a cache-key check: differing inputs must differ, identical
    inputs must not. A cache that keyed on something incidental could fail this too."""
    mods = synthesize_custom_buffs([_Buff("DA: Ice DMG", "ice_dmg", 3000)])
    first = _run(replace(_base(), modifiers=mods))
    second = _run(replace(_base(), modifiers=mods))
    assert first.builds[0].total_damage == second.builds[0].total_damage


def test_two_different_custom_buff_values_score_differently() -> None:
    """A collision would be invisible between two *buffed* runs as well, not only
    against the unbuffed baseline."""
    weak = synthesize_custom_buffs([_Buff("DA: Ice DMG", "ice_dmg", 1000)])
    strong = synthesize_custom_buffs([_Buff("DA: Ice DMG", "ice_dmg", 5000)])
    small = _run(replace(_base(), modifiers=weak))
    large = _run(replace(_base(), modifiers=strong))
    assert large.builds[0].total_damage > small.builds[0].total_damage
