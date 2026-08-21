"""Task B2 — White Thunder charge cascade + wire Anby (soldier_0_anby.json).

Tests (TDD — written before implementation):
  - test_anby_full_charge_sets_3_wt: EX/Ult anchor (grants_full_charge=silver_star) makes 3
    Azure-Flash WT consumes possible in one cycle — 3 extra-instance Aftershocks fire.
  - test_anby_wt_consume_emits_aftershock: one Azure Flash hit while WT>0 emits exactly 1 WT
    Aftershock proc; same hit with WT=0 emits nothing.
  - test_anby_thunder_smite_and_boundary_after_3: 3 Azure Flash consumes (tally=3) trigger
    Thunder Smite + Boundary as Aftershock events (5 total aftershock events in the cycle).
  - test_anby_no_wt_without_azure_flash: EX anchor sets WT=3, but basic-only hits never
    consume it — zero WT Aftershock procs.
"""

from types import SimpleNamespace

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate

_WT_EXTRA_MV = 4_300  # Azure Flash extra-instance (hit_index 1, DB)
_SMITE_MV = 18_810  # Thunder Smite (DB)
_BOUNDARY_MV = 24_940  # Boundary (DB)
_VORTEX_MV = 100_000  # M6 electromagnetic vortex (DB, 1000% ATK)


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Test Target",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=10000,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )


def _build(name: str, mindscape_level: int = 0):
    from app.services.build_damage_service import BuildSnapshot

    return BuildSnapshot(
        agent_name=name,
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[],
        mindscape_level=mindscape_level,
    )


def _hit(scope: str = "ex_special"):
    return SimpleNamespace(
        element="electric",
        skill_key="EXSpecial",
        damage_base=37_960,
        damage_growth=0,
        name="ex_sundering_bolt",
        id="1",
        anomaly_buildup=0,
    )


def _special_hit():
    return SimpleNamespace(
        element="electric",
        skill_key="Special",
        damage_base=16_720,
        damage_growth=0,
        name="azure_flash",
        id="2",
        anomaly_buildup=0,
    )


def _basic_hit():
    return SimpleNamespace(
        element="electric",
        skill_key="Basic",
        damage_base=3_270,
        damage_growth=0,
        name="basic_attack",
        id="3",
        anomaly_buildup=0,
    )


def _wt_spec(*, with_vortex: bool = False) -> AftershockSpec:
    """Anby's WT cascade spec: consume 1 WT on special-scope hits."""
    return AftershockSpec(
        react_to=["hit"],
        on_field_self=False,
        wt_consume_scopes=["special"],
        aftershock_mv_bp=_WT_EXTRA_MV,
        wt_smite_mv_bp=_SMITE_MV,
        wt_boundary_mv_bp=_BOUNDARY_MV,
        wt_tally_cap=3,
        element="electric",
        **(
            {
                "wt_vortex_mv_bp": _VORTEX_MV,
                "wt_vortex_tally_cap": 6,
                "wt_vortex_requires_mindscape": 6,
            }
            if with_vortex
            else {}
        ),
    )


_EX_MOVE = MoveBuildupSpec(
    hits=1,
    duration_s=2.0,
    scope="ex_special",
    grants_full_charge="silver_star",
)
_SPECIAL_MOVE = MoveBuildupSpec(hits=1, duration_s=1.5, scope="special")
_BASIC_MOVE = MoveBuildupSpec(hits=1, duration_s=1.0, scope="basic")


def _moves_db(agent_name: str, spec: AftershockSpec) -> dict:
    key = agent_name.lower().replace(" ", "_")
    return {
        key: AgentMovesSpec(
            moves={
                "ex": _EX_MOVE,
                "special": _SPECIAL_MOVE,
                "basic": _BASIC_MOVE,
            },
            aftershock=spec,
        )
    }


# ---------------------------------------------------------------------------
# test_anby_full_charge_sets_3_wt
# ---------------------------------------------------------------------------


def test_anby_full_charge_sets_3_wt():
    """EX anchor (grants_full_charge=silver_star) sets WT=3; 3 Azure Flash hits consume all 3
    stacks → exactly 3 WT extra-instance Aftershocks fire (plus Smite + Boundary)."""
    builds = {"A": _build("A")}
    mdb = _moves_db("A", _wt_spec())

    rotation = [
        # EX: grants_full_charge → WT=3
        SimulatedAttackStep(
            agent_id="A",
            move_name="ex",
            attacks=[_hit("ex_special")],
            conditions=[],
        ),
        # 3 Azure Flash specials: consume 1 WT each
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
    ]

    result = simulate(builds, rotation, _enemy(), mdb)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    wt_procs = [e for e in as_events if e.detail.get("multiplier") == _WT_EXTRA_MV]
    assert len(wt_procs) == 3, (
        f"EX should set WT=3, enabling 3 extra-instance Aftershocks; got {len(wt_procs)}"
    )


# ---------------------------------------------------------------------------
# test_anby_wt_consume_emits_aftershock
# ---------------------------------------------------------------------------


def test_anby_wt_consume_emits_aftershock():
    """Azure Flash (special scope) with WT>0 emits 1 WT extra-instance Aftershock.
    Without EX (WT=0), Azure Flash emits no WT Aftershock."""
    spec = _wt_spec()

    # --- with WT (EX first) ---
    builds = {"A": _build("A")}
    mdb = _moves_db("A", spec)

    rotation_with_wt = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="ex",
            attacks=[_hit("ex_special")],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
    ]
    result_with = simulate(builds, rotation_with_wt, _enemy(), mdb)
    wt_procs = [
        e
        for e in result_with.events
        if e.kind == "aftershock" and e.detail.get("multiplier") == _WT_EXTRA_MV
    ]
    assert len(wt_procs) == 1, f"Expected 1 WT proc; got {len(wt_procs)}"
    assert wt_procs[0].agent_id == "A"

    # --- without WT (no EX) ---
    rotation_no_wt = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
    ]
    result_no = simulate(builds, rotation_no_wt, _enemy(), mdb)
    wt_procs_none = [
        e
        for e in result_no.events
        if e.kind == "aftershock" and e.detail.get("multiplier") == _WT_EXTRA_MV
    ]
    assert len(wt_procs_none) == 0, "No WT procs expected when WT=0 (no EX anchor)"


# ---------------------------------------------------------------------------
# test_anby_thunder_smite_and_boundary_after_3
# ---------------------------------------------------------------------------


def test_anby_thunder_smite_and_boundary_after_3():
    """3 WT consumes (tally=3) trigger Thunder Smite + Boundary as Aftershock events.

    Expected aftershock events after EX + 3 Azure Flashes:
      3 × WT extra-instance (MV=4300) + 1 × Thunder Smite (MV=18810) + 1 × Boundary (MV=24940)
      = 5 aftershock events total.
    """
    builds = {"A": _build("A")}
    mdb = _moves_db("A", _wt_spec())

    rotation = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="ex",
            attacks=[_hit("ex_special")],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="special",
            attacks=[_special_hit()],
            conditions=[],
        ),
    ]

    result = simulate(builds, rotation, _enemy(), mdb)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    smite_events = [e for e in as_events if e.detail.get("multiplier") == _SMITE_MV]
    boundary_events = [e for e in as_events if e.detail.get("multiplier") == _BOUNDARY_MV]
    wt_extra = [e for e in as_events if e.detail.get("multiplier") == _WT_EXTRA_MV]

    assert len(wt_extra) == 3, f"Expected 3 WT extra-instance procs; got {len(wt_extra)}"
    assert len(smite_events) == 1, f"Expected 1 Thunder Smite; got {len(smite_events)}"
    assert len(boundary_events) == 1, f"Expected 1 Boundary; got {len(boundary_events)}"
    assert len(as_events) == 5, f"Expected 5 total aftershock events; got {len(as_events)}"

    # Smite + Boundary appear after the 3rd WT consume
    smite_t = smite_events[0].t
    boundary_t = boundary_events[0].t
    third_wt_t = wt_extra[2].t
    assert smite_t >= third_wt_t, "Thunder Smite must fire at or after the 3rd WT consume"
    assert boundary_t >= smite_t, "Boundary must fire at or after Thunder Smite"


# ---------------------------------------------------------------------------
# test_anby_no_wt_without_azure_flash
# ---------------------------------------------------------------------------


def test_anby_no_wt_without_azure_flash():
    """EX anchor sets WT=3, but basic-scope hits do not consume WT — zero WT procs."""
    builds = {"A": _build("A")}
    mdb = _moves_db("A", _wt_spec())

    rotation = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="ex",
            attacks=[_hit("ex_special")],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="basic",
            attacks=[_basic_hit()],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="A",
            move_name="basic",
            attacks=[_basic_hit()],
            conditions=[],
        ),
    ]

    result = simulate(builds, rotation, _enemy(), mdb)
    _wt_mvs = (_WT_EXTRA_MV, _SMITE_MV, _BOUNDARY_MV)
    wt_procs = [
        e
        for e in result.events
        if e.kind == "aftershock" and e.detail.get("multiplier") in _wt_mvs
    ]
    assert len(wt_procs) == 0, (
        f"Basic-scope hits must not consume WT; got {len(wt_procs)} WT procs"
    )


# ---------------------------------------------------------------------------
# test_anby_m6_vortex_after_6_wt_at_mindscape_6
# ---------------------------------------------------------------------------


def _rotation_with_n_wt_consumes(n: int) -> list[SimulatedAttackStep]:
    """EX anchors (full-charge → WT=3, not additive) interleaved every 3
    specials, so each of the n Azure Flash specials finds WT>0 and consumes 1."""
    steps: list[SimulatedAttackStep] = []
    for i in range(n):
        if i % 3 == 0:
            steps.append(
                SimulatedAttackStep(
                    agent_id="A", move_name="ex", attacks=[_hit("ex_special")], conditions=[]
                )
            )
        steps.append(
            SimulatedAttackStep(
                agent_id="A", move_name="special", attacks=[_special_hit()], conditions=[]
            )
        )
    return steps


def test_anby_m6_vortex_after_6_wt_at_mindscape_6():
    """Task 17 Batch 7 re-audit fix: the M6 vortex is a second, independent
    modulus (cap 6) on the same WT-consume event stream that drives the cap-3
    Smite/Boundary chain — not an attack-scope-gated bonus (formerly mis-scoped
    as scope:ex_special in the kit-modifiers formulas[] block, over-crediting
    0%-24% of rotation damage depending on the EX:Special ratio).

    6 WT consumes at mindscape 6: 2 Smite + 2 Boundary (cap 3, fires twice) and
    exactly 1 vortex (cap 6, fires once).
    """
    builds = {"A": _build("A", mindscape_level=6)}
    mdb = _moves_db("A", _wt_spec(with_vortex=True))

    result = simulate(builds, _rotation_with_n_wt_consumes(6), _enemy(), mdb)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    vortex_events = [e for e in as_events if e.detail.get("multiplier") == _VORTEX_MV]
    smite_events = [e for e in as_events if e.detail.get("multiplier") == _SMITE_MV]
    boundary_events = [e for e in as_events if e.detail.get("multiplier") == _BOUNDARY_MV]

    assert len(vortex_events) == 1, (
        f"Expected exactly 1 vortex at 6 WT consumes; got {len(vortex_events)}"
    )
    assert len(smite_events) == 2, (
        f"Expected 2 Thunder Smites (cap 3 fires twice); got {len(smite_events)}"
    )
    assert len(boundary_events) == 2, f"Expected 2 Boundaries; got {len(boundary_events)}"


def test_anby_m6_vortex_gated_below_mindscape_6():
    """Below M6, the vortex must not fire even after 6 WT consumes — the DB
    effect ('Upon triggering 6 instances... an electromagnetic vortex') is
    Mindscape-6-only."""
    builds = {"A": _build("A", mindscape_level=0)}
    mdb = _moves_db("A", _wt_spec(with_vortex=True))

    result = simulate(builds, _rotation_with_n_wt_consumes(6), _enemy(), mdb)
    vortex_events = [
        e
        for e in result.events
        if e.kind == "aftershock" and e.detail.get("multiplier") == _VORTEX_MV
    ]
    assert len(vortex_events) == 0, "Vortex must not fire below Mindscape 6"


def test_anby_m6_vortex_absent_without_spec_field():
    """Agents without wt_vortex_mv_bp set (the pre-fix default) never emit a
    vortex event, regardless of tally — confirms the new fields are opt-in and
    don't change behavior for other wt_consume_scopes users (e.g. any future
    non-Anby WT-style kit)."""
    builds = {"A": _build("A", mindscape_level=6)}
    mdb = _moves_db("A", _wt_spec(with_vortex=False))

    result = simulate(builds, _rotation_with_n_wt_consumes(6), _enemy(), mdb)
    vortex_events = [
        e
        for e in result.events
        if e.kind == "aftershock" and e.detail.get("multiplier") == _VORTEX_MV
    ]
    assert len(vortex_events) == 0, "No vortex without wt_vortex_mv_bp configured"
