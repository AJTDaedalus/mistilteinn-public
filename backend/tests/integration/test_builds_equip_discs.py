"""Integration tests for PATCH /builds/{id}/equip-discs (Page Plan A6)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.models.agent import Agent
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.w_engine import WEngine

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(db_session: AsyncSession, authed_client: AsyncClient) -> dict:
    """Seed two builds each with 6 discs (2 disc sets)."""
    agent = Agent(
        hakushin_id=8800,
        name="EquipAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=800,
        base_hp=7000,
        base_def=500,
    )
    agent2 = Agent(
        hakushin_id=8803,
        name="EquipAgent2",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=800,
        base_hp=7000,
        base_def=500,
    )
    engine = WEngine(
        hakushin_id=8801,
        name="EquipEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=500,
    )
    set_a = DiscSet(
        hakushin_id=8900,
        name="EqSetA",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    set_b = DiscSet(
        hakushin_id=8901,
        name="EqSetB",
        two_piece_text="ATK +8%",
        four_piece_text="DMG +12%",
    )
    db_session.add_all([agent, agent2, engine, set_a, set_b])
    await db_session.flush()

    build1_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "EquipBuild1",
            "agent_id": str(agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    build2_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "EquipBuild2",
            "agent_id": str(agent2.id),
            "w_engine_id": str(engine.id),
        },
    )
    build1_id = build1_resp.json()["id"]
    build2_id = build2_resp.json()["id"]

    # Equip build1 with set_a discs, build2 with set_b discs.
    slot_mains = [
        (DiscSlot.ONE, StatType.HP),
        (DiscSlot.TWO, StatType.ATK),
        (DiscSlot.THREE, StatType.DEF),
        (DiscSlot.FOUR, StatType.CRIT_RATE),
        (DiscSlot.FIVE, StatType.ATK_PCT),
        (DiscSlot.SIX, StatType.CRIT_DMG),
    ]
    build1_discs: dict[int, str] = {}
    build2_discs: dict[int, str] = {}
    for slot_enum, main_stat in slot_mains:
        d1 = Disc(
            disc_set_id=str(set_a.id),
            rarity=Rarity.S,
            slot=slot_enum,
            level=15,
            main_stat_type=main_stat,
            main_stat_value=1000,
            substats=[],
            build_id=build1_id,
        )
        d2 = Disc(
            disc_set_id=str(set_b.id),
            rarity=Rarity.S,
            slot=slot_enum,
            level=15,
            main_stat_type=main_stat,
            main_stat_value=1000,
            substats=[],
            build_id=build2_id,
        )
        db_session.add_all([d1, d2])
        await db_session.flush()
        slot_int = slot_enum.value if hasattr(slot_enum, "value") else int(slot_enum)
        build1_discs[slot_int] = str(d1.id)
        build2_discs[slot_int] = str(d2.id)

    await db_session.commit()
    return {
        "build1_id": build1_id,
        "build2_id": build2_id,
        "build1_discs": build1_discs,
        "build2_discs": build2_discs,
    }


async def test_equip_all_happy_path(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """PATCH equip-discs replaces all 6 slots and returns the updated build."""
    s = await _seed(db_session, authed_client)

    # Equip build1 with its own discs (should be a no-op structurally).
    payload = {"discs": {str(k): v for k, v in s["build1_discs"].items()}}
    resp = await authed_client.patch(f"/api/v1/builds/{s['build1_id']}/equip-discs", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == s["build1_id"]


async def test_equip_all_steals_from_other_build(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Discs currently on build2 can be reassigned to build1."""
    s = await _seed(db_session, authed_client)

    # Assign build2's discs to build1.
    payload = {"discs": {str(k): v for k, v in s["build2_discs"].items()}}
    resp = await authed_client.patch(f"/api/v1/builds/{s['build1_id']}/equip-discs", json=payload)
    assert resp.status_code == 200, resp.text

    # Verify via GET that build2 now has no discs equipped.
    build2_resp = await authed_client.get(f"/api/v1/builds/{s['build2_id']}")
    assert build2_resp.status_code == 200


async def test_equip_all_wrong_slot_returns_422(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A disc assigned to the wrong slot returns 422."""
    s = await _seed(db_session, authed_client)

    # Swap slots 1 and 2 to force a slot mismatch.
    bad = dict(s["build1_discs"])
    bad[1], bad[2] = bad[2], bad[1]
    payload = {"discs": {str(k): v for k, v in bad.items()}}
    resp = await authed_client.patch(f"/api/v1/builds/{s['build1_id']}/equip-discs", json=payload)
    assert resp.status_code == 422


async def test_equip_all_unknown_disc_returns_422(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A disc UUID that doesn't exist returns 422."""
    s = await _seed(db_session, authed_client)

    bad = dict(s["build1_discs"])
    bad[1] = str(uuid.uuid4())  # non-existent disc
    payload = {"discs": {str(k): v for k, v in bad.items()}}
    resp = await authed_client.patch(f"/api/v1/builds/{s['build1_id']}/equip-discs", json=payload)
    assert resp.status_code == 422


async def test_equip_all_atomic_rollback(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """If one disc is invalid, no changes are committed."""
    s = await _seed(db_session, authed_client)

    # Make slot 6 reference a non-existent disc — should cause rollback.
    bad = dict(s["build1_discs"])
    bad[6] = str(uuid.uuid4())
    payload = {"discs": {str(k): v for k, v in bad.items()}}
    resp = await authed_client.patch(f"/api/v1/builds/{s['build1_id']}/equip-discs", json=payload)
    assert resp.status_code == 422

    # Build1 should still have its original discs (the session rolled back).
    get_resp = await authed_client.get(f"/api/v1/builds/{s['build1_id']}")
    assert get_resp.status_code == 200


async def test_equip_all_unknown_build_returns_404(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A build UUID that doesn't exist returns 404."""
    s = await _seed(db_session, authed_client)

    payload = {"discs": {str(k): v for k, v in s["build1_discs"].items()}}
    resp = await authed_client.patch(
        f"/api/v1/builds/{uuid.uuid4()}/equip-discs",
        json=payload,
    )
    assert resp.status_code == 404
