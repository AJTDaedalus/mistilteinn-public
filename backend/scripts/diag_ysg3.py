"""Diagnostic dump for YSG3 build — compare to in-game numbers.

Prints raw inputs to compute_total_stats and the resulting stats so we
can see exactly what the engine is feeding the calc.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from app.database import async_session_factory as async_session_maker
from app.repositories.build import BuildRepository
from app.services.buff_resolver import resolve_modifiers
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    ModifierTarget,
)
from app.services.snapshot_builder import build_snapshot_from_db, inject_derived_conditions
from app.services.stat_calculator import (
    StatInputs,
    accumulate_disc_stats,
    compute_total_stats,
)

BUILD_ID = "019def20-4937-79d3-bd8e-536750955979"


def _parse_conditions(raw: list[str]) -> ActiveConditions:
    if not raw:
        raw = [Condition.ALWAYS.value]
    return ActiveConditions(active=set(raw))


async def main() -> None:  # noqa: PLR0915
    async with async_session_maker() as session:  # type: AsyncSession
        repo = BuildRepository(session)
        build = await repo.get_by_id(BUILD_ID)
        if build is None:
            print("Build not found")
            return
        agent = build.agent

        snap = build_snapshot_from_db(build, agent)

        # Resolve conditions: same logic as combo endpoint, plus auto-inject
        saved = list(build.active_conditions or [])
        merged = list(dict.fromkeys([Condition.ALWAYS.value, *saved]))
        conditions = _parse_conditions(merged)
        inject_derived_conditions(conditions, agent)

        print("=== SNAPSHOT BASE ===")
        print(f"agent_base_atk (lvl-scaled): {snap.agent_base_atk}")
        print(f"wengine_base_atk (lvl-scaled): {snap.wengine_base_atk}")
        print(f"agent_crit_rate (base bp): {snap.agent_crit_rate}")
        print(f"agent_crit_dmg (base bp): {snap.agent_crit_dmg}")
        print(f"agent_anomaly_proficiency: {snap.agent_anomaly_proficiency}")
        print(f"agent_pen_flat: {snap.agent_pen_flat}, pen_ratio: {snap.agent_pen_ratio}")
        print(f"agent_level: {snap.agent_level}, element: {snap.agent_element}")

        # Disc accumulation
        disc = accumulate_disc_stats(snap.disc_stats)
        print("\n=== DISC ACCUMULATION ===")
        print(json.dumps(asdict(disc), indent=2, default=str))

        # Modifiers (just labels)
        print("\n=== MODIFIERS (resolved against active conditions) ===")
        print(f"Active conditions: {sorted(conditions.active)}")
        buffs = resolve_modifiers(
            snap.modifiers,
            conditions,
            attack_scope=AttackScope.ALL,
            target_filter=ModifierTarget.SELF,
        )
        print(f"\nstat_bonuses: {dict(buffs.stat_bonuses)}")
        print(f"dmg_bonuses (sum bp): {sum(buffs.dmg_bonuses)}  list: {buffs.dmg_bonuses}")
        print(f"combat_bonuses: {dict(buffs.combat_bonuses)}")
        print("\nModifier list (active filter only):")
        for m in snap.modifiers:
            if not all(c == "always" or c in conditions.active for c in m.conditions):
                continue
            print(
                f"  [{m.source.value:18}] {m.source_label:38} {m.stat:24} "
                f"+{m.value} (cond={m.conditions})"
            )

        # Build StatInputs same way build_damage_service does
        inputs = StatInputs(
            agent_base_hp=snap.agent_base_hp,
            agent_base_atk=snap.agent_base_atk,
            agent_base_def=snap.agent_base_def,
            wengine_base_atk=snap.wengine_base_atk,
            hp_pct=disc.hp_pct,
            atk_pct=disc.atk_pct,
            def_pct=disc.def_pct,
            flat_hp=disc.flat_hp,
            flat_atk=disc.flat_atk,
            flat_def=disc.flat_def,
            crit_rate=snap.agent_crit_rate + disc.crit_rate,
            crit_dmg=snap.agent_crit_dmg + disc.crit_dmg,
            anomaly_proficiency=snap.agent_anomaly_proficiency + disc.anomaly_proficiency,
            anomaly_mastery=disc.anomaly_mastery,
            impact=disc.impact,
            energy_regen=disc.energy_regen,
            pen_flat=snap.agent_pen_flat + disc.pen_flat,
            pen_ratio=snap.agent_pen_ratio + disc.pen_ratio,
            physical_dmg=disc.physical_dmg,
            fire_dmg=disc.fire_dmg,
            ice_dmg=disc.ice_dmg,
            electric_dmg=disc.electric_dmg,
            ether_dmg=disc.ether_dmg,
        )
        print("\n=== INPUTS BEFORE BUFFS APPLIED ===")
        print(f"  base_atk (agent+wengine): {inputs.agent_base_atk + inputs.wengine_base_atk}")
        print(f"  atk_pct: {inputs.atk_pct} bp ({inputs.atk_pct / 100:.2f}%)")
        print(f"  flat_atk: {inputs.flat_atk}")
        print(f"  crit_rate: {inputs.crit_rate} bp ({inputs.crit_rate / 100:.2f}%)")
        print(f"  crit_dmg: {inputs.crit_dmg} bp ({inputs.crit_dmg / 100:.2f}%)")

        buffs.apply_to_stat_inputs(inputs)
        print("\n=== INPUTS AFTER BUFFS APPLIED ===")
        print(f"  atk_pct: {inputs.atk_pct} bp ({inputs.atk_pct / 100:.2f}%)")
        print(f"  flat_atk: {inputs.flat_atk}")
        print(f"  final_atk_pct: {inputs.final_atk_pct} bp ({inputs.final_atk_pct / 100:.2f}%)")
        print(f"  final_flat_atk: {inputs.final_flat_atk}")
        print(f"  crit_rate: {inputs.crit_rate} bp ({inputs.crit_rate / 100:.2f}%)")
        print(f"  crit_dmg: {inputs.crit_dmg} bp ({inputs.crit_dmg / 100:.2f}%)")
        print(f"  pen_flat: {inputs.pen_flat}, pen_ratio: {inputs.pen_ratio}")

        total = compute_total_stats(inputs)
        print("\n=== TOTAL STATS ===")
        print(f"  ATK   : {total.atk}")
        print(f"  HP    : {total.hp}")
        print(f"  DEF   : {total.defense}")
        print(f"  CR    : {total.crit_rate} bp ({total.crit_rate / 100:.2f}%)")
        print(f"  CD    : {total.crit_dmg} bp ({total.crit_dmg / 100:.2f}%)")
        print(f"  Phys% : {total.physical_dmg} bp")
        print(f"  AP    : {total.anomaly_proficiency}")
        print(f"  PEN   : flat={total.pen_flat} ratio={total.pen_ratio}")


if __name__ == "__main__":
    asyncio.run(main())
