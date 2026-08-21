"""Task 7 — Lumiflux dual-tagging choke point.

`build_damage_service._resolve_and_calc` (DESIGN_remielle.md §5.2) is the single
substitution point where a Lumiflux build's `dmg_element` becomes the fluxed
element for **stat aggregation** (`resolve_modifiers(damage_element=...)`,
`stats.elemental_dmg`) and **enemy RES targeting** (`enemy.res_map` lookup) —
while `build.agent_element` stays `"lumiflux"` everywhere else, so every
identity check (`EQUIPPER_IS_<element>`, attribute-locked set/W-Engine gates)
continues to see `lumiflux`, never the fluxed element.

These tests exercise the choke point through the public
`calculate_build_damage` entry point (the `element` kwarg is exactly the
vehicle a caller uses to hand in an already-resolved flux — team-roster
derivation via `lumiflux.resolve_fluxed_element` is upstream, wired in Task 8).
Covers DESIGN §9.1 tests 6 and 7, plus the no-flux default (§5.3).
"""

from __future__ import annotations

from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    _resolve_and_calc,
    calculate_build_damage,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _lumiflux_snap(
    *,
    agent_base_atk: int = 900,
    wengine_base_atk: int = 600,
    modifiers: list[Modifier] | None = None,
) -> BuildSnapshot:
    """A minimal Lumiflux-element build snapshot (agent_element never flexed)."""
    return BuildSnapshot(
        agent_base_hp=8000,
        agent_base_atk=agent_base_atk,
        agent_base_def=600,
        wengine_base_atk=wengine_base_atk,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_element="lumiflux",
        agent_specialty="anomaly",
        agent_level=60,
        modifiers=modifiers or [],
    )


def _enemy(
    *,
    element_res: int = 0,
    res_map: dict[str, int] | None = None,
) -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=50, element_res=element_res, res_map=res_map or {})


def _mod(
    stat: str,
    value: int,
    *,
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,),
    source_label: str = "test",
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.EXTERNAL,
        source_label=source_label,
        target=ModifierTarget.SELF,
        conditions=conditions,
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


class TestFluxedDmgPctApplies:
    """DESIGN §9.1 test 7 — fluxed DMG% applies only for the fluxed element."""

    def test_physical_dmg_pct_raises_damage_when_fluxed_physical(self):
        baseline = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        buffed = calculate_build_damage(
            build=_lumiflux_snap(modifiers=[_mod("physical_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        assert buffed.damage.total > baseline.damage.total
        assert buffed.damage.boost_mult == 13000

    def test_fire_dmg_pct_does_not_raise_damage_when_fluxed_physical(self):
        baseline = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        buffed = calculate_build_damage(
            build=_lumiflux_snap(modifiers=[_mod("fire_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        assert buffed.damage.total == baseline.damage.total
        assert buffed.damage.boost_mult == 10000

    def test_fluxing_to_fire_instead_picks_up_fire_dmg_pct(self):
        """Same build, fluxed to Fire this time — the fire_dmg row now applies."""
        result = calculate_build_damage(
            build=_lumiflux_snap(modifiers=[_mod("fire_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="fire",
        )
        assert result.damage.boost_mult == 13000


class TestFluxedEnemyResTargeting:
    """RES-targeting sibling of the same substitution (DESIGN §5.2)."""

    def test_fluxed_physical_uses_physical_res_map_entry(self):
        enemy = _enemy(res_map={"physical": 2000, "fire": -1000})
        result = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=enemy,
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        # RES area = 10000 - 2000 = 8000
        assert result.damage.res_mult == 8000

    def test_fluxed_fire_uses_fire_res_map_entry_not_physical(self):
        enemy = _enemy(res_map={"physical": 2000, "fire": -1000})
        result = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=enemy,
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="fire",
        )
        # RES area = 10000 - (-1000) = 11000
        assert result.damage.res_mult == 11000


class TestIdentityChecksNeverFlux:
    """DESIGN §9.1 test 6 — an attribute-locked set condition stays inactive.

    Chaos Jazz's real 4pc modifier (app/data/modifiers/disc_sets/chaos_jazz.json)
    is exactly this shape: `fire_dmg`, gated on `Condition.EQUIPPER_IS_FIRE`.
    In the real pipeline that condition is auto-injected from `build.agent_element`
    (snapshot_builder.inject_environment_conditions) — for a Lumiflux build that
    injects `equipper_is_lumiflux`, never `equipper_is_fire`, however she is
    fluxed. These tests model that directly: `conditions` never carries
    `EQUIPPER_IS_FIRE` for a Lumiflux build, regardless of the `element` override.
    """

    def test_equipper_is_fire_gated_modifier_stays_inactive_when_fluxed_fire(self):
        chaos_jazz_4pc = _mod(
            "fire_dmg",
            1500,
            conditions=(Condition.EQUIPPER_IS_FIRE,),
            source_label="4pc: Fire DMG",
        )
        # conditions carries no EQUIPPER_IS_FIRE — matches what the real pipeline
        # would inject for a lumiflux-element build (equipper_is_lumiflux, not
        # equipper_is_fire), even though this instance is fluxed to Fire.
        result = calculate_build_damage(
            build=_lumiflux_snap(modifiers=[chaos_jazz_4pc]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="fire",
        )
        assert result.damage.boost_mult == 10000

    def test_equipper_is_fire_condition_present_still_gates_correctly(self):
        """Sanity check: the modifier *does* fire for a genuinely Fire-element build."""
        fire_snap = BuildSnapshot(
            agent_base_hp=8000,
            agent_base_atk=900,
            agent_base_def=600,
            wengine_base_atk=600,
            agent_element="fire",
            agent_specialty="anomaly",
            agent_level=60,
            modifiers=[
                _mod(
                    "fire_dmg",
                    1500,
                    conditions=(Condition.EQUIPPER_IS_FIRE,),
                    source_label="4pc: Fire DMG",
                )
            ],
        )
        result = calculate_build_damage(
            build=fire_snap,
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(active={Condition.ALWAYS, Condition.EQUIPPER_IS_FIRE}),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.boost_mult == 11500


class TestNoFluxDefault:
    """DESIGN §5.3 — solo calc, no team, no override: pure Lumiflux damage."""

    def test_no_attribute_dmg_pct_applies_without_flux(self):
        build = _lumiflux_snap(
            modifiers=[_mod("physical_dmg", 3000), _mod("fire_dmg", 3000)]
        )
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.boost_mult == 10000

    def test_enemy_res_contribution_is_zero_without_flux(self):
        enemy = _enemy(res_map={"physical": 2000, "fire": -1000, "ice": 4000})
        result = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=enemy,
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.res_mult == 10000


class TestResolveAndCalcChokePoint:
    """Directly exercises `_resolve_and_calc` — the single substitution site."""

    def test_dmg_element_is_lumiflux_by_default(self):
        ctx = _resolve_and_calc(_lumiflux_snap(), ActiveConditions(), AttackScope.ALL)
        # "lumiflux_dmg" is not a real TotalStats attribute — elemental_dmg's
        # getattr default (0) proves no phantom bucket is picked up.
        assert ctx.stats.elemental_dmg("lumiflux") == 0
        assert ctx.enemy_res == 0

    def test_enemy_res_falls_back_to_element_res_when_dmg_element_absent_from_res_map(self):
        enemy = _enemy(element_res=1234, res_map={"physical": 2000})
        ctx = _resolve_and_calc(
            _lumiflux_snap(), ActiveConditions(), AttackScope.ALL, enemy=enemy
        )
        # dmg_element defaults to "lumiflux", never a res_map key.
        assert ctx.enemy_res == 1234

    def test_enemy_res_is_zero_when_enemy_omitted(self):
        ctx = _resolve_and_calc(
            _lumiflux_snap(), ActiveConditions(), AttackScope.ALL, "physical"
        )
        assert ctx.enemy_res == 0


class TestFluxedElementReachesTheDamageChain:
    """Pipeline finding P-F1 / hardening Task 17.

    The dual-tag choke point (`_resolve_and_calc(element=...)`) existed and was
    unit-tested, but a repo-wide grep found **zero production callers** passing
    a fluxed element into it. The API resolved `fluxed_element` and echoed it as
    "the element actually used" while every Lumiflux hit was computed as pure
    Lumiflux: her fluxed-element DMG% contributed nothing, and the enemy's RES
    for that element was replaced by a neutral 0 -- understating her against a
    weak enemy and overstating her against a resistant one.

    User decision (2026-07-29): implement, not defer.
    """

    def _remielle(self):
        from app.services.build_damage_service import BuildSnapshot

        return BuildSnapshot(
            agent_name="Remielle",
            agent_element="lumiflux",
            agent_source_id="1581",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=200,
        )

    def _ally(self, element):
        from app.services.build_damage_service import BuildSnapshot

        return BuildSnapshot(
            agent_name=f"{element.title()}Ally",
            agent_element=element,
            agent_level=60,
            agent_base_atk=1000,
        )

    def _damage(self, *, fluxed_elements, fire_res):
        from app.models.build import EnemyProfile
        from app.services.anomaly_simulator import (
            SimulatedAttackStep,
            _SyntheticAttack,
            simulate,
        )

        class _MoveSpec:
            buildup = 0
            duration_s = 1.0
            hits = 1
            element = "lumiflux"
            scope = "basic"
            consolidated = False

        class _AgentMoves:
            def __init__(self, moves):
                self.moves = moves

        result = simulate(
            {"rem": self._remielle()},
            [
                SimulatedAttackStep(
                    "rem",
                    "hit",
                    [
                        _SyntheticAttack(
                            id=None,
                            name="hit",
                            element="lumiflux",
                            skill_key="Basic",
                            anomaly_buildup=0,
                            damage_base=10000,  # 100% MV -- a real, scorable hit
                        )
                    ],
                )
            ],
            EnemyProfile(
                name="Asymmetric RES",
                level=60,
                defense=50,
                fire_res=fire_res,
                anomaly_duration_default=10.0,
            ),
            {"remielle": _AgentMoves({"hit": _MoveSpec()})},
            fluxed_elements=fluxed_elements,
        )
        hits = [e for e in result.events if e.kind == "hit"]
        assert hits, "expected a hit event"
        return sum(h.damage for h in hits)

    def test_a_fluxed_hit_uses_the_fluxed_elements_enemy_res(self):
        """Against an enemy WEAK to the fluxed element (negative RES) the hit
        must land harder than the unfluxed baseline."""
        unfluxed = self._damage(fluxed_elements={}, fire_res=-5000)
        fluxed = self._damage(fluxed_elements={"rem": "fire"}, fire_res=-5000)
        assert fluxed > unfluxed

    def test_a_fluxed_hit_against_a_resistant_enemy_lands_softer(self):
        """The other direction, so the test cannot pass on a blanket buff."""
        unfluxed = self._damage(fluxed_elements={}, fire_res=5000)
        fluxed = self._damage(fluxed_elements={"rem": "fire"}, fire_res=5000)
        assert fluxed < unfluxed

    def test_an_unfluxed_request_is_byte_identical(self):
        """The neutral path must not move: `element=None` when unfluxed."""
        a = self._damage(fluxed_elements={}, fire_res=-5000)
        b = self._damage(fluxed_elements={}, fire_res=5000)
        assert a == b, "Lumiflux RES is neutral 0 either way when unfluxed"

    def test_a_flux_for_another_agent_does_not_touch_hers(self):
        assert self._damage(
            fluxed_elements={"someone_else": "fire"}, fire_res=-5000
        ) == self._damage(fluxed_elements={}, fire_res=-5000)
