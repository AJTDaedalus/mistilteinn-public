"""Team audit harness — does a real team behave as expected, especially on anomaly buildup?

Runs a named team through a rotation against a real enemy and reports the things a
player would notice: how fast each attribute's gauge fills, when anomalies actually
proc, whether the cadence is gated by the 3s per-attribute cooldown or by buildup
starvation, and whether Disorder fires in a dual-anomaly comp.

Buildup is the focus because it is the least directly observable part of the model:
damage numbers are visible in the timeline, but *why* an anomaly did or did not proc
is not. This instruments `calculate_buildup` to expose the gauge directly.

    cd backend
    python -m scripts.audit_team --team jane_burnice
    python -m scripts.audit_team --list
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.config import settings
from app.data.loaders.moves import load_agent_moves
from app.models.agent import Agent
from app.models.build import Build, EnemyProfile
from app.models.disc import Disc
from app.models.enums import PotentialVariant
from app.repositories.attack import AttackRepository
from app.services import anomaly_simulator as _sim
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.buff_resolver import ActiveConditions
from app.services.build_damage_service import resolve_build_stats
from app.services.modifiers import Condition
from app.services.snapshot_builder import build_snapshot_from_db

MOVES = load_agent_moves()

# Rotations use each agent's real DB move names. Kept short and repeated rather than
# "optimal" — the question is whether buildup accrues at a believable rate, not
# whether this is the highest-DPS line.
TEAMS: dict[str, dict] = {
    "jane_burnice": {
        "desc": "Jane (Physical) + Burnice (Fire) + Caesar — dual-anomaly, expect Disorder",
        "members": ["Jane", "Burnice", "Caesar"],
        "conditions": ["passion_state_active"],
        "rotation": [
            *[("Burnice", "EX Special Attack: Intense Heat Stirring Method")] * 3,
            ("Burnice", "EX Special Attack: Intense Heat Stirring Method - Double Shot"),
            ("Burnice", "Assist Follow-Up: Scorching Dew"),
            *[("Jane", "Basic Attack: Dancing Blades")] * 2,
            ("Jane", "EX Special Attack: Aerial Sweep - Clearout"),
            *[("Jane", "Basic Attack: Salchow Jump")] * 10,
            ("Jane", "EX Special Attack: Aerial Sweep - Clearout"),
            *[("Jane", "Basic Attack: Salchow Jump")] * 8,
            ("Burnice", "Assist Follow-Up: Scorching Dew"),
            *[("Burnice", "EX Special Attack: Intense Heat Stirring Method")] * 3,
        ],
    },
    "yanagi_burnice": {
        "desc": "Yanagi (Electric) + Burnice (Fire) + Astra Yao — the canonical Disorder comp",
        "members": ["Yanagi", "Burnice", "Astra Yao"],
        "conditions": [],
        "rotation": [
            *[("Burnice", "EX Special Attack: Intense Heat Stirring Method")] * 3,
            ("Burnice", "EX Special Attack: Intense Heat Stirring Method - Double Shot"),
            ("Burnice", "Assist Follow-Up: Scorching Dew"),
            *[
                ("Yanagi", "Stance: Jougen"),
                ("Yanagi", "EX Special Attack: Gekka Ruten"),
                ("Yanagi", "Stance: Kagen"),
                ("Yanagi", "EX Special Attack: Gekka Ruten"),
            ] * 4,
            ("Burnice", "Assist Follow-Up: Scorching Dew"),
            *[("Burnice", "EX Special Attack: Intense Heat Stirring Method")] * 2,
        ],
    },
    "miyabi_solo": {
        "desc": "Miyabi (Ice) + Soukaku + Caesar — mono-Ice, Shatter cadence",
        "members": ["Miyabi", "Soukaku", "Caesar"],
        "conditions": [],
        "rotation": [
            *[
                ("Miyabi", "Basic Attack: Kazahana"),
                ("Miyabi", "Basic Attack: Shimotsuki"),
                ("Miyabi", "EX Special Attack: Hisetsu"),
            ] * 7,
        ],
    },
    "vivian_yanagi": {
        "desc": "Vivian (Ether) + Yanagi (Electric) + Astra Yao — Corruption + Abloom",
        "members": ["Vivian", "Yanagi", "Astra Yao"],
        "conditions": [],
        "rotation": [
            *[("Vivian", "Basic Attack: Featherbloom"),
              ("Vivian", "EX Special Attack: Violet Requiem")] * 6,
            *[("Yanagi", "Stance: Jougen"), ("Yanagi", "EX Special Attack: Gekka Ruten")] * 3,
            *[("Vivian", "Basic Attack: Featherbloom")] * 4,
        ],
    },
}

ENEMY_NAME = "Notorious - Pompey"  # boss: 3600 physical / 3000 other anomaly capacity


async def main(team_key: str, extra_conditions: list[str] | None = None) -> int:  # noqa: PLR0915
    spec = dict(TEAMS[team_key])
    if extra_conditions:
        spec["conditions"] = [*spec["conditions"], *extra_conditions]
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        enemy = (
            await session.execute(select(EnemyProfile).where(EnemyProfile.name == ENEMY_NAME))
        ).scalars().first()
        attack_repo = AttackRepository(session)

        snaps, builds = {}, {}
        for name in spec["members"]:
            agent = (
                await session.execute(select(Agent).where(Agent.name == name))
            ).scalars().first()
            # Same eager-load set BuildRepository uses — build_snapshot_from_db walks
            # w_engine, discs (+ their sets) and the agent's core skills / mindscapes,
            # and an async session cannot lazy-load them mid-call.
            build = (
                await session.execute(
                    select(Build)
                    .where(Build.agent_id == agent.id)
                    .options(
                        selectinload(Build.discs).selectinload(Disc.disc_set),
                        selectinload(Build.agent).selectinload(Agent.core_skills),
                        selectinload(Build.agent).selectinload(Agent.mindscapes),
                        selectinload(Build.w_engine),
                    )
                )
            ).scalars().first()
            if build is None:
                print(f"  !! no build for {name} — skipping team")
                return 2
            builds[name] = build
            snaps[name] = build_snapshot_from_db(build, build.agent, support_builds=[])

        print(f"=== {team_key}: {spec['desc']} ===")
        print(f"enemy: {enemy.name} (lv{enemy.level}, phys cap {enemy.anomaly_capacity_physical}, "
              f"fire cap {enemy.anomaly_capacity_fire})")
        for name in spec["members"]:
            st = resolve_build_stats(snaps[name], ActiveConditions(active={Condition.ALWAYS}))
            print(f"  {name:12s} M{builds[name].mindscape_level}  ATK {st.atk:5d}  "
                  f"AP {st.anomaly_proficiency:4d}  AM {st.anomaly_mastery:4d}")

        steps = []
        step_buildup_by_move: dict[tuple[str, str], int] = {}
        step_element_by_move: dict[tuple[str, str], str] = {}
        for agent_name, move in spec["rotation"]:
            build = builds[agent_name]
            rows = await attack_repo.get_by_agent_and_name(
                build.agent_id,
                move,
                PotentialVariant.for_rank(build.potential_rank),
            )
            if not rows:
                print(f"  !! move not found: {agent_name} / {move}")
            step_buildup_by_move[(agent_name, move)] = sum(r.anomaly_buildup for r in rows)
            if rows:
                step_element_by_move[(agent_name, move)] = rows[0].element
            steps.append(
                SimulatedAttackStep(
                    agent_id=agent_name,
                    move_name=move,
                    attacks=list(rows),
                    conditions=list(spec["conditions"]),
                )
            )

    await engine.dispose()

    # Instrument the gauge so buildup is observable, not merely inferred.
    trace: list[tuple[int, int]] = []
    original = _sim.calculate_buildup

    def spy(**kw):
        applied = original(**kw)
        trace.append((kw["move_buildup"], applied))
        return applied

    _sim.calculate_buildup = spy
    try:
        result = simulate(snaps, steps, enemy, MOVES)
    finally:
        _sim.calculate_buildup = original

    # Independent projection of each attribute's gauge, computed from the DB rows and
    # the curated move specs rather than read back out of the engine. If this disagrees
    # with the engine's proc timing, that disagreement is itself the finding.
    print("\n--- gauge projection (independent of the engine) ---")
    thresholds = {
        el: getattr(enemy, f"anomaly_capacity_{el}", 100) * 100
        for el in ("physical", "fire", "ice", "electric", "ether", "wind")
    }
    accrued: dict[str, float] = defaultdict(float)
    for agent_name, move in spec["rotation"]:
        snap = snaps[agent_name]
        st = resolve_build_stats(snap, ActiveConditions(active={Condition.ALWAYS}))
        agent_key = snap.agent_name.lower().replace(" ", "_").replace("-", "").replace("&", "")
        move_spec = (MOVES.get(agent_key).moves.get(move)) if MOVES.get(agent_key) else None
        rows = [r for r in ()]  # placeholder, filled below
        buildup = getattr(move_spec, "buildup", None)
        element = getattr(move_spec, "element", None) or snap.agent_element
        if buildup is None:
            buildup = step_buildup_by_move.get((agent_name, move), 0)
            element = step_element_by_move.get((agent_name, move), element)
        accrued[element] += buildup * st.anomaly_mastery / 100
    for el, total in sorted(accrued.items()):
        thr = thresholds.get(el, 10000)
        pct = total / thr * 100 if thr else 0
        verdict = "PROCS" if total >= thr else "STARVED"
        print(f"  {el:9s} accrued {total:10.0f} / threshold {thr:7d}  = {pct:5.1f}%  {verdict}")

    procs = defaultdict(list)
    for e in result.events:
        if e.kind in {"anomaly", "refresh"}:
            procs[e.element].append(e.t)
    disorders = [e for e in result.events if e.kind == "disorder"]
    vortices = [e for e in result.events if e.kind == "vortex"]
    ticks = [e for e in result.events if e.kind == "anomaly_tick"]
    end_t = max((e.t for e in result.events), default=0.0)

    print(f"\n--- anomaly buildup over {end_t:.1f}s ---")
    if not procs:
        print("  NO ANOMALY PROCS AT ALL")
    for element, times in sorted(procs.items()):
        gaps = [round(b - a, 2) for a, b in zip(times, times[1:], strict=False)]
        rate = len(times) / end_t * 60 if end_t else 0
        print(f"  {element:9s} procs={len(times):2d}  first={times[0]:5.2f}s  "
              f"gaps={gaps if gaps else '—'}  ({rate:.1f}/min)")
        if gaps and min(gaps) < 3.0:  # noqa: PLR2004
            print(f"    !! gap {min(gaps)}s is under the 3s per-attribute cooldown")
    print(f"  anomaly ticks={len(ticks)}  disorder={len(disorders)}  vortex={len(vortices)}")
    print(f"  buildup applications: {len(trace)}  "
          f"(median applied {sorted(a for _, a in trace)[len(trace) // 2] if trace else 0})")
    print(f"  totals: { {k: v for k, v in result.totals.items() if v} }")
    if result.warnings:
        print(f"  warnings ({len(result.warnings)}):")
        for w in dict.fromkeys(result.warnings):
            print(f"    - {w[:110]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", help="team key")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--conditions", default="", help="extra run-level conditions, comma-separated")
    args = parser.parse_args()
    if args.list:
        for k, v in TEAMS.items():
            print(f"{k:16s} {v['desc']}")
        sys.exit(0)
    keys = list(TEAMS) if args.all else [args.team]
    rc = 0
    for k in keys:
        rc |= asyncio.run(main(k, [c for c in args.conditions.split(",") if c]))
        print()
    sys.exit(rc)
