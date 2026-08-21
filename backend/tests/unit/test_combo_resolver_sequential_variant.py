"""Unit tests for sequential single-tap and variant resolver branches — T-B3, T-B4, T-B5."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.enums import HitMode, PotentialVariant
from app.services.combo_step_resolver import (
    _classify_move,
    resolve_combo_sequence,
)
from app.services.combo_types import ComboStep, StunTriggerStep


def _build(agent_id: str = "agent-1") -> MagicMock:
    b = MagicMock()
    b.potential_rank = 5
    b.agent_id = agent_id
    b.skill_levels = "12,12,12,12,12"
    return b


def _attack(
    hit_index: int = 0,
    name: str = "Basic Attack: Swiftedge",
    skill_key: str = "Basic",
    hit_mode: HitMode = HitMode.ATOMIC,
    variant_label: str | None = None,
    damage_base: int = 1000,
    damage_growth: int = 0,
) -> MagicMock:
    a = MagicMock()
    a.id = f"att-{hit_index}"
    a.hit_index = hit_index
    a.name = name
    a.skill_key = skill_key
    a.hit_mode = hit_mode
    a.variant_label = variant_label
    a.element = "fire"
    a.damage_base = damage_base
    a.damage_growth = damage_growth
    a.stun_base = 0
    a.stun_growth = 0
    a.energy_gain = 0
    a.anomaly_buildup = 0
    return a


def _swiftedge_attacks() -> list[MagicMock]:
    return [
        _attack(hit_index=i, hit_mode=HitMode.SEQUENTIAL, damage_base=1000 + i * 500)
        for i in range(4)
    ]


def _repo_for(attacks: list[MagicMock]) -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = attacks
    return repo


# ---- _classify_move -------------------------------------------------------


def test_classify_atomic() -> None:
    attacks = [_attack(hit_index=i, hit_mode=HitMode.ATOMIC) for i in range(3)]
    mode, labels = _classify_move(attacks)
    assert mode == HitMode.ATOMIC
    assert labels == []


def test_classify_sequential() -> None:
    attacks = _swiftedge_attacks()
    mode, labels = _classify_move(attacks)
    assert mode == HitMode.SEQUENTIAL
    assert labels == []


def test_classify_variant() -> None:
    attacks = [
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="Low"),
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="High"),
    ]
    mode, labels = _classify_move(attacks)
    assert mode == HitMode.VARIANT
    assert set(labels) == {"Low", "High"}


def test_classify_empty_returns_atomic() -> None:
    mode, _labels = _classify_move([])
    assert mode == HitMode.ATOMIC


# ---- Variant resolve -------------------------------------------------------

pytestmark = pytest.mark.asyncio


async def test_variant_valid_label_emits_only_matching_hits() -> None:
    attacks = [
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="Low"),
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="High"),
    ]
    repo = _repo_for(attacks)
    raw_seq = [{"move_name": "Soaring Light", "variant_label": "Low", "label": "SL-Low"}]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert len(result) == 1
    assert isinstance(result[0], ComboStep)
    assert result[0].label == "SL-Low"


async def test_variant_missing_label_falls_back_to_first_label() -> None:
    """Was a 400 until Task 4 (DESIGN_sequential_variant.md §5.8).

    Re-classifying a move to `variant` leaves every already-saved combo step without a
    label; a 400 there fails the whole team-DPS request. It now resolves to the first
    of the sorted labels and warns. Full coverage — including the other two cycle
    implementations agreeing — lives in `test_variant_fallback.py`.
    """
    attacks = [
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="Low"),
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="High"),
    ]
    repo = _repo_for(attacks)
    raw_seq = [{"move_name": "Soaring Light", "label": "SL"}]
    warnings: list[str] = []
    result = await resolve_combo_sequence(
        raw_seq, build=_build(), attack_repo=repo, warnings=warnings
    )
    assert len(result) == 1
    assert result[0].label == "SL"
    assert len(warnings) == 1
    assert "High" in warnings[0], "sorted labels are ['High', 'Low'] — first is 'High'"


async def test_variant_unknown_label_raises_404() -> None:
    attacks = [
        _attack(hit_index=0, name="Soaring Light", hit_mode=HitMode.VARIANT, variant_label="Low"),
    ]
    repo = _repo_for(attacks)
    raw_seq = [{"move_name": "Soaring Light", "variant_label": "Unknown", "label": "SL"}]
    with pytest.raises(HTTPException) as exc_info:
        await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert exc_info.value.status_code == 404


# ---- Sequential single-tap -------------------------------------------------


async def test_sequential_single_tap_isolated_starts_at_hit0() -> None:
    repo = _repo_for(_swiftedge_attacks())
    raw_seq = [{"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": "SW"}]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert len(result) == 1
    assert result[0].attack_id == "att-0"


async def test_sequential_single_tap_consecutive_cycles() -> None:
    attacks = _swiftedge_attacks()
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = attacks
    raw_seq = [
        {"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": f"SW{i}"}
        for i in range(5)  # 5 taps over 4-hit chain → should wrap
    ]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert len(result) == 5
    assert [r.attack_id for r in result] == ["att-0", "att-1", "att-2", "att-3", "att-0"]


async def test_sequential_single_tap_interrupted_resets_to_hit0() -> None:
    attacks = _swiftedge_attacks()
    other_attacks = [_attack(hit_index=0, name="Special Attack", hit_mode=HitMode.ATOMIC)]
    repo = AsyncMock()

    def side_effect(agent_id: str, name: str, variant: object) -> list:
        if "Swiftedge" in name:
            return attacks
        return other_attacks

    repo.get_by_agent_and_name.side_effect = side_effect

    raw_seq = [
        {"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": "SW0"},
        {"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": "SW1"},
        {"move_name": "Special Attack", "label": "SP"},  # interrupt
        {"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": "SW2"},
    ]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert result[0].attack_id == "att-0"  # first tap → hit 0
    assert result[1].attack_id == "att-1"  # second tap → hit 1
    # index 2 is Special (not checked by attack_id)
    assert result[3].attack_id == "att-0"  # after interrupt → hit 0 again


async def test_stun_marker_does_not_reset_sequential_cycle() -> None:
    attacks = _swiftedge_attacks()
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = attacks

    raw_seq = [
        {"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": "SW0"},
        {"step_type": "stun_trigger", "label": "Stun"},
        {"move_name": "Basic Attack: Swiftedge", "single_tap": True, "label": "SW1"},
    ]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    combo_steps = [r for r in result if isinstance(r, ComboStep)]
    assert combo_steps[0].attack_id == "att-0"
    assert combo_steps[1].attack_id == "att-1"  # NOT reset by marker
    stun_steps = [r for r in result if isinstance(r, StunTriggerStep)]
    assert len(stun_steps) == 1


async def test_sequential_explicit_cycle_position() -> None:
    attacks = _swiftedge_attacks()
    repo = _repo_for(attacks)
    raw_seq = [
        {
            "move_name": "Basic Attack: Swiftedge",
            "single_tap": True,
            "cycle_position": 3,
            "label": "SW",
        }
    ]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert result[0].attack_id == "att-3"


# ---- Sequential full-chain (backward compat) --------------------------------


async def test_sequential_single_step_emits_one_hit() -> None:
    repo = _repo_for(_swiftedge_attacks())
    raw_seq = [{"move_name": "Basic Attack: Swiftedge", "label": "SW"}]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    assert len(result) == 1


async def test_sequential_single_tap_false_treated_as_single_tap() -> None:
    """single_tap=False on a sequential step is backward-compat for pre-fix saved combos.
    It must behave identically to single_tap=True so old combos resolve correctly."""
    attacks = _swiftedge_attacks()
    repo = _repo_for(attacks)
    raw_seq = [
        {"move_name": "Basic Attack: Swiftedge", "single_tap": False, "label": "SW1"},
        {"move_name": "Basic Attack: Swiftedge", "single_tap": False, "label": "SW2"},
    ]
    result = await resolve_combo_sequence(raw_seq, build=_build(), attack_repo=repo)
    combo_steps = [r for r in result if isinstance(r, ComboStep)]
    # Each step fires exactly one hit; second step advances the cycle
    assert len(combo_steps) == 2
    assert combo_steps[0].attack_id == "att-0"
    assert combo_steps[1].attack_id == "att-1"


# ---- Support agent steps ----------------------------------------------------


async def test_resolve_support_agent_steps() -> None:
    build = _build(agent_id="dps-agent")
    s1 = _build(agent_id="support-agent-1")
    # Distinct ranks, so the assertion below proves the step resolves against the
    # SUPPORT build's Potential state rather than the primary build's (#90).
    build.potential_rank = 5
    s1.potential_rank = 0

    support_attacks = [
        _attack(hit_index=0, name="EX Special Attack: Cavity Alert", skill_key="EXSpecial")
    ]
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = support_attacks

    raw_seq = [
        {
            "move_name": "EX Special Attack: Cavity Alert",
            "agent_id": "support1",
            "label": "Cavity Alert",
        }
    ]
    result = await resolve_combo_sequence(
        raw_seq, build=build, attack_repo=repo, member_builds={"dps": build, "support1": s1}
    )
    assert len(result) == 1
    assert isinstance(result[0], ComboStep)
    assert result[0].attack_id == "att-0"
    assert result[0].attack_name == "EX Special Attack: Cavity Alert"

    repo.get_by_agent_and_name.assert_called_once_with(
        "support-agent-1", "EX Special Attack: Cavity Alert", PotentialVariant.LOCKED
    )


async def test_resolve_support_agent_steps_not_equipped() -> None:
    build = _build(agent_id="dps-agent")

    repo = AsyncMock()
    raw_seq = [
        {
            "move_name": "EX Special Attack: Cavity Alert",
            "agent_id": "support1",
            "label": "Cavity Alert",
        }
    ]
    with pytest.raises(HTTPException) as exc_info:
        await resolve_combo_sequence(
            raw_seq, build=build, attack_repo=repo, member_builds={"dps": build}
        )
    assert exc_info.value.status_code == 422
    assert "No Support 1 build in this team" in str(exc_info.value.detail)
