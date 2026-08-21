"""Task 16c/16d — ZO cross-validation gate.

For each archetype fixture, constructs the build — bare (agent base stats only) or
reconstructed from the fixture's own `stat_line` — runs simulate() with a fixed step
list, then matches simulated events to golden events by (kind, element, ordinal) and
asserts per-event delta ≤ tolerance_pct.

No archetype loads a build by UUID any more. Two used to, and those rows lived in one
developer's database and were never checked in, so those two tests skipped for everyone
and failed for everyone under `CROSSVAL_REQUIRE_DB=1` — see `_load_stat_line_build`.

Reference provenance per fixture event:
  - "formula_derived": independently derived from game formulas (CLAUDE.md,
    Leifa references). ZO repo 464e7a2 contains only a README; no ZO UI
    capture was performed. Formula derivations are documented in the fixture.
  - "Leifa": proc counts and aggregate totals from
    references/DMG Formula for Anomaly, Disorder and Vortex Leifa.html.

These tests require the SEEDED PRODUCTION DB (not the test DB). They are
designed to be run manually with:
  docker compose exec backend python -m pytest tests/integration/test_zo_crossval.py -v

They skip automatically when the seeded data is absent (regular CI with
the isolated test DB). This is the documented "Requires Docker + seeded DB"
contract in TASKS_anomaly_fixes.md Task 16.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import engine as _app_engine
from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import build_snapshot_from_db
from scripts.dump_crossval import resolve_steps

pytestmark = pytest.mark.asyncio

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "zo_crossval"


def _load_fixture(archetype: str) -> dict:
    return json.loads((_FIXTURES_DIR / f"{archetype}.json").read_text())

# A skip is not a pass. This suite is the damage chain's only golden-fixture
# regression detector, and because it needs the seeded DB it skips on every CI run —
# so it sat green-by-absence while #145 changed anomaly proc counts out from under
# `jane_assault`, and nobody found out until the audit ran it by hand.
#
# Set CROSSVAL_REQUIRE_DB=1 to turn every "seeded DB required" skip into a failure.
# That is what makes an operator's run *prove* something, exactly as
# `validate_kits --require-db` does for L4/L5 (CLAUDE.md's Half 2 rule).
_REQUIRE_DB = bool(os.environ.get("CROSSVAL_REQUIRE_DB"))


def _skip_or_fail(reason: str) -> None:
    """Skip normally; fail loudly under CROSSVAL_REQUIRE_DB."""
    if _REQUIRE_DB:
        pytest.fail(f"CROSSVAL_REQUIRE_DB is set but the data is missing: {reason}")
    pytest.skip(reason)

# Fixed step lists per archetype (mirrors dump_crossval.py).
_STEP_LISTS: dict[str, list[str]] = {
    "burnice_burn": ["Basic Attack: Direct Flame Blend"] * 6,
    "yanagi_shock": ["Stance: Jougen"] * 4,
    "jane_assault": ["Basic Attack: Dancing Blades"] * 3,
    "vivian_corruption": ["Basic Attack: Featherbloom"] * 7,
    # trigger_aftershock uses a two-agent setup (see _run_trigger_archetype)
}

# Archetypes whose build is reconstructed from the fixture's own `stat_line` rather than
# loaded from the DB. These two used to name build UUIDs (`019e7ade`, `019e673e`) that
# existed in exactly one developer's database and were never checked in — see
# `_load_stat_line_build` for why reconstructing is not a downgrade.
_STAT_LINE_BUILDS: dict[str, str] = {
    "burnice_burn": "Burnice",
    "yanagi_shock": "Yanagi",
}

# Agent names for bare-build archetypes.
_BARE_BUILDS: dict[str, str] = {
    "jane_assault": "Jane",
    "vivian_corruption": "Vivian",
}

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


async def _load_stat_line_build(db: AsyncSession, archetype: str):
    """Build a snapshot whose resolved stats **are** the fixture's own `stat_line`.

    These two archetypes used to load a DB build by UUID (`019e7ade`, `019e673e`). Those
    rows were one developer's and were never checked in, so no other database has ever
    had them: the two tests skipped everywhere, and under `CROSSVAL_REQUIRE_DB=1` — the
    mode CLAUDE.md tells a reviewer to run before merging any damage-chain change — they
    *failed*, every run, for a reason nobody could fix. Two permanently-red tests teach
    reviewers to skim the output of the suite whose entire job is to be read.

    Reconstructing them from the fixture is not a downgrade in what is actually checked.
    Every golden event here is `source: "formula_derived"`, and every one of those
    formulas starts from the recorded stat line — `base=floor(2597*8990/10000)` — never
    from the build. The stat line *is* the oracle; the build was one (unverifiable) way
    of producing it, and it produced it wrongly at least once: `_atk_note` records ATK
    being corrected 4651 → 3603 and 2480 → 2597 after the fixtures were first frozen.

    What is genuinely lost is the build → stats half: that a Timeweaver R1 with those
    discs really resolves to ATK 3603. Nobody could run that check anyway, and
    `test_build_damage_service` covers snapshot resolution against builds that exist.
    """
    fixture = _load_fixture(archetype)
    stat_line = fixture["stat_line"]
    active = fixture["active_modifiers"]
    agent_name = _STAT_LINE_BUILDS[archetype]

    result = await db.execute(select(Agent).where(Agent.name == agent_name))
    agent = result.scalar_one_or_none()
    if agent is None:
        _skip_or_fail(f"Seeded DB has no agent '{agent_name}' — seeded DB required")

    element = str(getattr(agent.element, "value", agent.element)).lower()
    # Only the modifiers the fixture itself declares active. Its `active_modifiers` block
    # is an enumeration, not a sample — it says in prose which kit rows are live in this
    # rotation and which are (correctly) inactive, e.g. Yanagi's `Core: Electric DMG`
    # being re-gated to `after_ex_hit`, which this EX-free rotation never triggers.
    modifiers = [
        Modifier(
            stat=f"{element}_dmg",
            value=int(active[f"{element}_dmg_bp"]),
            source=ModifierSource.EXTERNAL,
            source_label=f"fixture:{archetype}:{element}_dmg",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
        )
    ]

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
        # PEN comes from `active_modifiers`, which is authoritative where the two
        # disagree: Yanagi's Kagen-stance 10% PEN Ratio is in the modifiers and in every
        # golden `def_area`, and was simply missing from its `stat_line` (fixed in the
        # same change that added this loader — def_area 551 only reproduces at 10%).
        agent_pen_flat=int(active.get("pen_flat", 0)),
        agent_pen_ratio=int(active.get("pen_ratio_bp", 0)),
        modifiers=modifiers,
    )
    return snap, agent


async def _load_bare_build(db: AsyncSession, agent_name: str):
    result = await db.execute(
        select(Agent)
        .where(Agent.name == agent_name)
        .options(
            selectinload(Agent.core_skills),
            selectinload(Agent.mindscapes),
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        # Same contract as `_load_real_build`. The `app_db` fixture only probes that
        # *some* agent exists, so a partially-seeded DB reaches here.
        _skip_or_fail(f"Seeded DB has no agent '{agent_name}' — seeded DB required")

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


async def _run_archetype(db: AsyncSession, archetype: str):
    """Load build, run sim, return (events, sim_result)."""
    from app.api.v1.simulate import _MOVES_DB

    if archetype in _STAT_LINE_BUILDS:
        snap, agent = await _load_stat_line_build(db, archetype)
    else:
        snap, agent = await _load_bare_build(db, _BARE_BUILDS[archetype])

    move_names = _STEP_LISTS[archetype]
    result = await db.execute(select(Attack).where(Attack.agent_id == agent.id))
    all_attacks = result.scalars().all()
    by_name: dict[str, list] = {}
    for atk in all_attacks:
        by_name.setdefault(atk.name, []).append(atk)
    for v in by_name.values():
        v.sort(key=lambda a: a.hit_index)

    # Resolved the way production resolves — sequential moves single-tap, one step per
    # press — rather than bundling every row of a move into one step (issue #83). Shared
    # with the capture aid so the fixtures and the harness that produced them cannot
    # drift into different step shapes.
    steps = resolve_steps(move_names, by_name)
    assert steps, f"No steps resolved for {archetype}"

    enemy = EnemyProfile(**_ENEMY_PARAMS)
    db.add(enemy)
    await db.flush()

    return simulate(builds={"dps": snap}, steps=steps, enemy=enemy, moves_db=_MOVES_DB)


async def _run_pulchra_archetype(db: AsyncSession):
    """Pulchra off-field repeat-chain: Pulchra chain (grants gait 6s) → Burnice 1 EX → 6 procs.

    Pulchra chain grants Hunter's Gait at t_start=0 (expires t=6.0).
    Switch +1s → Burnice EX t_start=3.0 with 6 hits over 2.5s (t_hit=3.4..5.5, all < 6.0).
    react_scopes=['special','ex_special'], cap=1+5=6 → 6 procs expected.
    """
    from app.api.v1.simulate import _MOVES_DB

    pulchra_snap, pulchra_agent = await _load_bare_build(db, "Pulchra")
    burnice_snap, burnice_agent = await _load_bare_build(db, "Burnice")

    result = await db.execute(select(Attack).where(Attack.agent_id == pulchra_agent.id))
    pulchra_attacks = result.scalars().all()
    pulchra_by_name: dict[str, list] = {}
    for atk in pulchra_attacks:
        pulchra_by_name.setdefault(atk.name, []).append(atk)
    for v in pulchra_by_name.values():
        v.sort(key=lambda a: a.hit_index)

    chain_move = "Chain Attack: Hey, Didn't Expect That, Right?"
    if chain_move not in pulchra_by_name:
        _skip_or_fail(f"Seeded DB has no '{chain_move}' for Pulchra — seeded DB required")

    result = await db.execute(select(Attack).where(Attack.agent_id == burnice_agent.id))
    burnice_attacks = result.scalars().all()
    burnice_by_name: dict[str, list] = {}
    for atk in burnice_attacks:
        burnice_by_name.setdefault(atk.name, []).append(atk)
    for v in burnice_by_name.values():
        v.sort(key=lambda a: a.hit_index)

    ex_move = "EX Special Attack: Intense Heat Stirring Method"
    if ex_move not in burnice_by_name:
        _skip_or_fail(f"Seeded DB has no '{ex_move}' for Burnice — seeded DB required")

    steps = [
        SimulatedAttackStep(
            agent_id="pulchra",
            move_name=chain_move,
            attacks=pulchra_by_name[chain_move],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="burnice",
            move_name=ex_move,
            attacks=burnice_by_name[ex_move],
            conditions=[],
        ),
    ]

    enemy = EnemyProfile(**_ENEMY_PARAMS)
    db.add(enemy)
    await db.flush()

    return simulate(
        builds={"pulchra": pulchra_snap, "burnice": burnice_snap},
        steps=steps,
        enemy=enemy,
        moves_db=_MOVES_DB,
    )


async def _run_anby_retag_archetype(db: AsyncSession):
    """Anby on-field Chain re-tag: Chain Attack counted in totals['aftershock']."""
    from app.api.v1.simulate import _MOVES_DB

    anby_snap, anby_agent = await _load_bare_build(db, "Soldier 0 - Anby")

    result = await db.execute(select(Attack).where(Attack.agent_id == anby_agent.id))
    all_attacks = result.scalars().all()
    by_name: dict[str, list] = {}
    for atk in all_attacks:
        by_name.setdefault(atk.name, []).append(atk)
    for v in by_name.values():
        v.sort(key=lambda a: a.hit_index)

    chain_move = "Chain Attack: Leaping Thunderstrike"
    if chain_move not in by_name:
        _skip_or_fail(f"Seeded DB has no '{chain_move}' for Soldier 0 - Anby — seeded DB required")

    steps = [
        SimulatedAttackStep(
            agent_id="anby",
            move_name=chain_move,
            attacks=by_name[chain_move],
            conditions=[],
        )
    ]

    enemy = EnemyProfile(**_ENEMY_PARAMS)
    db.add(enemy)
    await db.flush()

    return simulate(
        builds={"anby": anby_snap},
        steps=steps,
        enemy=enemy,
        moves_db=_MOVES_DB,
    )


async def _run_trigger_archetype(db: AsyncSession):
    """Load bare Burnice + bare Trigger; run 4 Burnice EX Specials; return sim result.

    Trigger is off-field throughout (never acting agent).  The 3s CD + 2/20s window gates
    allow exactly 2 procs out of 4 qualifying hits (see trigger_aftershock.json timing notes).
    _MOVES_DB is loaded from files at startup — trigger.json aftershock spec is always present.
    """
    from app.api.v1.simulate import _MOVES_DB

    burnice_snap, burnice_agent = await _load_bare_build(db, "Burnice")
    trigger_snap, _ = await _load_bare_build(db, "Trigger")

    result = await db.execute(select(Attack).where(Attack.agent_id == burnice_agent.id))
    all_attacks = result.scalars().all()
    by_name: dict[str, list] = {}
    for atk in all_attacks:
        by_name.setdefault(atk.name, []).append(atk)
    for v in by_name.values():
        v.sort(key=lambda a: a.hit_index)

    ex_move = "EX Special Attack: Intense Heat Stirring Method"
    if ex_move not in by_name:
        _skip_or_fail(f"Seeded DB has no '{ex_move}' for Burnice — seeded DB required")

    steps = [
        SimulatedAttackStep(
            agent_id="burnice",
            move_name=ex_move,
            attacks=by_name[ex_move],
            conditions=[],
        )
    ] * 4

    enemy = EnemyProfile(**_ENEMY_PARAMS)
    db.add(enemy)
    await db.flush()

    return simulate(
        builds={"burnice": burnice_snap, "trigger": trigger_snap},
        steps=steps,
        enemy=enemy,
        moves_db=_MOVES_DB,
    )


def _check_aftershock_procs(fixture: dict, sim_result) -> None:
    """Validate aftershock proc count and liveness against fixture."""
    apc = fixture.get("aftershock_proc_counts", {})
    if not apc:
        return
    aftershock_events = [ev for ev in sim_result.events if ev.kind == "aftershock"]
    total_procs = len(aftershock_events)
    total_dmg = sum(ev.damage or 0 for ev in aftershock_events)
    for name, spec in apc.items():
        expected_procs = spec["expected_procs"]
        assert total_procs == expected_procs, (
            f"{name}: expected {expected_procs} aftershock procs, got {total_procs}"
        )
        min_total = spec.get("min_total", 0)
        if min_total > 0:
            assert total_dmg >= min_total, (
                f"{name}: aftershock total {total_dmg} < min_total {min_total}"
            )


def _group_events(sim_result) -> dict[tuple[str, str], list]:
    """Group sim events by (kind, element), preserving order."""
    groups: dict[tuple[str, str], list] = {}
    for ev in sim_result.events:
        if ev.kind not in ("hit", "anomaly_tick"):
            continue
        elem = str(ev.element.value if hasattr(ev.element, "value") else ev.element or "")
        key = (ev.kind, elem)
        groups.setdefault(key, []).append(ev)
    return groups


def _check_event(golden: dict, sim_events: dict[tuple[str, str], list]) -> None:
    """Assert one golden event against the sim."""
    kind = golden["kind"]
    element = golden["element"]
    ordinal = golden["ordinal"]
    expected = golden["expected"]
    tolerance_pct = golden.get("tolerance_pct", 1.0)

    key = (kind, element)
    group = sim_events.get(key, [])
    assert ordinal < len(group), (
        f"Sim has only {len(group)} events for ({kind}, {element}); "
        f"golden expects ordinal={ordinal}"
    )
    sim_val = group[ordinal].damage
    assert sim_val is not None, f"Sim event ({kind}, {element})[{ordinal}] has no damage"

    if expected == 0:
        assert sim_val == 0, f"Expected near-zero for ({kind},{element})[{ordinal}], got {sim_val}"
        return

    delta_pct = abs(sim_val - expected) / expected * 100
    assert delta_pct <= tolerance_pct, (
        f"({kind}, {element})[{ordinal}]: sim={sim_val}, expected={expected}, "
        f"delta={delta_pct:.2f}% > tolerance={tolerance_pct}%"
    )


def _check_proc_counts(fixture: dict, sim_result) -> None:
    """Validate anomaly proc counts and totals against Leifa-sourced fixture."""
    pc = fixture.get("proc_counts", {})
    for anomaly_name, spec in pc.items():
        expected_procs = spec["expected_procs"]
        expected_total = spec["expected_total"]
        # Determine element from archetype
        archetype = fixture["archetype"]
        element_map = {
            "jane_assault": "physical",
            "vivian_corruption": "ether",
            "burnice_burn": "fire",
            "yanagi_shock": "electric",
        }
        element = element_map.get(archetype, "")
        ticks = [
            ev
            for ev in sim_result.events
            if ev.kind == "anomaly_tick"
            and str(ev.element.value if hasattr(ev.element, "value") else ev.element or "")
            == element
        ]
        assert len(ticks) == expected_procs, (
            f"{anomaly_name}: expected {expected_procs} ticks, got {len(ticks)}"
        )
        sim_total = sum(ev.damage or 0 for ev in ticks)
        # Aggregate tolerance must be >= per-tick tolerance (spec["tolerance_pct"] or 1.0%),
        # otherwise a sim that passes all N per-tick checks can still fail the aggregate
        # when every tick sits at the per-tick boundary and errors accumulate.
        agg_tolerance = spec.get("tolerance_pct", 1.0)
        if expected_total > 0:
            agg_delta_pct = abs(sim_total - expected_total) / expected_total * 100
            assert agg_delta_pct <= agg_tolerance, (
                f"{anomaly_name} aggregate: sim={sim_total}, expected={expected_total}, "
                f"delta={agg_delta_pct:.2f}% > {agg_tolerance}%"
            )


@pytest.fixture
async def app_db():
    """AsyncSession connected to the REAL seeded app DB (not the test DB).

    Skips the test if the DB isn't reachable or required game data is absent.
    The regular CI test DB is isolated (fairy_test) and won't have this data.
    """
    try:
        async with AsyncSession(_app_engine) as session:
            # Quick connectivity probe: check for at least one agent
            result = await session.execute(select(Agent).limit(1))
            if result.scalar_one_or_none() is None:
                _skip_or_fail("App DB has no agents — seeded DB required for crossval")
            yield session
    except Exception as exc:
        pytest.skip(f"App DB not reachable for crossval: {exc}")


def _assert_no_fallback_warnings(sim_result) -> None:
    """No 'Move spec missing' warning may fire for these archetypes.

    docs/TASKS_move_key_resolution.md Task 8: this harness now loads the real
    moves/agents/*.json (see _run_archetype) specifically so it validates a curated
    spec end to end instead of exercising anomaly_simulator's tolerant fallback
    exclusively — a "Move spec missing" warning here means a step's move_name didn't
    resolve against moves_db, silently reverting to the fallback path this task exists
    to stop masking (DESIGN §1.2/§6). Every archetype's step-list move is curated
    (confirmed in docs/LOG_move_key_resolution.md Task 8), so zero is the only
    acceptable count.
    """
    fallback_warnings = [w for w in sim_result.warnings if "Move spec missing" in w]
    assert fallback_warnings == [], (
        f"Unexpected fallback warning(s) — a curated move spec failed to resolve: "
        f"{fallback_warnings}"
    )


async def _run_burnice_channel(db: AsyncSession, channel_s: float):
    """Burnice's single-shot EX held for *channel_s*, expanded the way production expands it.

    Goes through `build_channel_plan` / `plan_hit_offsets` rather than hand-building the
    hit list, so the fixture pins the shipped expansion instead of a copy of it.
    """
    from app.api.v1.simulate import _MOVES_DB
    from app.services.channel_plan import build_channel_plan, plan_hit_offsets

    snap, agent = await _load_stat_line_build(db, "burnice_burn")
    result = await db.execute(select(Attack).where(Attack.agent_id == agent.id))
    by_name: dict[str, list] = {}
    for atk in result.scalars().all():
        by_name.setdefault(atk.name, []).append(atk)
    for v in by_name.values():
        v.sort(key=lambda a: a.hit_index)

    move = "EX Special Attack: Intense Heat Stirring Method"
    if move not in by_name:
        _skip_or_fail(f"Seeded DB has no {move!r} for Burnice — seeded DB required")
    if any(getattr(a.hit_mode, "value", a.hit_mode) != "channel" for a in by_name[move]):
        _skip_or_fail(
            f"{move!r} is not hit_mode='channel' in this DB — migrated but not re-seeded. "
            "Run `python -m scripts.seed_db --skip-icons`."
        )

    spec = _MOVES_DB["burnice"].moves[move]
    plan = build_channel_plan(
        by_name[move],
        spec.channel,
        channel_s,
        tail_s=spec.duration_s or 0.0,
        move_name=move,
    )
    assert plan.warnings == [], f"channel plan warned: {plan.warnings}"

    step = SimulatedAttackStep(
        agent_id="dps",
        move_name=move,
        attacks=[h.row for h in plan.hits],
        attack_scales=[h.mv_scale for h in plan.hits],
        attack_offsets=plan_hit_offsets(plan),
        channel_s=channel_s,
    )

    enemy = EnemyProfile(**_ENEMY_PARAMS)
    db.add(enemy)
    await db.flush()

    sim = simulate(builds={"dps": snap}, steps=[step], enemy=enemy, moves_db=_MOVES_DB)
    return plan, sim


class TestZoCrossval:
    async def test_jane_assault(self, app_db: AsyncSession) -> None:
        fixture = json.loads((_FIXTURES_DIR / "jane_assault.json").read_text())
        sim_result = await _run_archetype(app_db, "jane_assault")
        _assert_no_fallback_warnings(sim_result)
        grouped = _group_events(sim_result)
        for golden in fixture["events"]:
            _check_event(golden, grouped)
        _check_proc_counts(fixture, sim_result)

    async def test_vivian_corruption(self, app_db: AsyncSession) -> None:
        fixture = json.loads((_FIXTURES_DIR / "vivian_corruption.json").read_text())
        sim_result = await _run_archetype(app_db, "vivian_corruption")
        _assert_no_fallback_warnings(sim_result)
        grouped = _group_events(sim_result)
        for golden in fixture["events"]:
            _check_event(golden, grouped)
        _check_proc_counts(fixture, sim_result)

    async def test_burnice_burn(self, app_db: AsyncSession) -> None:
        fixture = json.loads((_FIXTURES_DIR / "burnice_burn.json").read_text())
        sim_result = await _run_archetype(app_db, "burnice_burn")
        _assert_no_fallback_warnings(sim_result)
        grouped = _group_events(sim_result)
        for golden in fixture["events"]:
            _check_event(golden, grouped)
        _check_proc_counts(fixture, sim_result)

    async def test_yanagi_shock(self, app_db: AsyncSession) -> None:
        fixture = json.loads((_FIXTURES_DIR / "yanagi_shock.json").read_text())
        sim_result = await _run_archetype(app_db, "yanagi_shock")
        _assert_no_fallback_warnings(sim_result)
        grouped = _group_events(sim_result)
        for golden in fixture["events"]:
            _check_event(golden, grouped)
        _check_proc_counts(fixture, sim_result)

    async def test_trigger_aftershock(self, app_db: AsyncSession) -> None:
        """Trigger off-field aftershock proc gate: 4 EX hits → 2 procs (3s CD + 2/20s window)."""
        fixture = json.loads((_FIXTURES_DIR / "trigger_aftershock.json").read_text())
        sim_result = await _run_trigger_archetype(app_db)
        _check_aftershock_procs(fixture, sim_result)
        assert sim_result.totals["aftershock"] > 0, (
            "aftershock total must be non-zero when Trigger fires 2 procs"
        )

    async def test_pulchra_aftershock(self, app_db: AsyncSession) -> None:
        """Pulchra repeat-chain gate: chain (grants 6s gait) + Burnice 1 EX → 6 procs (cap)."""
        fixture = json.loads((_FIXTURES_DIR / "pulchra_aftershock.json").read_text())
        sim_result = await _run_pulchra_archetype(app_db)
        _check_aftershock_procs(fixture, sim_result)
        assert sim_result.totals["aftershock"] > 0, (
            "aftershock total must be non-zero when Pulchra fires 6 repeat-chain procs"
        )

    async def test_anby_retag_aftershock(self, app_db: AsyncSession) -> None:
        """Anby on-field re-tag: Chain Attack counted in totals['aftershock'] (P2 Task B3)."""
        fixture = json.loads((_FIXTURES_DIR / "anby_retag_aftershock.json").read_text())
        sim_result = await _run_anby_retag_archetype(app_db)
        retag = fixture["retag_check"]
        min_as = retag["min_aftershock"]
        assert sim_result.totals.get("aftershock", 0) >= min_as, (
            f"aftershock total {sim_result.totals.get('aftershock', 0)} < min {min_as}"
        )
        if retag.get("aftershock_equals_total"):
            total = sim_result.totals.get("total", 0)
            aftershock = sim_result.totals.get("aftershock", 0)
            assert abs(aftershock - total) < 1e-3, (
                f"aftershock ({aftershock:.1f}) should equal total ({total:.1f}) "
                "when only Chain hit in rotation"
            )

    async def test_burnice_channel_full_hold_reproduces_the_authored_multiplier(
        self, app_db: AsyncSession
    ) -> None:
        """A full hold must recover exactly the authored spray MV — no more, no less.

        This is D-CH2 made testable: `nominal_s` is the duration 543.80% is the total OF,
        so the tick scales over a `max_s` hold sum to 1.0. If `tick_s` ever stops dividing
        `max_s` evenly, `round(channel_s / tick_s)` quantizes this away from 1.0 and every
        Burnice spray number moves — silently, because the result stays plausible.
        """
        fixture = json.loads((_FIXTURES_DIR / "burnice_channel.json").read_text())
        expect = fixture["full_hold"]
        plan, sim = await _run_burnice_channel(app_db, 2.0)

        ticks = [h for h in plan.hits if h.role == "tick"]
        releases = [h for h in plan.hits if h.role == "release"]
        assert len(ticks) == expect["tick_count"]
        assert len(releases) == expect["release_count"]
        assert sum(h.mv_scale for h in ticks) == pytest.approx(expect["tick_scale_sum"])
        assert releases[0].mv_scale == pytest.approx(expect["release_scale"])
        assert sim.totals["total"] > 0

    async def test_burnice_channel_hit_cadence_is_the_real_tick_rate(
        self, app_db: AsyncSession
    ) -> None:
        """Ticks land one `tick_s` apart, not spread evenly across the step.

        The spacing is what the 3s per-attribute re-trigger CD and the anomaly decay clock
        read, so an even spread is not a cosmetic difference — it changes proc counts.
        """
        fixture = json.loads((_FIXTURES_DIR / "burnice_channel.json").read_text())
        from app.services.channel_plan import plan_hit_offsets

        plan, _ = await _run_burnice_channel(app_db, 2.0)
        assert plan_hit_offsets(plan) == pytest.approx(fixture["full_hold"]["hit_offsets_s"])

    async def test_burnice_channel_is_linear_in_the_hold_length(
        self, app_db: AsyncSession
    ) -> None:
        """Half the hold, half the spray. The property the whole `whole_channel` basis rests on.

        Asserted as a RATIO between two runs rather than against an absolute number: no
        third party models channels, so an absolute golden here would be this engine
        grading its own homework. A ratio still catches the failure that matters — a basis
        or `nominal_s` change silently rescaling every spray in the game.
        """
        fixture = json.loads((_FIXTURES_DIR / "burnice_channel.json").read_text())
        expect = fixture["half_hold"]

        full_plan, _ = await _run_burnice_channel(app_db, 2.0)
        half_plan, half_sim = await _run_burnice_channel(app_db, 1.0)

        half_ticks = [h for h in half_plan.hits if h.role == "tick"]
        assert len(half_ticks) == expect["tick_count"]
        assert sum(h.mv_scale for h in half_ticks) == pytest.approx(expect["tick_scale_sum"])

        full_spray = sum(h.mv_scale for h in full_plan.hits if h.role == "tick")
        half_spray = sum(h.mv_scale for h in half_ticks)
        assert half_spray / full_spray == pytest.approx(expect["spray_damage_ratio_vs_full"])
        assert half_sim.totals["total"] > 0

    async def test_burnice_channel_gauge_comes_from_the_rows_own_buildup(
        self, app_db: AsyncSession
    ) -> None:
        """D-CH3: a hit's gauge is its OWN row's `anomaly_buildup`, scaled like its damage.

        The release row carries 7155 of the move's 48265 — 14.8%. Under the old uniform
        per-hit split a 0.5s spray tick and the Fire Blast contributed the same gauge,
        which is the defect D-CH3 retired.
        """
        plan, _ = await _run_burnice_channel(app_db, 2.0)
        tick_gauge = sum(
            round((h.row.anomaly_buildup or 0) * h.mv_scale) for h in plan.hits if h.role == "tick"
        )
        release_gauge = sum(
            round((h.row.anomaly_buildup or 0) * h.mv_scale)
            for h in plan.hits
            if h.role == "release"
        )
        # The DB's own per-row values, recovered by a full hold (rounding aside).
        assert tick_gauge == pytest.approx(41110, abs=4)
        assert release_gauge == 7155
        assert tick_gauge + release_gauge == pytest.approx(48265, abs=4)
