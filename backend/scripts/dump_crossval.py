"""Task 16b — Cross-validation capture aid.

Given an archetype key, loads the build from the DB (or constructs a bare
build from base agent stats), runs simulate() with a fixed step list, and
prints the resolved stat block + per-event output so the author can:
  (a) transcribe the stat line into ZO, and
  (b) eyeball sim-vs-ZO before freezing the golden fixture.

This script is a developer capture aid; it is NOT run in CI.

Usage:
    docker compose exec backend python -m scripts.dump_crossval --archetype burnice_burn
    docker compose exec backend python -m scripts.dump_crossval --archetype yanagi_shock
    docker compose exec backend python -m scripts.dump_crossval --archetype jane_assault
    docker compose exec backend python -m scripts.dump_crossval --archetype vivian_corruption

Supported archetypes:
    burnice_burn      Burnice with Electro-Lip Gloss build (DB build 019e7ade)
    yanagi_shock      Yanagi with Timeweaver build (DB build 019e673e)
    jane_assault      Jane bare build (M0, L60, no W-engine, no discs)
    vivian_corruption Vivian bare build (M0, L60, no W-engine, no discs)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.data.loaders.moves import load_agent_moves
from app.database import engine
from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.models.enums import HitMode
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot, resolve_build_stats
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import build_snapshot_from_db

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_MOVES_DB = load_agent_moves()

if TYPE_CHECKING:
    from app.services.stat_calculator import TotalStats

# ---------------------------------------------------------------------------
# Archetype definitions
# ---------------------------------------------------------------------------

#: Archetypes whose build is reconstructed from the golden fixture's own `stat_line`.
#: They used to name build UUIDs that lived in exactly one developer's database and were
#: never checked in, so this aid could not be run for them by anyone else — see
#: `tests/integration/test_zo_crossval._load_stat_line_build` for the full reasoning.
_STAT_LINE_BUILDS: dict[str, str] = {
    "burnice_burn": "Burnice",
    "yanagi_shock": "Yanagi",
}
_FIXTURES_DIR = BACKEND_ROOT / "tests" / "integration" / "fixtures" / "zo_crossval"

#: Agent names for bare builds (no discs, no W-engine, M0).
_BARE_BUILDS: dict[str, str] = {
    "jane_assault": "Jane",
    "vivian_corruption": "Vivian",
}

# Standard enemy for crossval: level 70, neutral RES.
# capacity=800 for all elements so anomalies trigger in short rotations.
_ENEMY_PARAMS = {
    "name": "CrossVal Dummy",
    "level": 70,
    "defense": 953,
    "physical_res": 0,
    "fire_res": 0,
    "ice_res": 0,
    "electric_res": 0,
    "ether_res": 0,
    "stun_dmg_taken_ratio": 5000,
    "anomaly_capacity_physical": 800,
    "anomaly_capacity_fire": 800,
    "anomaly_capacity_ice": 800,
    "anomaly_capacity_electric": 800,
    "anomaly_capacity_ether": 800,
    "anomaly_res_physical": 0,
    "anomaly_res_fire": 0,
    "anomaly_res_ice": 0,
    "anomaly_res_electric": 0,
    "anomaly_res_ether": 0,
    "anomaly_duration_default": 10.0,
}

# Fixed step lists per archetype — enough moves to trigger at least one anomaly.
# Capacity=800 → threshold=80000 bp for all elements.
# Anomaly mastery scales buildup: AM/100 factor applied per hit.
# Steps chosen to be simple (1-2 move types) for easy ZO transcription.
_STEP_LISTS: dict[str, list[str]] = {
    # Burnice fire: Direct Flame Blend = ~13504 bp/cast × 1.2 AM = ~16205/cast
    # 6 casts ≈ 97230 bp → triggers Burn around cast 5-6
    "burnice_burn": [
        "Basic Attack: Direct Flame Blend",
        "Basic Attack: Direct Flame Blend",
        "Basic Attack: Direct Flame Blend",
        "Basic Attack: Direct Flame Blend",
        "Basic Attack: Direct Flame Blend",
        "Basic Attack: Direct Flame Blend",
    ],
    # Yanagi electric: Stance: Jougen = ~33668 bp/cast × 1.14 AM = ~38381/cast
    # 3 casts ≈ 115143 bp → triggers Shock in 3rd cast
    "yanagi_shock": [
        "Stance: Jougen",
        "Stance: Jougen",
        "Stance: Jougen",
        "Stance: Jougen",
    ],
    # Jane physical: Dancing Blades = ~57296 bp/cast × 1.14 AM = ~65318/cast
    # 2 casts ≈ 130636 bp → triggers Assault in 2nd cast
    "jane_assault": [
        "Basic Attack: Dancing Blades",
        "Basic Attack: Dancing Blades",
        "Basic Attack: Dancing Blades",
    ],
    # Vivian ether: Featherbloom = 12600 bp/cast × 1.18 AM = ~14868/cast
    # 6 casts ≈ 89208 bp → triggers Corruption in 6th cast
    "vivian_corruption": [
        "Basic Attack: Featherbloom",
        "Basic Attack: Featherbloom",
        "Basic Attack: Featherbloom",
        "Basic Attack: Featherbloom",
        "Basic Attack: Featherbloom",
        "Basic Attack: Featherbloom",
        "Basic Attack: Featherbloom",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_stat_line_build(db: AsyncSession, archetype: str) -> tuple[BuildSnapshot, Agent]:
    """Snapshot whose resolved stats are the golden fixture's own `stat_line`.

    Shares its reasoning — and must stay in step — with
    `tests/integration/test_zo_crossval._load_stat_line_build`.
    """
    fixture = json.loads((_FIXTURES_DIR / f"{archetype}.json").read_text())
    stat_line, active = fixture["stat_line"], fixture["active_modifiers"]

    result = await db.execute(select(Agent).where(Agent.name == _STAT_LINE_BUILDS[archetype]))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent '{_STAT_LINE_BUILDS[archetype]}' not found in DB")

    element = str(getattr(agent.element, "value", agent.element)).lower()
    snap = BuildSnapshot(
        agent_name=agent.name,
        agent_element=element,
        agent_specialty=str(getattr(agent.specialty, "value", agent.specialty)).lower(),
        agent_level=60,
        agent_base_atk=int(stat_line["atk"]),
        agent_crit_rate=round(stat_line["crit_rate_pct"] * 100),
        agent_crit_dmg=round(stat_line["crit_dmg_pct"] * 100),
        agent_anomaly_proficiency=int(stat_line["anomaly_proficiency"]),
        agent_anomaly_mastery=int(stat_line["anomaly_mastery"]),
        agent_pen_flat=int(active.get("pen_flat", 0)),
        agent_pen_ratio=int(active.get("pen_ratio_bp", 0)),
        modifiers=[
            Modifier(
                stat=f"{element}_dmg",
                value=int(active[f"{element}_dmg_bp"]),
                source=ModifierSource.EXTERNAL,
                source_label=f"fixture:{archetype}:{element}_dmg",
                target=ModifierTarget.SELF,
                conditions=(Condition.ALWAYS,),
                scopes=(AttackScope.ALL,),
            )
        ],
    )
    return snap, agent


async def _load_bare_build(db: AsyncSession, agent_name: str) -> tuple[BuildSnapshot, Agent]:
    result = await db.execute(
        select(Agent)
        .where(Agent.name == agent_name)
        .options(
            selectinload(Agent.core_skills),
            selectinload(Agent.mindscapes),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise ValueError(f"Agent '{agent_name}' not found in DB")

    # Minimal build ORM object — no discs, no W-engine, M0, L60.
    bare = Build()
    bare.agent = agent
    bare.agent_id = agent.id
    bare.w_engine = None
    bare.w_engine_id = None
    bare.w_engine_refinement = 1
    bare.mindscape_level = 0
    bare.agent_level = 60
    bare.skill_levels = "12,12,12,12,12"
    bare.core_skill_level = 5
    bare.disabled_buffs = []
    bare.discs = []
    bare.active_conditions = []
    bare.stack_counts = {}

    snap = build_snapshot_from_db(bare, agent)
    return snap, agent


def resolve_steps(
    move_names: list[str], attacks_by_name: dict[str, list[Attack]]
) -> list[SimulatedAttackStep]:
    """Turn a step list into simulated steps the way **production** resolves them.

    A `hit_mode='sequential'` move is never bundled in production: both real resolution
    paths — `combo_step_resolver` ("Always single-tap for sequential moves — each step is
    one button press") and `optimizer_pipeline` — emit one step per press carrying one
    `Attack` row, with `hit_index` cycling. This harness bundled every row of the move
    into one step instead, so for sequential moves it validated a step shape production
    never produces, and a 5x anomaly-buildup over-count on Aria, Grace and Burnice passed
    straight through it (issue #83; the over-count itself was fixed in #79).

    One entry in the step list stays one **full cycle** of the move, so the rotation the
    fixtures were derived against is unchanged — a bundled 5-hit step and 5 single-tap
    presses are the same rotation only if the presses are all there. What changes is the
    encoding, not the rotation.

    Atomic and variant moves are still bundled: for those the resolved step legitimately
    carries every row (`MODIFIER_AUTHORING.md`, hit-mode decision tree).
    """
    steps: list[SimulatedAttackStep] = []
    for name in move_names:
        rows = attacks_by_name.get(name)
        if not rows:
            continue
        if getattr(rows[0], "hit_mode", None) == HitMode.SEQUENTIAL and len(rows) > 1:
            steps.extend(
                SimulatedAttackStep(
                    agent_id="dps", move_name=name, attacks=[row], conditions=[]
                )
                for row in rows
            )
        else:
            steps.append(
                SimulatedAttackStep(agent_id="dps", move_name=name, attacks=rows, conditions=[])
            )
    return steps


async def _load_attacks_for_moves(
    db: AsyncSession, agent: Agent, _move_names: list[str]
) -> dict[str, list[Attack]]:
    """Return a {move_name: [Attack,...]} mapping of all the agent's attacks.

    ``_move_names`` is accepted for call-site documentation/future filtering but is not
    currently used to filter the query — the caller filters the returned dict itself.
    """
    result = await db.execute(select(Attack).where(Attack.agent_id == agent.id))
    all_attacks = result.scalars().all()
    # Group by name
    by_name: dict[str, list[Attack]] = {}
    for atk in all_attacks:
        by_name.setdefault(atk.name, []).append(atk)
    # Sort each group by hit_index
    for v in by_name.values():
        v.sort(key=lambda a: a.hit_index)
    return by_name


def _format_stats(stats: TotalStats) -> dict:
    return {
        "atk": stats.atk,
        "hp": stats.hp,
        "def": stats.defense,
        "crit_rate_pct": stats.crit_rate / 100,
        "crit_dmg_pct": stats.crit_dmg / 100,
        "anomaly_proficiency": stats.anomaly_proficiency,
        "anomaly_mastery": stats.anomaly_mastery,
        "pen_flat": stats.pen_flat,
        "pen_ratio_pct": stats.pen_ratio / 100,
        "physical_dmg_pct": stats.physical_dmg / 100,
        "fire_dmg_pct": stats.fire_dmg / 100,
        "electric_dmg_pct": stats.electric_dmg / 100,
        "ether_dmg_pct": stats.ether_dmg / 100,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(archetype: str) -> None:
    """Load the archetype's build, run simulate(), and print stats/events/a fixture stub."""
    if archetype not in {**_STAT_LINE_BUILDS, **_BARE_BUILDS}:
        known = list({**_STAT_LINE_BUILDS, **_BARE_BUILDS})
        raise ValueError(f"Unknown archetype '{archetype}'. Choose from: {known}")

    async with AsyncSession(engine) as db:
        if archetype in _STAT_LINE_BUILDS:
            snap, agent = await _load_stat_line_build(db, archetype)
            build_ref = f"fixture_stat_line:{archetype}"
        else:
            snap, agent = await _load_bare_build(db, _BARE_BUILDS[archetype])
            build_ref = f"bare_build:agent={_BARE_BUILDS[archetype]},M0,L60,no_discs"

        # Resolve in-combat stats (ALWAYS + element/specialty conditions active).
        # This captures set bonuses that require these conditions (e.g. Chaos Jazz 4pc fire_dmg).
        elem = (
            agent.element.value if hasattr(agent.element, "value") else str(agent.element)
        ).lower()
        spec = (
            agent.specialty.value if hasattr(agent.specialty, "value") else str(agent.specialty)
        ).lower()
        active: set[Condition] = {Condition.ALWAYS}
        for tag in (f"equipper_is_{elem}", f"equipper_is_{spec}"):
            with __import__("contextlib").suppress(ValueError):
                active.add(Condition(tag))
        in_combat_conditions = ActiveConditions(active=active)
        stats = resolve_build_stats(snap, in_combat_conditions)

        print(f"\n=== ARCHETYPE: {archetype} ===")
        print(f"Agent:     {agent.name} (element={agent.element}, specialty={agent.specialty})")
        print(f"Build ref: {build_ref}")
        print("\n--- RESOLVED STAT LINE ---")
        stat_block = _format_stats(stats)
        for k, v in stat_block.items():
            print(f"  {k:<30} {v}")

        # Load attacks and run simulate
        move_names = _STEP_LISTS.get(archetype, [])
        if not move_names:
            print("\n(No step list defined for this archetype — skipping simulation)")
            return

        attacks_by_name = await _load_attacks_for_moves(db, agent, move_names)
        missing = [m for m in move_names if m not in attacks_by_name]
        if missing:
            print(f"\nWARNING: Moves not found in DB: {missing}")

        steps = resolve_steps(move_names, attacks_by_name)

        if not steps:
            print("\nNo steps resolved — cannot simulate.")
            return

        # Build enemy profile
        enemy = EnemyProfile(**_ENEMY_PARAMS)
        db.add(enemy)
        await db.flush()

        # Use the real curated moves_db (docs/TASKS_move_key_resolution.md Task 8) — an
        # empty dict forces the tolerant fallback path (buildup summed straight off the
        # DB Attack rows, duration approximated, no abloom/state effects), which is
        # exactly the coverage gap that let every #77 defect ship undetected: this
        # capture aid never validated an authored spec end to end. The buildup fields in
        # moves/agents/*.json ARE move totals (verified against Yanagi/Jane/Vivian/Rina,
        # Task 8 LOG) — a prior version of this comment claimed otherwise from Burnice's
        # entry, which was independently confirmed stale (fixed in the same task).
        result = simulate(
            builds={"dps": snap},
            steps=steps,
            enemy=enemy,
            moves_db=_MOVES_DB,
        )

        print(f"\n  Steps with attacks: {sum(1 for s in steps if s.attacks)}/{len(steps)}")
        for s in steps:
            print(f"    {s.move_name!r}  attacks={len(s.attacks)}")

        print("\n--- SIMULATION EVENTS ---")
        print(f"{'t':>6}  {'kind':<12}  {'element':<10}  {'damage':>10}")
        print("-" * 50)
        for ev in result.events:
            elem_str = str(ev.element.value if hasattr(ev.element, "value") else ev.element or "")
            print(f"{ev.t:6.3f}  {ev.kind:<12}  {elem_str:<10}  {ev.damage or 0:>10}")

        print("\n--- TOTALS ---")
        for k, v in result.totals.items():
            print(f"  {k:<20} {v:>12}")

        print("\n--- FIXTURE STUB ---")
        print(
            json.dumps(
                {
                    "archetype": archetype,
                    "build_ref": build_ref,
                    "zo_commit": "464e7a2",
                    "stat_line": stat_block,
                    "enemy": {k: v for k, v in _ENEMY_PARAMS.items() if k in ("level", "defense")},
                    "events": [
                        {
                            "kind": ev.kind,
                            "element": str(
                                ev.element.value
                                if hasattr(ev.element, "value")
                                else ev.element or ""
                            ),
                            "expected": ev.damage,
                            "source": "TODO_ZO_or_Leifa",
                            "tolerance_pct": 1.0,
                        }
                        for ev in result.events
                        if ev.kind in ("hit", "anomaly", "disorder", "vortex")
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump cross-validation stat line + sim events.")
    parser.add_argument(
        "--archetype",
        "-a",
        required=True,
        choices=list({**_STAT_LINE_BUILDS, **_BARE_BUILDS}),
        help="Archetype key to dump.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.archetype))
