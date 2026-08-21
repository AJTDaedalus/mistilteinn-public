"""LCH — channel binding (Task 13, DESIGN_channeled_moves.md §9).

Every rule is exercised against a hand-built violation rather than through Postgres. The
acceptance for this level is "catches each of six", and a rule reachable only through a live
DB is a rule that quietly stops being tested the first time someone's DB is down — which is
the same failure shape LCH itself exists to prevent.
"""

from __future__ import annotations

from unittest.mock import patch

from app.data.loaders.moves import ChannelSpec
from scripts.validate_kits import (
    LCH_STATUS,
    LEVELS,
    _ChannelAgent,
    _ChannelRow,
    _lch_signals,
    unrunnable_levels,
)

_MOVE = "EX Special Attack: Spray"


def _agent(
    *,
    name: str = "Burnice",
    hakushin_id: int | None = 1171,
    params: tuple[str, ...] = ("Continuous Spray DMG Multiplier", "Fire Blast DMG Multiplier"),
    costs: dict[str, bool] | None = None,
    gates: dict[str, str] | None = None,
) -> _ChannelAgent:
    gates = gates or {}
    return _ChannelAgent(
        name=name,
        hakushin_id=hakushin_id,
        rows_by_move={
            _MOVE: [
                _ChannelRow(hit_index=i, param_name=p, select_when=gates.get(p))
                for i, p in enumerate(params)
            ]
        },
        cost_keys={"entry": False, "drain": True, "release": False}
        if costs is None
        else costs,
    )


def _channel(**over: object) -> ChannelSpec:
    base: dict[str, object] = {
        "min_s": 0.0,
        "max_s": 2.0,
        "default_s": 2.0,
        "tick_s": 0.5,
        "tick_mv_basis": "whole_channel",
        "nominal_s": 2.0,
        "roles": {
            "Continuous Spray DMG Multiplier": "tick",
            "Fire Blast DMG Multiplier": "release",
        },
        "entry_cost_key": "entry",
        "drain_cost_key": "drain",
        "release_cost_key": "release",
    }
    base.update(over)
    return ChannelSpec(**base)  # type: ignore[arg-type]


def _codes(agent: _ChannelAgent, channel: ChannelSpec) -> set[str]:
    return {code for code, _ in _lch_signals(agent, _MOVE, channel)}


def test_a_correctly_bound_channel_is_silent() -> None:
    """The control. Without this the six below could all pass on a level that always fires."""
    assert _lch_signals(_agent(), _MOVE, _channel()) == []


# ---- rule 1: role keys resolve, scoped to THIS agent ------------------------


def test_rule1_role_key_that_names_no_row_of_this_move() -> None:
    channel = _channel(
        roles={"Continuous Spray DMG Multiplier": "tick", "Napalm DMG Multiplier": "release"}
    )
    assert "channel_role_key_unresolved" in _codes(_agent(), channel)


def test_rule1_is_scoped_per_agent_not_per_corpus() -> None:
    """A key that is a real `param_name` *somewhere* must still fail if this agent lacks it.

    The #77 trap: a corpus-wide `param_name` set answers "resolves" for a row belonging to
    another agent entirely, and this repo fell into exactly that inside #77's own
    remediation table.
    """
    other = _agent(name="Norma", hakushin_id=1571, params=("Barrage DMG Multiplier Per Sec",))
    channel = _channel(
        tick_mv_basis="per_second",
        nominal_s=None,
        roles={"Continuous Spray DMG Multiplier": "tick"},
    )
    assert "channel_role_key_unresolved" in _codes(other, channel)


# ---- rule 2: every row is classified ---------------------------------------


def test_rule2_unclassified_row_is_flagged() -> None:
    """It would fire once, unscaled — plausible output, wrong move."""
    channel = _channel(roles={"Continuous Spray DMG Multiplier": "tick"})
    assert "channel_row_unclassified" in _codes(_agent(), channel)


# ---- rule 3: basis / nominal_s coherence -----------------------------------


def test_rule3_whole_channel_without_nominal_s() -> None:
    """The loader defaults this (D-CH2), so only a spec built past it in code can be here."""
    channel = _channel()
    object.__setattr__(channel, "nominal_s", None)
    assert "channel_basis_nominal_mismatch" in _codes(_agent(), channel)


def test_rule3_per_second_carrying_a_nominal_s() -> None:
    channel = _channel(tick_mv_basis="per_second", nominal_s=None)
    object.__setattr__(channel, "nominal_s", 2.0)
    assert "channel_basis_nominal_mismatch" in _codes(_agent(), channel)


# ---- rule 4: the upstream 'Per Sec' label ----------------------------------


def test_rule4_labelled_row_read_as_a_whole_channel_total() -> None:
    """The game says the row is a rate; the curator says it is a total. One of them is wrong."""
    agent = _agent(
        name="Norma",
        hakushin_id=1571,
        params=("Barrage DMG Multiplier Per Sec", "Fire Blast DMG Multiplier"),
    )
    channel = _channel(
        roles={"Barrage DMG Multiplier Per Sec": "tick", "Fire Blast DMG Multiplier": "release"}
    )
    assert "channel_per_sec_label_mismatch" in _codes(agent, channel)


def test_rule4_unlabelled_row_claiming_the_per_second_basis() -> None:
    channel = _channel(tick_mv_basis="per_second", nominal_s=None)
    assert "channel_per_sec_label_mismatch" in _codes(_agent(hakushin_id=1571), channel)


# ---- rule 5: cost-key binding ----------------------------------------------


def test_rule5_cost_key_resolving_to_nothing() -> None:
    channel = _channel(drain_cost_key="not_a_real_key")
    assert "channel_cost_key_unresolved" in _codes(_agent(), channel)


def test_rule5_drain_bound_to_a_flat_cost() -> None:
    """Bills a whole hold as one payment — and the total still looks like a number."""
    channel = _channel(drain_cost_key="entry", entry_cost_key="drain")
    codes = _codes(_agent(), channel)
    assert codes == {"channel_cost_key_per_sec_mismatch"}


# ---- rule 6: the era boundary (D-CH1) --------------------------------------


def test_rule6_early_agent_claiming_the_per_second_basis() -> None:
    channel = _channel(tick_mv_basis="per_second", nominal_s=None)
    assert "channel_era_basis_mismatch" in _codes(_agent(hakushin_id=1171), channel)


def test_rule6_a_synthetic_new_agent_that_violates_the_boundary() -> None:
    """The event this rule exists for: HoYo shifts convention and nobody notices.

    A brand-new agent well past the per-second boundary, authored whole_channel. It must
    fail the build rather than arrive silently; widening the boundary is an owner ruling.
    """
    agent = _agent(name="Someone New", hakushin_id=1701)
    assert "channel_era_basis_mismatch" in _codes(agent, _channel())


def test_rule6_says_nothing_inside_the_gap_between_the_cohorts() -> None:
    """1371 < id < 1541 is where no channel has shipped. Asserting there would be invention."""
    agent = _agent(name="Gap Agent", hakushin_id=1441)
    assert _lch_signals(agent, _MOVE, _channel()) == []


def test_rule6_is_silent_when_the_agent_has_no_id() -> None:
    assert _lch_signals(_agent(hakushin_id=None), _MOVE, _channel()) == []


# ---- the skip contract: a skipped level BLOCKS ------------------------------


class TestLchSkipBlocks:
    """`--require-db` must turn LCH's two skip modes into a non-zero exit naming LCH."""

    def test_unreachable_db_is_unrunnable(self) -> None:
        with patch.dict(LCH_STATUS, {"db_reachable": False, "param_name_populated": False}):
            assert "lch" in unrunnable_levels(["lch"])

    def test_migrated_but_not_reseeded_is_unrunnable(self) -> None:
        """`param_name` is populated by the nanoka importer alone — NULLs are 'could not check'."""
        with patch.dict(LCH_STATUS, {"db_reachable": True, "param_name_populated": False}):
            assert "lch" in unrunnable_levels(["lch"])

    def test_a_healthy_run_is_runnable(self) -> None:
        with patch.dict(LCH_STATUS, {"db_reachable": True, "param_name_populated": True}):
            assert unrunnable_levels(["lch"]) == []

    def test_lch_is_not_reported_when_it_was_not_requested(self) -> None:
        """Asserted as "lch absent", NOT "the list is empty".

        `unrunnable_levels` reports every requested DB-backed layer, and L0 has its own
        DB-dependent branch (Rule 8c's ramp-index check) driven by module-level state that
        earlier tests mutate. Demanding an empty list couples this test to all of that: it
        passed against a seeded DB and failed on CI, where L0's ramps are unavailable.
        """
        with patch.dict(LCH_STATUS, {"db_reachable": False, "param_name_populated": False}):
            assert "lch" not in unrunnable_levels(["l0"])


def test_lch_is_in_the_dispatch_table() -> None:
    """The stale-waiver check is gated on `set(levels) == set(LEVELS)`.

    A level that exists but is never dispatched would silently switch that check off for
    every other level too, so LCH must be a real LEVELS entry rather than a special case.
    """
    assert LEVELS["lch"].__name__ == "check_lch"


# ---- rules 7 and 8: the row gates (D-CH5) -----------------------------------


def test_rule7_an_unknown_row_condition_is_flagged() -> None:
    """The simulator fails OPEN on one of these, which is the right runtime call.

    It keeps the damage rather than deleting a hit. But "we fired a row we could not
    interpret" is exactly the thing to be loud about at build time.
    """
    agent = _agent(gates={"Fire Blast DMG Multiplier": "enemy_is_on_fire"})
    assert "channel_row_condition_unknown" in _codes(agent, _channel())


def test_rule8_a_role_that_starves_in_one_state_is_flagged() -> None:
    """Gating is the only mechanism here that can make a role produce NOTHING.

    Author both warheads `enemy_stunned` and the move silently deals no entry damage
    against an unstunned target — a smaller number, not an error, which is the class of
    defect this harness exists for.
    """
    agent = _agent(
        gates={
            "Continuous Spray DMG Multiplier": "enemy_stunned",
            "Fire Blast DMG Multiplier": "enemy_stunned",
        }
    )
    codes = _codes(agent, _channel())
    assert "channel_role_empty_in_state" in codes


def test_rule8_is_silent_when_the_gates_partition_properly() -> None:
    """Norma's real shape: one row per state per role, so every state keeps every role."""
    agent = _agent(
        params=(
            "Shot DMG Multiplier",
            "AP Warhead DMG Multiplier",
            "HE Warhead DMG Multiplier",
            "Extended Shot DMG Multiplier Per Sec",
        ),
        gates={
            "AP Warhead DMG Multiplier": "enemy_not_stunned",
            "HE Warhead DMG Multiplier": "enemy_stunned",
        },
    )
    channel = _channel(
        tick_mv_basis="per_second",
        nominal_s=None,
        roles={
            "Shot DMG Multiplier": "entry",
            "AP Warhead DMG Multiplier": "entry",
            "HE Warhead DMG Multiplier": "entry",
            "Extended Shot DMG Multiplier Per Sec": "tick",
        },
    )
    assert "channel_role_empty_in_state" not in _codes(_agent_at(agent, 1571), channel)


def _agent_at(agent: _ChannelAgent, hakushin_id: int) -> _ChannelAgent:
    """Same agent, different id — the era rule reads it and would otherwise object."""
    return _ChannelAgent(
        name=agent.name,
        hakushin_id=hakushin_id,
        rows_by_move=agent.rows_by_move,
        cost_keys=agent.cost_keys,
    )


def test_ungated_moves_are_untouched_by_the_new_rules() -> None:
    """Every existing channel has no gates; rules 7 and 8 must be inert for them."""
    assert _lch_signals(_agent(), _MOVE, _channel()) == []
