"""Task A1 — AftershockSpec P2 field defaults + per-move grants fields parse."""


from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec

# ---------------------------------------------------------------------------
# AftershockSpec P2 fields — defaults preserve P1 behaviour
# ---------------------------------------------------------------------------


def test_aftershockspec_p2_fields_default():
    spec = AftershockSpec(react_to=["hit"], aftershock_mv_bp=1000)
    assert spec.requires_state is None
    assert spec.repeat_max == 0
    assert spec.finisher_mv_bp is None
    assert spec.on_field_self is False


def test_aftershockspec_p2_fields_roundtrip():
    spec = AftershockSpec(
        react_to=["hit"],
        aftershock_mv_bp=4630,
        requires_state="hunters_gait",
        repeat_max=5,
        finisher_mv_bp=5350,
        on_field_self=False,
    )
    assert spec.requires_state == "hunters_gait"
    assert spec.repeat_max == 5
    assert spec.finisher_mv_bp == 5350
    assert spec.on_field_self is False


def test_aftershockspec_on_field_self_flag():
    spec = AftershockSpec(
        react_to=["hit"],
        aftershock_mv_bp=4300,
        on_field_self=True,
    )
    assert spec.on_field_self is True


# ---------------------------------------------------------------------------
# Existing P1 specs (trigger / orphie) round-trip without change
# ---------------------------------------------------------------------------


def _trigger_spec() -> AftershockSpec:
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=["ex_special", "chain", "ultimate", "assist_followup"],
        requires_off_field=True,
        cooldown_s=3.0,
        max_per_window=2,
        window_s=20.0,
        procs_per_trigger=1,
        aftershock_mv_bp=6780,
        element="electric",
        damage_path="standard",
    )


def test_trigger_spec_p2_fields_absent_from_p1_json():
    """P1 JSON has no P2 keys — defaults must silently absorb them."""
    spec = _trigger_spec()
    assert spec.requires_state is None
    assert spec.repeat_max == 0
    assert spec.finisher_mv_bp is None
    assert spec.on_field_self is False


# ---------------------------------------------------------------------------
# MoveBuildupSpec — grants_state / state_duration_s / grants_full_charge
# ---------------------------------------------------------------------------


def test_move_grants_fields_default():
    move = MoveBuildupSpec()
    assert move.grants_state is None
    assert move.state_duration_s is None
    assert move.grants_full_charge is None


def test_move_grants_fields_parse():
    move = MoveBuildupSpec(
        grants_state="hunters_gait",
        state_duration_s=6.0,
    )
    assert move.grants_state == "hunters_gait"
    assert move.state_duration_s == 6.0
    assert move.grants_full_charge is None


def test_move_grants_full_charge_parse():
    move = MoveBuildupSpec(grants_full_charge="silver_star")
    assert move.grants_full_charge == "silver_star"
    assert move.grants_state is None


def test_move_grants_fields_via_agent_spec():
    """Full AgentMovesSpec round-trip including new move fields."""
    data = {
        "agent_name": "TestAgent",
        "moves": {
            "ex_special": {
                "hits": 2,
                "grants_state": "hunters_gait",
                "state_duration_s": 6.0,
            },
            "ultimate": {
                "hits": 1,
                "grants_full_charge": "silver_star",
            },
        },
    }
    spec = AgentMovesSpec.model_validate(data)
    ex = spec.moves["ex_special"]
    assert ex.grants_state == "hunters_gait"
    assert ex.state_duration_s == 6.0
    assert ex.grants_full_charge is None

    ult = spec.moves["ultimate"]
    assert ult.grants_full_charge == "silver_star"
    assert ult.grants_state is None
