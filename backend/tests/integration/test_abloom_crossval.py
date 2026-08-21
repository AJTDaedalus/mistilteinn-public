"""Task A7 — Abloom cross-validation + additivity regression.

ZO cross-reference is unavailable (ZO repo 464e7a2 contains only a README).
Per-event formula correctness is verified by checking that each abloom event
satisfies the identity stored in its own detail fields:

    damage == original_anomaly_dmg * abloom_mv_bp * ap // 100_000
               * abloom_boost_mult // 10_000

Additivity regression checks that C4 holds: Abloom must not fire when no aura
is active, and agents without abloom_mv_by_element never produce abloom events.

Requires the SEEDED PRODUCTION DB (not the isolated test DB). Run manually:
    docker compose exec backend python -m pytest tests/integration/test_abloom_crossval.py -v

Skips automatically when the seeded data is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.data.loaders.moves import load_agent_moves
from app.database import engine as _app_engine
from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.snapshot_builder import build_snapshot_from_db

pytestmark = pytest.mark.asyncio

_MOVES_DB = load_agent_moves()

_CROSSVAL_FIXTURES = Path(__file__).parent / "fixtures" / "zo_crossval"


def _crossval_expected(archetype: str, kind: str, element: str, ordinal: int) -> int:
    """Expected damage for one event in a zo_crossval fixture.

    Shared with test_zo_crossval so the two suites cannot disagree about the
    same golden value.
    """
    fixture = json.loads((_CROSSVAL_FIXTURES / f"{archetype}.json").read_text())
    for event in fixture["events"]:
        if (event["kind"], event["element"], event["ordinal"]) == (kind, element, ordinal):
            return int(event["expected"])
    raise AssertionError(f"No ({kind}, {element})[{ordinal}] event in {archetype}.json")


_VIVIAN_STEPS = ["Basic Attack: Featherbloom"] * 7
_JANE_STEPS = ["Basic Attack: Dancing Blades"] * 5

# Standard enemy — same as test_zo_crossval so fixtures are comparable.
_ENEMY_NORMAL: dict = {
    "name": "Abloom CrossVal Dummy",
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

# Enemy with huge ether capacity so the Corruption aura never fires.
_ENEMY_INFINITE_ETHER_CAP: dict = {
    **_ENEMY_NORMAL,
    "name": "Abloom CrossVal NoAura Dummy",
    "anomaly_capacity_ether": 999_999_999,
}


async def _bare_build_snap(db: AsyncSession, agent_name: str):
    result = await db.execute(
        select(Agent)
        .where(Agent.name == agent_name)
        .options(
            selectinload(Agent.core_skills),
            selectinload(Agent.mindscapes),
        )
    )
    agent = result.scalar_one_or_none()
    assert agent is not None, f"Agent '{agent_name}' not found in seeded DB"

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


async def _resolve_steps(
    db: AsyncSession, agent: Agent, move_names: list[str]
) -> list[SimulatedAttackStep]:
    result = await db.execute(select(Attack).where(Attack.agent_id == agent.id))
    all_attacks = result.scalars().all()
    by_name: dict[str, list] = {}
    for atk in all_attacks:
        by_name.setdefault(atk.name, []).append(atk)
    for v in by_name.values():
        v.sort(key=lambda a: a.hit_index)
    return [
        SimulatedAttackStep(
            agent_id="dps",
            move_name=name,
            attacks=by_name.get(name, []),
            conditions=[],
        )
        for name in move_names
        if name in by_name
    ]


async def _resolve_single_tap_steps(
    db: AsyncSession, agent: Agent, move_name: str, count: int
) -> list[SimulatedAttackStep]:
    """Steps for *count* single-tap presses of a sequential move, cycling hit_index.

    Unlike `_resolve_steps` (which bundles every Attack row for the move into each
    step — a "full-chain" press), this models `hit_mode='sequential'` combo_step_resolver
    behavior: each press is its own step carrying exactly one Attack row, and hit_index
    cycles back to 0 after a full pass. This is the rigorous shape for testing
    "abloom must bind to the final hit only" — a bundled step already ends on the last
    hit_index by construction, so it can't distinguish a real per-hit gate from no gate
    at all.
    """
    result = await db.execute(
        select(Attack)
        .where(Attack.agent_id == agent.id, Attack.name == move_name)
        .order_by(Attack.hit_index)
    )
    attacks = list(result.scalars().all())
    assert attacks, f"No '{move_name}' rows found for {agent.name}"
    return [
        SimulatedAttackStep(
            agent_id="dps",
            move_name=move_name,
            attacks=[attacks[i % len(attacks)]],
            conditions=[],
        )
        for i in range(count)
    ]


@pytest.fixture
async def app_db():
    """AsyncSession on the seeded app DB; skips if not reachable or empty."""
    try:
        async with AsyncSession(_app_engine) as session:
            result = await session.execute(select(Agent).limit(1))
            if result.scalar_one_or_none() is None:
                pytest.skip("App DB has no agents — seeded DB required for abloom crossval")
            yield session
    except Exception as exc:
        pytest.skip(f"App DB not reachable for abloom crossval: {exc}")


class TestAbloomCrossval:
    async def test_vivian_abloom_formula_per_event(self, app_db: AsyncSession) -> None:
        """Every abloom event must satisfy the Abloom formula identity.

        Derived from LOG_abloom.md A1 (game text, agent_kit_atlas.json:4160):
            damage = original_anomaly_dmg * abloom_mv_bp * ap // 100_000
                     * abloom_boost_mult // 10_000

        With bare Vivian M0 L60 (AP=108, Ether MV=615bp), 7 Featherbloom steps
        against a standard enemy will fire at least one Corruption aura and
        produce abloom events on subsequent steps while the aura is active.

        Also asserts the Vivian Ether MV is 615bp (6.15%/10AP) per A1.
        """
        snap, agent = await _bare_build_snap(app_db, "Vivian")
        steps = await _resolve_steps(app_db, agent, _VIVIAN_STEPS)
        assert steps, "No Featherbloom steps resolved for Vivian"

        enemy = EnemyProfile(**_ENEMY_NORMAL)
        app_db.add(enemy)
        await app_db.flush()

        sim = simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)

        abloom_events = [e for e in sim.events if e.kind == "abloom"]
        assert abloom_events, (
            "Expected ≥1 abloom event from Vivian vs live Corruption aura "
            "within 7 Featherbloom steps; check abloom_mv_by_element and aura threshold"
        )

        for ev in abloom_events:
            d = ev.detail
            orig = d["original_anomaly_dmg"]
            mv_bp = d["abloom_mv_bp"]
            ap = d["ap"]
            boost = d["abloom_boost_mult"]

            expected_base = orig * mv_bp * ap // 100_000
            expected_total = expected_base * boost // 10_000

            assert ev.damage == expected_total, (
                f"Abloom formula mismatch: orig={orig} mv_bp={mv_bp} ap={ap} "
                f"boost={boost} → expected={expected_total}, got={ev.damage}"
            )
            assert str(ev.element) == "ether", (
                f"Vivian bare build should trigger Ether Abloom; got element={ev.element}"
            )
            assert mv_bp == 615, (
                f"Vivian Ether MV should be 615bp (6.15%/10AP, agent_kit_atlas.json:4160); "
                f"got {mv_bp}"
            )

        assert sim.totals["abloom"] == sum(e.damage or 0 for e in abloom_events)

    async def test_additivity_no_aura(self, app_db: AsyncSession) -> None:
        """Vivian on an enemy with infinite ether capacity fires no abloom.

        C4: Abloom must not fire when no aura is active. The abloom total must
        be zero and the standard + anomaly totals must be unaffected.
        """
        snap, agent = await _bare_build_snap(app_db, "Vivian")
        steps = await _resolve_steps(app_db, agent, _VIVIAN_STEPS)
        assert steps

        enemy = EnemyProfile(**_ENEMY_INFINITE_ETHER_CAP)
        app_db.add(enemy)
        await app_db.flush()

        sim = simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)

        abloom_events = [e for e in sim.events if e.kind == "abloom"]
        assert abloom_events == [], (
            f"Expected zero abloom events when no Corruption aura can fire; "
            f"got {len(abloom_events)} events"
        )
        assert sim.totals.get("abloom", 0) == 0

    async def test_additivity_non_abloom_agent(self, app_db: AsyncSession) -> None:
        """Jane (no abloom flag on any move) vs standard enemy fires no abloom.

        C4 from the agent side: agents without abloom_mv_by_element must never
        produce abloom events regardless of enemy state.
        """
        snap, agent = await _bare_build_snap(app_db, "Jane")
        steps = await _resolve_steps(app_db, agent, _JANE_STEPS)
        assert steps, "No Dancing Blades steps resolved for Jane"

        enemy = EnemyProfile(**_ENEMY_NORMAL)
        app_db.add(enemy)
        await app_db.flush()

        sim = simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)

        abloom_events = [e for e in sim.events if e.kind == "abloom"]
        assert abloom_events == [], (
            f"Jane has no abloom moves; expected zero abloom events, got {len(abloom_events)}"
        )
        assert sim.totals.get("abloom", 0) == 0

    async def test_additivity_standard_hit_dmg_unchanged(self, app_db: AsyncSession) -> None:
        """Vivian's first Featherbloom hit matches the pre-Abloom golden value.

        Abloom is additive — it must not change existing hit damage paths.
        The expected value is read from the crossval fixture rather than
        duplicated here, so the two cannot drift apart when the fixture is
        re-derived (they did: the fixture moved to 197 with the core-flat-ATK
        fold while this test still hardcoded the old 180).
        Source: tests/integration/fixtures/zo_crossval/vivian_corruption.json,
                formula_derived.
        """
        snap, agent = await _bare_build_snap(app_db, "Vivian")
        steps = await _resolve_steps(app_db, agent, _VIVIAN_STEPS)
        assert steps

        enemy = EnemyProfile(**_ENEMY_NORMAL)
        app_db.add(enemy)
        await app_db.flush()

        sim = simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)

        hit_events = [e for e in sim.events if e.kind == "hit" and str(e.element or "") == "ether"]
        assert hit_events, "Expected ether hit events from Vivian Featherbloom"

        first_hit = hit_events[0].damage
        assert first_hit is not None
        expected = _crossval_expected("vivian_corruption", "hit", "ether", 0)
        delta_pct = abs(first_hit - expected) / expected * 100
        assert delta_pct <= 1.0, (
            f"First Featherbloom hit: expected ~{expected}, got {first_hit} "
            f"(delta={delta_pct:.2f}%); Abloom branch may have changed hit DMG"
        )


class TestAriaAbloom:
    """Task 4, docs/TASKS_move_key_resolution.md — Aria's Abloom restored (OQ-1 (a)).

    'Basic Attack: Perfect Pitch' now resolves (was dead: keyed with a '(Level 3)'
    suffix no DB row carries). These tests are the crossval evidence the task's
    acceptance criteria ask for: non-zero abloom from real moves_db, and — the
    load-bearing part — exactly once per combo cycle, not once per hit.
    """

    async def test_aria_abloom_nonzero_with_real_moves_db(self, app_db: AsyncSession) -> None:
        """Aria's own Perfect Pitch combo builds an Ether aura and then Abloom fires.

        Using the real seeded `moves_db` (not a synthetic spec) — this is the
        end-to-end path the pre-fix dead key silently skipped for months (see
        test_anomaly_simulator.py's synthetic Aria test, which never loaded
        aria.json at all).

        Two cycles, not one: a bare Aria spends the whole first cycle building the
        Ether gauge to its Corruption threshold, so no aura is active at the start of
        cycle 1's final hit and the first Abloom lands on cycle 2's. (Re-derived after
        the whole-cycle buildup divisor fix — a single cycle sufficed only while a
        single-tap press was crediting 5x its real gauge.)
        """
        snap, agent = await _bare_build_snap(app_db, "Aria")
        steps = await _resolve_single_tap_steps(
            app_db, agent, "Basic Attack: Perfect Pitch", count=10
        )

        enemy = EnemyProfile(**_ENEMY_NORMAL)
        app_db.add(enemy)
        await app_db.flush()

        sim = simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)

        abloom_events = [e for e in sim.events if e.kind == "abloom"]
        assert abloom_events, (
            "Expected >=1 abloom event from two full 5-press Perfect Pitch cycles; "
            "check requires_charge_level gating and the move's buildup value"
        )
        assert sim.totals["abloom"] > 0
        for ev in abloom_events:
            assert str(ev.element) == "ether"

    async def test_aria_abloom_fires_exactly_once_per_cycle_not_per_hit(
        self, app_db: AsyncSession
    ) -> None:
        """The load-bearing assertion: 3 cycles (15 single-tap presses) -> 2 events.

        Cycle 1 is spent ramping the Ether gauge (see the test above), so the aura is
        only live for cycles 2 and 3 — one Abloom each, exactly 5 presses apart. Keying
        the plain DB name without the final-hit gate instead fires on every press that
        has an aura up, roughly 5x this count — over-crediting Aria worse than the
        pre-fix zero, because it errs in the flattering direction (DESIGN §5).
        """
        snap, agent = await _bare_build_snap(app_db, "Aria")
        steps = await _resolve_single_tap_steps(
            app_db, agent, "Basic Attack: Perfect Pitch", count=15
        )

        enemy = EnemyProfile(**_ENEMY_NORMAL)
        app_db.add(enemy)
        await app_db.flush()

        sim = simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)

        abloom_events = [e for e in sim.events if e.kind == "abloom"]
        assert len(abloom_events) == 2, (
            f"Expected exactly 1 abloom event per aura-live 5-hit cycle (cycles 2-3 of "
            f"15 presses); got {len(abloom_events)}. Firing more than once per cycle "
            f"means the final-hit gate (requires_charge_level) isn't restricting to "
            f"the last hit_index of the sequential combo."
        )

        # Each Abloom lands on a cycle boundary, 5 presses apart — the positive
        # statement of the gate, not just a count.
        #
        # 2.4s and 3.6s, i.e. exactly one 1.2s cycle apart. These were 12.0 and 18.0
        # while `duration_s` was charged in full on every single-tap press, which made
        # one press of Perfect Pitch cost the whole 5-hit chain's 1.2s and stretched 15
        # presses across 18s (issue #83). `duration_s` is authored per *move*, so a
        # press costs 1.2/5 = 0.24s and a cycle costs 1.2s — the number the surrounding
        # comment always claimed. The gate itself is unchanged: still 2 events, still
        # one per aura-live cycle.
        assert [round(e.t, 1) for e in abloom_events] == [2.4, 3.6]

    # L4 no longer flagging aria.json is verified by
    # tests/integration/test_move_key_resolution.py (the L4 harness's own test) and by
    # the retired known_issues.json waiver, not here — check_l4() manages its own
    # asyncio.run() internally, which cannot be called from this file's already-running
    # pytest-asyncio event loop (every test here is `async def`).
