"""Integration tests for Task 8 — fluxed_element API contract (DESIGN_remielle.md §5.3).

Covers the three acceptance bullets:
1. A solo-agent calc with no team returns ``fluxed_element: null`` and pure
   Lumiflux damage (no attribute DMG% bonus, RES contribution 0).
2. An explicit ``fluxed_element`` override in the request wins over the
   derived value and is echoed back.
3. The disc optimizer's top-K union field keys off the *fluxed* element's
   ``<element>_dmg`` disc stat, not ``agent_element`` (which is
   ``"lumiflux"`` and has no such bucket by design — DESIGN §4.2).

Synthetic Lumiflux agents (not the real seeded Remielle row) are used
throughout, mirroring the existing ``_seed_two_agent_team``-style fixtures
in ``test_teams.py`` / ``test_optimizer_team_combo.py`` — ``Element.LUMIFLUX``
is a real enum member (Task 2), so this needs no dependency on the live DB's
Remielle row (id 300).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.damage_calculator import CritMode
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
    optimize_discs,
)
from app.services.modifiers import ActiveConditions, AttackScope, Condition

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Shared seed helpers
# ---------------------------------------------------------------------------


async def _seed_solo_lumiflux_build(
    authed_client: AsyncClient,
    db: AsyncSession,
) -> dict:
    """One Lumiflux agent, no team, one attack, one enemy."""
    agent = Agent(
        hakushin_id=8300,
        name="T8Solo",
        element=Element.LUMIFLUX,
        specialty=Specialty.ANOMALY,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    enemy = EnemyProfile(name="T8Dummy", level=60, defense=60, physical_res=2000)
    db.add_all([agent, enemy])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=830,
        skill_key="Basic",
        name="T8 Basic",
        hit_index=0,
        element=Element.LUMIFLUX,
        damage_base=10_000,
        damage_growth=0,
    )
    db.add(attack)
    await db.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "T8SoloBuild", "agent_id": str(agent.id)},
    )
    assert build_resp.status_code == 201, build_resp.text
    build_id = build_resp.json()["id"]
    await db.get(Build, build_id)

    return {
        "build_id": build_id,
        "attack_id": str(attack.id),
        "enemy_id": str(enemy.id),
    }


async def _seed_lumiflux_team(
    authed_client: AsyncClient,
    db: AsyncSession,
    *,
    support_element: Element = Element.PHYSICAL,
    with_support: bool = True,
) -> dict:
    """A Lumiflux DPS (slot 1) + one support (slot 2, default Physical).

    ``with_support=False`` seeds a solo (1-member) team instead — the
    "no other teammates" edge case, which ``resolve_fluxed_element``
    treats identically to a missing team (n<=1 -> None).
    """
    dps_agent = Agent(
        hakushin_id=8301,
        name="T8DPS",
        element=Element.LUMIFLUX,
        specialty=Specialty.ANOMALY,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    enemy = EnemyProfile(name="T8TeamDummy", level=60, defense=60, physical_res=1500, ice_res=500)
    db.add_all([dps_agent, enemy])
    await db.flush()

    dps_attack = Attack(
        agent_id=dps_agent.id,
        hakushin_skill_id=831,
        skill_key="Basic",
        name="T8 DPS Basic",
        hit_index=0,
        element=Element.LUMIFLUX,
        damage_base=10_000,
        damage_growth=0,
    )
    db.add(dps_attack)
    await db.flush()

    dps_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "T8DPSBuild", "agent_id": str(dps_agent.id)},
    )
    assert dps_resp.status_code == 201, dps_resp.text
    dps_build_id = dps_resp.json()["id"]
    await db.get(Build, dps_build_id)

    team_payload = {"name": "T8Team", "build1_id": dps_build_id}

    sup_build_id = None
    if with_support:
        sup_agent = Agent(
            hakushin_id=8302,
            name="T8Sup",
            element=support_element,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_atk=500,
            base_hp=10_000,
            base_def=700,
        )
        db.add(sup_agent)
        await db.flush()

        sup_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "T8SupBuild", "agent_id": str(sup_agent.id)},
        )
        assert sup_resp.status_code == 201, sup_resp.text
        sup_build_id = sup_resp.json()["id"]
        await db.get(Build, sup_build_id)
        team_payload["build2_id"] = sup_build_id

    team_resp = await authed_client.post("/api/v1/teams", json=team_payload)
    assert team_resp.status_code == 201, team_resp.text
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "T8Combo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(dps_attack.id), "label": "DPS BA1"}],
        },
    )
    assert combo_resp.status_code == 201, combo_resp.text
    combo_id = combo_resp.json()["id"]

    return {
        "team_id": team_id,
        "dps_build_id": dps_build_id,
        "sup_build_id": sup_build_id,
        "combo_id": combo_id,
        "enemy_id": str(enemy.id),
    }


# ---------------------------------------------------------------------------
# Acceptance 1 + 2: solo-agent calc (/damage/build) — no team available at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solo_build_no_team_returns_null_fluxed_element(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """No team_id anywhere in this endpoint -> derived fluxed_element is null,
    and the build still deals damage (pure Lumiflux: no attribute DMG% bonus,
    RES contribution 0 — this is the correct default, not a missing-team bug)."""
    s = await _seed_solo_lumiflux_build(authed_client, db_session)

    resp = await authed_client.post(
        "/api/v1/damage/build",
        json={
            "build_id": s["build_id"],
            "attack_id": s["attack_id"],
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["fluxed_element"] is None
    assert data["total"] > 0


@pytest.mark.asyncio
async def test_solo_build_explicit_override_is_echoed(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An explicit fluxed_element override wins over the (always-null, no-team)
    derived value and is echoed back verbatim."""
    s = await _seed_solo_lumiflux_build(authed_client, db_session)

    resp = await authed_client.post(
        "/api/v1/damage/build",
        json={
            "build_id": s["build_id"],
            "attack_id": s["attack_id"],
            "enemy_profile_id": s["enemy_id"],
            "fluxed_element": "physical",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["fluxed_element"] == "physical"


# ---------------------------------------------------------------------------
# Team-context derivation + override precedence (/teams/{id}/calculate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_calculate_derives_fluxed_element_from_next_slot(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """2-agent team [Lumiflux DPS, Physical support]: cyclic next-slot after
    the DPS (slot 1) is the support (slot 2) -> derived fluxed_element is
    "physical", with no override in the request."""
    s = await _seed_lumiflux_team(
        authed_client, db_session, support_element=Element.PHYSICAL
    )

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["fluxed_element"] == "physical"


@pytest.mark.asyncio
async def test_team_calculate_explicit_override_wins_over_derived(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Same team (derived value would be "physical") but the request pins
    "ice" explicitly -> override wins and is echoed, not the derived value."""
    s = await _seed_lumiflux_team(
        authed_client, db_session, support_element=Element.PHYSICAL
    )

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
            "fluxed_element": "ice",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["fluxed_element"] == "ice"


@pytest.mark.asyncio
async def test_team_calculate_solo_team_returns_null_fluxed_element(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A 1-member team has no next slot to flux into -- same documented
    no-flux default as no team at all (resolve_fluxed_element: n<=1 -> None)."""
    s = await _seed_lumiflux_team(authed_client, db_session, with_support=False)

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["fluxed_element"] is None


# ---------------------------------------------------------------------------
# Acceptance 3: disc_optimizer unions the fluxed element's <element>_dmg field
# ---------------------------------------------------------------------------


def _flux_union_inventory() -> list[DiscCandidate]:
    """6-slot inventory; slot 1 has a 6-disc bucket engineered so the
    damage-rank top-1 + crit_rate/crit_dmg top-3 union excludes "B" (a disc
    with a large physical_dmg main stat and nothing else) unless
    ``fluxed_element="physical"`` adds physical_dmg to the union fields.
    """

    def _disc(disc_id: str, slot: int, *, main_stat_type: str = "", main_stat_value: int = 0):
        return DiscCandidate(
            disc_id=disc_id,
            slot=slot,
            set_id=1,
            main_stat_type=main_stat_type,
            main_stat_value=main_stat_value,
        )

    slot1 = [
        _disc("A", 1, main_stat_type="crit_dmg", main_stat_value=6000),
        _disc("C1", 1, main_stat_type="crit_dmg", main_stat_value=5000),
        _disc("C2", 1, main_stat_type="crit_dmg", main_stat_value=4500),
        _disc("D1", 1, main_stat_type="crit_dmg", main_stat_value=1000),
        _disc("D2", 1, main_stat_type="crit_dmg", main_stat_value=800),
        _disc("B", 1, main_stat_type="physical_dmg", main_stat_value=5000),
    ]
    rest = [_disc(f"S{slot}", slot, main_stat_type="crit_dmg", main_stat_value=1000)
            for slot in range(2, 7)]
    return slot1 + rest


def _run_flux_union_optimizer(fluxed_element: str | None):
    base_build = BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="lumiflux",
    )
    enemy = EnemySnapshot(level=60, base_def=50, element_res=0)
    step = ComboStep(
        label="BA1",
        attack_id="a1",
        attack_name="Basic",
        scope=AttackScope.BASIC,
        multiplier=10_000,
        element="lumiflux",
    )
    inventory = _flux_union_inventory()
    constraints = OptimizerConstraints(top_n=1, prefilter_top_k=1)

    return optimize_discs(
        base_build=base_build,
        enemy=enemy,
        combo_steps=[step],
        inventory=inventory,
        disc_set_modifiers={1: []},
        constraints=constraints,
        conditions=ActiveConditions(active={Condition.ALWAYS}),
        crit_mode=CritMode.EXPECTED,
        fluxed_element=fluxed_element,
    )


def test_disc_optimizer_without_flux_prunes_the_physical_dmg_disc() -> None:
    """Baseline (no fluxed_element, matches pre-Task-8 behavior): an unfluxed
    Lumiflux build's damage never depends on physical_dmg, so "B" (whose only
    stat is physical_dmg) is pruned before it ever reaches evaluation --
    both by the lossless Pareto layer (dominated once physical_dmg is
    correctly probed as dead weight) and, had it survived that, by the
    top-K union prefilter (only crit_rate/crit_dmg are unioned)."""
    result = _run_flux_union_optimizer(fluxed_element=None)

    # Only "A" (the top crit_dmg disc) is ever scored for slot 1 -- "B"
    # never reaches the combo-evaluation loop.
    assert result.evaluated == 1
    assert result.builds[0].disc_ids[0] == "A"


def test_disc_optimizer_fluxed_element_unions_physical_dmg_not_lumiflux_dmg() -> None:
    """Direct proof of acceptance criterion 3: passing fluxed_element="physical"
    keeps physical_dmg live through both the Pareto layer and the top-K union
    prefilter (not the nonexistent lumiflux_dmg, which would have silently
    kept/unioned nothing -- the pre-Task-8 bug for a Lumiflux build), so "B"
    now survives to evaluation alongside "A"."""
    without_flux = _run_flux_union_optimizer(fluxed_element=None)
    with_flux = _run_flux_union_optimizer(fluxed_element="physical")

    assert without_flux.evaluated == 1
    assert with_flux.evaluated == 2
