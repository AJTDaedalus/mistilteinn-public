"""Correcting the stock a plan is priced against, end to end over HTTP.

`docs/DESIGN_planner_materials.md`. The cases here are the ones where a wrong answer looks
right: an edit that appears to save and does not, a zero that reads as "imported nothing", and
an import that silently discards a correction — which is deliberate, and therefore has to be
pinned rather than left to be rediscovered as a bug.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import pytest

from app.models.enums import UserStatus
from app.models.planner import Material, UserMaterial
from app.models.user import User
from app.services.planner.stock import MAX_COUNT

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


#: Teachings of Freedom, as `test_planner_endpoints.py` uses it.
TEACHINGS = 104301
#: Shivada Jade Sliver.
SLIVER = 104161
#: Sakura Bloom — a local specialty, and **rarity 0**. Present here because rarity 0 means
#: *unranked* rather than worst, and the list must not bury it.
SPECIALTY = 101202


def _auth(authed_user: tuple[User, str]) -> dict[str, str]:
    _, token = authed_user
    return {"Authorization": f"Bearer {token}"}


async def _materials(db_session: AsyncSession) -> None:
    for material_id, name, rarity in (
        (TEACHINGS, "Teachings of Freedom", 2),
        (SLIVER, "Shivada Jade Sliver", 2),
        (SPECIALTY, "Sakura Bloom", 0),
    ):
        db_session.add(
            Material(
                id=material_id,
                name=name,
                icon=f"UI_ItemIcon_{material_id}",
                rarity=rarity,
            ),
        )
    await db_session.flush()


@pytest.mark.asyncio
async def test_an_edit_is_readable_afterwards(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    await _materials(db_session)
    await db_session.commit()

    patched = await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": TEACHINGS, "count": 40}]},
        headers=_auth(authed_user),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json() == [
        {
            "material_id": TEACHINGS,
            "name": "Teachings of Freedom",
            "icon": f"UI_ItemIcon_{TEACHINGS}",
            "rarity": 2,
            "count": 40,
        },
    ]

    listed = await client.get("/api/v1/planner/materials", headers=_auth(authed_user))
    assert listed.status_code == 200
    body = listed.json()
    assert body["owned_count"] == 1
    # **Owned first**, which is the whole of the sort contract a bulk fix depends on.
    assert body["items"][0]["material_id"] == TEACHINGS
    assert {item["material_id"]: item["count"] for item in body["items"]} == {
        TEACHINGS: 40,
        SLIVER: 0,
        SPECIALTY: 0,
    }


@pytest.mark.asyncio
async def test_only_the_named_rows_are_touched(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """The reason the route is a `PATCH` and its body cannot express an inventory.

    A whole-inventory `PUT` built from a *filtered* view would delete every material the
    filter was hiding, so this asserts the untouched row survives rather than that the touched
    one changed.
    """
    user, _ = authed_user
    await _materials(db_session)
    db_session.add(UserMaterial(owner_id=user.id, material_id=SLIVER, count=7))
    await db_session.commit()

    await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": TEACHINGS, "count": 3}]},
        headers=_auth(authed_user),
    )

    listed = (
        await client.get("/api/v1/planner/materials", headers=_auth(authed_user))
    ).json()
    counts = {item["material_id"]: item["count"] for item in listed["items"]}
    assert counts[SLIVER] == 7
    assert counts[TEACHINGS] == 3


@pytest.mark.asyncio
async def test_a_zero_deletes_the_row_rather_than_storing_it(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """Measured, not assumed: `service.py` computes `stock_is_empty=not stock`.

    A stored zero is a second spelling of "none" — and the spelling that makes an account
    which has never imported anything look stocked, losing the banner that tells the user so.
    """
    user, _ = authed_user
    await _materials(db_session)
    db_session.add(UserMaterial(owner_id=user.id, material_id=TEACHINGS, count=5))
    await db_session.commit()

    await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": TEACHINGS, "count": 0}]},
        headers=_auth(authed_user),
    )

    remaining = await db_session.execute(
        UserMaterial.__table__.select().where(UserMaterial.owner_id == user.id),
    )
    assert remaining.all() == []


@pytest.mark.asyncio
async def test_a_count_at_the_column_ceiling_round_trips(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """`int4`'s maximum is accepted; one more is refused before it can reach asyncpg."""
    await _materials(db_session)
    await db_session.commit()

    accepted = await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": TEACHINGS, "count": MAX_COUNT}]},
        headers=_auth(authed_user),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()[0]["count"] == MAX_COUNT

    refused = await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": TEACHINGS, "count": MAX_COUNT + 1}]},
        headers=_auth(authed_user),
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_material_is_refused_by_name(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """An export newer than the seeded patch is the usual cause, and the user can act on
    being told which id — where a silent drop leaves a number that appears to save."""
    await _materials(db_session)
    await db_session.commit()

    response = await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": 999_999, "count": 1}]},
        headers=_auth(authed_user),
    )
    assert response.status_code == 422
    assert "999999" in response.json()["detail"]


@pytest.mark.asyncio
async def test_one_bad_row_writes_none_of_them(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """A partial write is the failure mode where a user fixes several numbers, sees an error,
    and cannot tell which landed."""
    await _materials(db_session)
    await db_session.commit()

    response = await client.patch(
        "/api/v1/planner/materials",
        json={
            "counts": [
                {"material_id": TEACHINGS, "count": 40},
                {"material_id": 999_999, "count": 1},
            ],
        },
        headers=_auth(authed_user),
    )
    assert response.status_code == 422

    listed = (
        await client.get("/api/v1/planner/materials", headers=_auth(authed_user))
    ).json()
    assert listed["owned_count"] == 0


@pytest.mark.asyncio
async def test_an_import_replaces_a_hand_typed_count(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """**The ruling, pinned.** `DESIGN_planner_materials.md` §2.

    `/roster` answers the identical question the other way — `source: manual` is exactly what
    stops an import undoing a user's answer there — so this divergence has to be a decision
    with a test on it rather than a behaviour someone later reads as a bug and "fixes".

    "Do I own Ayaka" is durable; "how many Teachings do I hold" is a reading that goes stale
    within a day, and *invisibly*. The failure mode chosen here is the one the user can see.
    """
    await _materials(db_session)
    await db_session.commit()

    await client.patch(
        "/api/v1/planner/materials",
        json={"counts": [{"material_id": TEACHINGS, "count": 40}]},
        headers=_auth(authed_user),
    )

    imported = await client.post(
        "/api/v1/artifacts/import/good",
        json={
            "mode": "replace",
            "payload": {
                "format": "GOOD",
                "version": 3,
                "source": "Inventory Kamera",
                "artifacts": [],
                "materials": {"TeachingsOfFreedom": 2},
            },
        },
        headers=_auth(authed_user),
    )
    assert imported.status_code == 200, imported.text

    listed = (
        await client.get("/api/v1/planner/materials", headers=_auth(authed_user))
    ).json()
    counts = {item["material_id"]: item["count"] for item in listed["items"]}
    assert counts[TEACHINGS] == 2


@pytest.mark.asyncio
async def test_one_account_cannot_see_anothers_stock(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    await _materials(db_session)
    other = User(
        email=f"other_{secrets.token_hex(4)}@test.example",
        label="Someone Else",
        password_hash="x",  # noqa: S106 — never authenticated as
        status=UserStatus.APPROVED,
    )
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        UserMaterial(owner_id=other.id, material_id=TEACHINGS, count=9999),
    )
    await db_session.commit()

    listed = (
        await client.get("/api/v1/planner/materials", headers=_auth(authed_user))
    ).json()
    assert listed["owned_count"] == 0


@pytest.mark.asyncio
async def test_both_routes_require_a_caller(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/planner/materials")).status_code == 401
    assert (
        await client.patch("/api/v1/planner/materials", json={"counts": []})
    ).status_code == 401
