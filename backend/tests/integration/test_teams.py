"""Integration tests for the team calculate endpoint (Phase 5B).

Covers B5 acceptance criteria:
- Team-owned combo with matching team_id → 200 + by_agent breakdown
- Combo from different team → 422
- Step with non-member agent_id → 422
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.models.disc import DiscSet
from app.models.enums import Element, Rarity, Specialty, StatType
from app.services.modifiers import AttackScope, Condition, Modifier, ModifierSource, ModifierTarget

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Shared seed helper
# ---------------------------------------------------------------------------


async def _seed_two_agent_team(
    authed_client: AsyncClient,
    db: AsyncSession,
    owner_id: str,
) -> dict:
    """Two agents (DPS + support) in a team, combo with one DPS step.

    Combo steps have no explicit agent_id, so they default to the primary
    (slot 1) build after endpoint normalization.
    """
    dps_agent = Agent(
        hakushin_id=8001,
        name="B5DPS",
        element=Element.ICE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    sup_agent = Agent(
        hakushin_id=8002,
        name="B5Sup",
        element=Element.FIRE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_atk=500,
        base_hp=10_000,
        base_def=700,
    )
    enemy = EnemyProfile(name="B5Dummy", level=60, defense=60, ice_res=0)
    db.add_all([dps_agent, sup_agent, enemy])
    await db.flush()

    attack = Attack(
        agent_id=dps_agent.id,
        hakushin_skill_id=80,
        skill_key="Basic",
        name="B5 Basic",
        hit_index=0,
        element=Element.ICE,
        damage_base=10_000,
        damage_growth=500,
    )
    # Support owns a damaging move of its own — exercises the multi-agent path
    # where a non-primary member contributes damage via a move_name step.
    sup_attack = Attack(
        agent_id=sup_agent.id,
        hakushin_skill_id=81,
        skill_key="Special",
        name="B5 Support Skill",
        hit_index=0,
        element=Element.FIRE,
        damage_base=8_000,
        damage_growth=400,
    )
    db.add_all([attack, sup_attack])
    await db.flush()

    dps_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "B5DPSBuild", "agent_id": str(dps_agent.id)},
    )
    assert dps_resp.status_code == 201
    dps_build_id = dps_resp.json()["id"]

    sup_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "B5SupBuild", "agent_id": str(sup_agent.id)},
    )
    assert sup_resp.status_code == 201
    sup_build_id = sup_resp.json()["id"]

    # Ensure build objects are loaded (needed for snapshot creation).
    await db.get(Build, dps_build_id)
    await db.get(Build, sup_build_id)

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "B5Team", "build1_id": dps_build_id, "build2_id": sup_build_id},
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "B5Combo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "BA1"}],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    return {
        "team_id": team_id,
        "dps_build_id": dps_build_id,
        "sup_build_id": sup_build_id,
        "combo_id": combo_id,
        "attack_id": str(attack.id),
        "sup_attack_name": sup_attack.name,
        "enemy_id": str(enemy.id),
    }


async def _seed_team_with_dps_discs(
    authed_client: AsyncClient,
    db: AsyncSession,
    owner_id: str,
) -> dict:
    """The B5 two-agent team fixture, plus six owned+equipped discs on the DPS build."""
    s = await _seed_two_agent_team(authed_client, db, owner_id)

    disc_set = DiscSet(
        hakushin_id=8950,
        name="B3Set",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    db.add(disc_set)
    await db.flush()

    slot_mains = [
        (1, StatType.HP, 2200),
        (2, StatType.ATK, 316),
        (3, StatType.DEF, 200),
        (4, StatType.CRIT_RATE, 2400),
        (5, StatType.ATK_PCT, 3000),
        (6, StatType.ATK_PCT, 3000),
    ]
    disc_ids: dict[int, str] = {}
    for slot, stat, val in slot_mains:
        resp = await authed_client.post(
            "/api/v1/discs",
            json={
                "disc_set_id": str(disc_set.id),
                "slot": slot,
                "rarity": "S",
                "level": 15,
                "main_stat_type": stat.value,
                "main_stat_value": val,
                "substats": [],
            },
        )
        assert resp.status_code == 201, resp.text
        disc_ids[slot] = resp.json()["id"]

    equip_resp = await authed_client.patch(
        f"/api/v1/builds/{s['dps_build_id']}/equip-discs",
        json={"discs": {str(k): v for k, v in disc_ids.items()}},
    )
    assert equip_resp.status_code == 200, equip_resp.text

    s["disc_ids"] = disc_ids
    s["disc_set_id"] = str(disc_set.id)
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_calculate_returns_200_with_by_agent(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Team-owned combo with matching team_id → 200 + by_agent breakdown."""
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Basic shape.
    assert data["total_damage"] > 0
    assert "by_agent" in data
    assert len(data["by_agent"]) > 0

    # Sum of per-agent damage equals grand total.
    total_by_agent = sum(int(a["damage"]) for a in data["by_agent"])
    assert total_by_agent == data["total_damage"]

    # DPS is the primary (slot 1) build.
    assert data["dps_agent_name"] == "B5DPS"


@pytest.mark.asyncio
async def test_team_calculate_rejects_combo_mismatch(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Combo owned by a different team → 422."""
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    # Create a second team and a combo for it.
    other_team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "OtherTeam", "build1_id": s["dps_build_id"]},
    )
    assert other_team_resp.status_code == 201
    other_team_id = other_team_resp.json()["id"]

    other_combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={"name": "OtherCombo", "team_id": other_team_id},
    )
    assert other_combo_resp.status_code == 201
    other_combo_id = other_combo_resp.json()["id"]

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": other_combo_id,
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_team_calculate_rejects_unknown_step_agent_id(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Step with an agent_id that doesn't reference any team member → 422."""
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    # Patch the combo sequence to carry an unknown agent_id on the step.
    bad_combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "BadAgentCombo",
            "team_id": s["team_id"],
            "sequence": [
                {
                    "attack_id": s["attack_id"],
                    "label": "BA1",
                    "agent_id": "00000000-0000-0000-0000-000000000000",
                }
            ],
        },
    )
    assert bad_combo_resp.status_code == 201
    bad_combo_id = bad_combo_resp.json()["id"]

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": bad_combo_id,
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_team_calculate_support_owned_step_contributes_damage(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """A combo step owned by the support (by build UUID, via move_name) resolves
    against the support's own agent and contributes damage in by_agent.

    Regression: the team /calculate path used to resolve every step against the
    primary build, so a support-owned move_name step 404'd (the move only exists
    on the support's agent).
    """
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    # Combo: DPS basic attack + a support-owned skill (tagged with the support
    # build UUID, referenced by move_name).
    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "MultiAgentCombo",
            "team_id": s["team_id"],
            "sequence": [
                {"attack_id": s["attack_id"], "label": "BA1"},
                {
                    "move_name": s["sup_attack_name"],
                    "label": "SupSkill",
                    "agent_id": s["sup_build_id"],
                },
            ],
        },
    )
    assert combo_resp.status_code == 201, combo_resp.text
    combo_id = combo_resp.json()["id"]

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": combo_id, "enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    by_agent = {a["build_id"]: a["damage"] for a in data["by_agent"]}
    # Both members contribute non-zero damage.
    assert by_agent.get(s["dps_build_id"], 0) > 0
    assert by_agent.get(s["sup_build_id"], 0) > 0
    # Per-agent contributions sum to the grand total.
    assert sum(int(d) for d in by_agent.values()) == data["total_damage"]


@pytest.mark.asyncio
async def test_team_calculate_without_attribution_flag_is_unchanged(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Default payload (Task B2 acceptance): no attribution/formulas/roster."""
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["buff_roster"] == []
    for step in data["steps"]:
        if "attribution" in step:
            assert step["attribution"] is None
            assert step["zone_formulas"] is None


@pytest.mark.asyncio
async def test_team_calculate_with_attribution_flag_populates_breakdown(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """``with_attribution=true`` (Task B2) returns per-step attribution +
    zone_formulas and a build-level buff_roster; totals are unchanged."""
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    baseline = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert baseline.status_code == 200, baseline.text

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "with_attribution": True,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Totals are identical regardless of the flag -- attribution is purely
    # additive, never a second arithmetic path.
    assert data["total_damage"] == baseline.json()["total_damage"]

    damage_steps = [s for s in data["steps"] if "attribution" in s]
    assert damage_steps, "expected at least one damage step in the response"
    for step in damage_steps:
        assert step["attribution"] is not None
        assert step["zone_formulas"] is not None
        # zone_formulas' result_bp must match the step's own *_mult fields
        # (attribution never re-derives numbers the calculator already produced).
        assert step["zone_formulas"]["boost"]["result_bp"] == step["boost_mult"]
        assert step["zone_formulas"]["def"]["result_bp"] == step["def_mult"]

    assert isinstance(data["buff_roster"], list)


# ---------------------------------------------------------------------------
# Issue #94 — request-scoped stack_counts must reach each member's own
# snapshot in the Phase 5B (with_attribution) path.
# ---------------------------------------------------------------------------

_STACK_ME_MODULE_TARGET = "app.services.snapshot_builder.load_agent_modifiers"
_STACK_ME = Modifier(
    stat="atk_pct",
    value=1000,
    source=ModifierSource.EXTERNAL,
    source_label="test:team_stack_me",
    target=ModifierTarget.SELF,
    conditions=(Condition.ALWAYS,),
    scopes=(AttackScope.ALL,),
    max_stacks=4,
)


async def _attributed_total(
    authed_client: AsyncClient,
    team_id: str,
    combo_id: str,
    enemy_id: str,
    stack_counts: dict[str, int],
) -> int:
    resp = await authed_client.post(
        f"/api/v1/teams/{team_id}/calculate",
        json={
            "combo_id": combo_id,
            "enemy_profile_id": enemy_id,
            "with_attribution": True,
            "stack_counts": stack_counts,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["total_damage"]


@pytest.mark.asyncio
async def test_request_stack_counts_reaches_attributed_team_calc(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """DESIGN §2.1 / issue #94: stack_counts must reach the Phase 5B calc.

    The Phase 5B (``with_attribution=True``) path resolves each acting
    member's stacks straight off that member's own ``member_snapshots``
    entry (``anomaly_simulator``'s per-step ``ActiveConditions`` is built
    from ``builds[acting_agent_id].stack_counts``), not from the merged
    request ``conditions``. Before ``_load_team_context`` threaded
    ``stack_counts`` into each ``build_snapshot_from_db`` call, this request
    field was silently ignored on this path and every member's stacks came
    from that build's own DB column instead.
    """
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    with patch(_STACK_ME_MODULE_TARGET, return_value=[_STACK_ME]):
        one_stack = await _attributed_total(
            authed_client, s["team_id"], s["combo_id"], s["enemy_id"], {"test:team_stack_me": 1}
        )
        four_stacks = await _attributed_total(
            authed_client, s["team_id"], s["combo_id"], s["enemy_id"], {"test:team_stack_me": 4}
        )

    assert four_stacks > one_stack, (
        "with_attribution=True did not scale 'test:team_stack_me' from 1 to "
        f"4 stacks via the request's stack_counts (total_damage {four_stacks} "
        f"at 4 stacks vs {one_stack} at 1 stack)."
    )


@pytest.mark.asyncio
async def test_build_stack_counts_column_does_not_affect_attributed_team_calc(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """The build's own ``stack_counts`` column is not a server fallback here either."""
    user, _ = authed_user
    s = await _seed_two_agent_team(authed_client, db_session, str(user.id))

    with patch(_STACK_ME_MODULE_TARGET, return_value=[_STACK_ME]):
        before = await _attributed_total(
            authed_client, s["team_id"], s["combo_id"], s["enemy_id"], {"test:team_stack_me": 1}
        )

        # 2, not 4: ActiveConditions.get_stacks falls back to `max_stacks` for an
        # *unset* key (modifiers.py -- `stack_counts.get(source_label, max_stacks)`),
        # and _STACK_ME's max_stacks is 4. A column value of 4 therefore resolves
        # identically to the empty column above, so this assertion would hold even
        # with the leak fully present. Keep the patched value != max_stacks or the
        # test stops discriminating.
        patch_resp = await authed_client.patch(
            f"/api/v1/builds/{s['dps_build_id']}",
            json={"stack_counts": {"test:team_stack_me": 2}},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        after = await _attributed_total(
            authed_client, s["team_id"], s["combo_id"], s["enemy_id"], {"test:team_stack_me": 1}
        )

    assert after == before, (
        f"mutating build.stack_counts changed the with_attribution result "
        f"({before} -> {after}) for a fixed request context. DESIGN §2.1 -- "
        "the column is a client-read default, never a server fallback."
    )


# ---------------------------------------------------------------------------
# Task B3 — keystone endpoint POST /teams/{team_id}/evaluate-discs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_discs_with_equipped_ids_matches_calculate(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Overriding with the equipped six (disc_ids) reproduces /calculate exactly,
    and always returns full attribution (no with_attribution flag needed)."""
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))

    baseline = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "with_attribution": True,
        },
    )
    assert baseline.status_code == 200, baseline.text

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "active_index": 0,
            "disc_ids": list(s["disc_ids"].values()),
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_damage"] == baseline.json()["total_damage"]
    assert data["dps_agent_name"] == "B5DPS"

    damage_steps = [st for st in data["steps"] if "attribution" in st]
    assert damage_steps
    for step in damage_steps:
        assert step["attribution"] is not None
        assert step["zone_formulas"] is not None
    assert isinstance(data["buff_roster"], list)


@pytest.mark.asyncio
async def test_evaluate_discs_with_inline_stats_overrides_equipped(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Inline disc_stats (an unpersisted candidate) replace the equipped set and
    change the result -- proving the override is actually applied."""
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))

    baseline = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert baseline.status_code == 200, baseline.text

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "active_index": 0,
            "disc_stats": [
                {"main_stat_type": "hp", "main_stat_value": 2200, "substats": []},
                {"main_stat_type": "atk", "main_stat_value": 316, "substats": []},
                {"main_stat_type": "def", "main_stat_value": 200, "substats": []},
                {"main_stat_type": "crit_rate", "main_stat_value": 2400, "substats": []},
                {"main_stat_type": "atk_pct", "main_stat_value": 9000, "substats": []},
                {"main_stat_type": "atk_pct", "main_stat_value": 9000, "substats": []},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Much higher ATK% substats than the equipped set -> more total damage.
    assert data["total_damage"] > baseline.json()["total_damage"]


@pytest.mark.asyncio
async def test_evaluate_discs_rejects_both_disc_sources(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "disc_ids": list(s["disc_ids"].values()),
            "disc_stats": [{"main_stat_type": "atk", "main_stat_value": 316, "substats": []}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_evaluate_discs_rejects_neither_disc_source(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Task B4 — delta decomposition vs. a comparison build
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_discs_without_compare_to_has_no_delta(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Default payload (no compare_to/compare_to_disc_ids) -- delta is None,
    matching every other pre-B4 evaluate-discs/calculate response."""
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "disc_ids": list(s["disc_ids"].values()),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["delta"] is None


@pytest.mark.asyncio
async def test_evaluate_discs_compare_to_equipped_decomposes_the_gain(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """``compare_to: "equipped"`` diffs the inline candidate against the
    build's currently-equipped discs; zone_deltas' gain_share_pct sums to
    ~100% and the ratios telescope back to the real total ratio."""
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "disc_stats": [
                {"main_stat_type": "hp", "main_stat_value": 2200, "substats": []},
                {"main_stat_type": "atk", "main_stat_value": 316, "substats": []},
                {"main_stat_type": "def", "main_stat_value": 200, "substats": []},
                {"main_stat_type": "crit_rate", "main_stat_value": 2400, "substats": []},
                {"main_stat_type": "atk_pct", "main_stat_value": 9000, "substats": []},
                {"main_stat_type": "atk_pct", "main_stat_value": 9000, "substats": []},
            ],
            "compare_to": "equipped",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    baseline = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert baseline.status_code == 200, baseline.text

    delta = data["delta"]
    assert delta is not None
    assert delta["from_total"] == baseline.json()["total_damage"]
    assert delta["to_total"] == data["total_damage"]
    assert delta["to_total"] > delta["from_total"]

    zone_deltas = delta["zone_deltas"]
    assert zone_deltas
    assert sum(z["gain_share_pct"] for z in zone_deltas) == pytest.approx(100.0, abs=0.5)

    product = 1.0
    for z in zone_deltas:
        product *= z["ratio"]
    assert delta["from_total"] * product == pytest.approx(delta["to_total"], rel=1e-3)


@pytest.mark.asyncio
async def test_evaluate_discs_compare_to_disc_ids_identical_set_is_a_no_op_delta(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Comparing the candidate against itself (via compare_to_disc_ids) ->
    every zone ratio 1.0, from_total == to_total."""
    user, _ = authed_user
    s = await _seed_team_with_dps_discs(authed_client, db_session, str(user.id))
    equipped_ids = list(s["disc_ids"].values())

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/evaluate-discs",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "disc_ids": equipped_ids,
            "compare_to_disc_ids": equipped_ids,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    delta = data["delta"]
    assert delta is not None
    assert delta["from_total"] == delta["to_total"] == data["total_damage"]
    for z in delta["zone_deltas"]:
        assert z["ratio"] == pytest.approx(1.0)
        assert z["gain_share_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# A build cannot occupy two slots on the same team
#
# Rejected rather than reconciled, because no consumer reads it correctly.
# `_load_team_context` keeps the duplicate in `slot_build_ids` (a list) and so in
# `all_members`, putting the primary in its own support list, while its `builds`
# and `member_snapshots` dicts collapse to one entry -- one request, two members,
# one build. Every index-based support selection lands in the same place from the
# other side. Surfaced by the PR #120 review; see docs/DECISIONS.md.
# ---------------------------------------------------------------------------


async def _two_builds(authed_client: AsyncClient, db: AsyncSession) -> tuple[str, str]:
    """Two builds on two distinct agents, ready to be slotted into a team."""
    agents = [
        Agent(
            hakushin_id=8801 + i,
            name=f"DupSlot{i}",
            element=Element.ICE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=900,
            base_hp=8000,
            base_def=600,
        )
        for i in range(2)
    ]
    db.add_all(agents)
    await db.flush()

    ids = []
    for i, a in enumerate(agents):
        resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": f"DupSlotBuild{i}", "agent_id": str(a.id)},
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids[0], ids[1]


@pytest.mark.parametrize(
    ("slot_a", "slot_b"),
    [("build1_id", "build2_id"), ("build1_id", "build3_id"), ("build2_id", "build3_id")],
)
async def test_create_team_rejects_the_same_build_in_two_slots(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    slot_a: str,
    slot_b: str,
) -> None:
    """Every pair of slots is covered, not just the primary/support one."""
    build_id, other_id = await _two_builds(authed_client, db_session)
    body = {"name": "DupTeam", "build1_id": other_id, slot_a: build_id, slot_b: build_id}

    resp = await authed_client.post("/api/v1/teams", json=body)

    assert resp.status_code == 422, resp.text
    assert "more than one slot" in resp.text


async def test_create_team_still_accepts_three_distinct_builds(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The guard must not reject the ordinary case, or partially-filled teams."""
    a, b = await _two_builds(authed_client, db_session)

    full = await authed_client.post(
        "/api/v1/teams", json={"name": "OkTeam", "build1_id": a, "build2_id": b}
    )
    assert full.status_code == 201, full.text

    # Two empty slots are both None -- None is not a duplicate.
    solo = await authed_client.post("/api/v1/teams", json={"name": "SoloTeam", "build1_id": a})
    assert solo.status_code == 201, solo.text


async def test_patch_rejects_a_duplicate_only_visible_after_merging(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The case a body-only validator cannot see.

    The patch carries a single slot, so it is internally consistent; it is a
    duplicate only against the id the persisted row already holds.
    """
    a, b = await _two_builds(authed_client, db_session)
    created = await authed_client.post(
        "/api/v1/teams", json={"name": "PatchTeam", "build1_id": a, "build2_id": b}
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]

    resp = await authed_client.patch(f"/api/v1/teams/{team_id}", json={"build2_id": a})

    assert resp.status_code == 422, resp.text
    assert "more than one slot" in resp.text

    # The row is untouched by the rejected patch.
    after = await authed_client.get(f"/api/v1/teams/{team_id}")
    assert after.json()["build2_id"] == b


async def test_patch_that_does_not_touch_slots_is_unaffected(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A name-only patch must not pay for the merged-slot check."""
    a, b = await _two_builds(authed_client, db_session)
    created = await authed_client.post(
        "/api/v1/teams", json={"name": "RenameTeam", "build1_id": a, "build2_id": b}
    )
    assert created.status_code == 201, created.text

    resp = await authed_client.patch(
        f"/api/v1/teams/{created.json()['id']}", json={"name": "Renamed"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed"


async def test_patch_touching_a_slot_on_an_unknown_team_is_still_404(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The merged-slot check reads the row first, so it owns the 404 for slot patches.

    ``repo.get_by_id`` is owner-scoped, so this also covers another user's team id:
    the pre-read must not leak it as a 422 or a 200 before ``repo.update``'s own
    404 would have fired.
    """
    a, _ = await _two_builds(authed_client, db_session)
    missing = "01930000-0000-7000-8000-000000000000"

    resp = await authed_client.patch(f"/api/v1/teams/{missing}", json={"build1_id": a})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Team not found"
