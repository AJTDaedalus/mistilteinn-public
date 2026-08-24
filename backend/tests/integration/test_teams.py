"""Team endpoint tests — the duplicate-slot guard.

**Port state.** B.12 trimmed this file from 911 lines. fairy's version was mostly
`POST /teams/{id}/calculate` and `POST /teams/{id}/evaluate-discs` coverage; both routes and
everything behind them were deleted in B.6. What is kept is the slot-uniqueness guard, which
is game-neutral and is the one piece of non-obvious logic left in `api/v1/teams.py`: a PATCH
carrying a single slot is internally consistent and is a duplicate only once merged with the
persisted row, so the check has to read the row first — which also makes it own the 404.

`_two_builds` no longer POSTs to `/api/v1/builds` (deleted in B.6) and no longer needs an
`Agent`. It inserts `Build` skeleton rows directly. C.6 gives `Build` real columns; this
helper should grow with it rather than being replaced.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.schemas.team import TEAM_SLOTS

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


async def _two_builds(
    db: AsyncSession,
    authed_user: tuple[User, str],
) -> tuple[str, str]:
    """Two builds owned by the authenticated user, returned as ids."""
    user, _ = authed_user
    builds = [Build(owner_id=str(user.id), notes=f"DupSlotBuild{i}") for i in range(2)]
    db.add_all(builds)
    await db.flush()
    return str(builds[0].id), str(builds[1].id)


@pytest.mark.parametrize(
    ("slot_a", "slot_b"),
    # Derived from TEAM_SLOTS rather than listed. The hand-written version covered the three
    # pairs a ZZZ squad has; when the fourth Genshin slot arrived it would have kept passing
    # while testing three quarters of the surface.
    list(itertools.combinations(TEAM_SLOTS, 2)),
)
async def test_create_team_rejects_the_same_build_in_two_slots(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple[User, str],
    slot_a: str,
    slot_b: str,
) -> None:
    """Every pair of slots is covered, not just the primary/support one."""
    build_id, other_id = await _two_builds(db_session, authed_user)
    body = {"name": "DupTeam", "build1_id": other_id, slot_a: build_id, slot_b: build_id}

    resp = await authed_client.post("/api/v1/teams", json=body)

    assert resp.status_code == 422, resp.text
    assert "more than one slot" in resp.text


async def test_create_team_still_accepts_distinct_builds(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple[User, str],
) -> None:
    """The guard must not reject the ordinary case, or partially-filled teams."""
    a, b = await _two_builds(db_session, authed_user)

    full = await authed_client.post(
        "/api/v1/teams", json={"name": "OkTeam", "build1_id": a, "build2_id": b},
    )
    assert full.status_code == 201, full.text

    # Two empty slots are both None -- None is not a duplicate.
    solo = await authed_client.post("/api/v1/teams", json={"name": "SoloTeam", "build1_id": a})
    assert solo.status_code == 201, solo.text


async def test_patch_rejects_a_duplicate_only_visible_after_merging(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple[User, str],
) -> None:
    """The case a body-only validator cannot see.

    The patch carries a single slot, so it is internally consistent; it is a
    duplicate only against the id the persisted row already holds.
    """
    a, b = await _two_builds(db_session, authed_user)
    created = await authed_client.post(
        "/api/v1/teams", json={"name": "PatchTeam", "build1_id": a, "build2_id": b},
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
    authed_user: tuple[User, str],
) -> None:
    """A name-only patch must not pay for the merged-slot check."""
    a, b = await _two_builds(db_session, authed_user)
    created = await authed_client.post(
        "/api/v1/teams", json={"name": "RenameTeam", "build1_id": a, "build2_id": b},
    )
    assert created.status_code == 201, created.text

    resp = await authed_client.patch(
        f"/api/v1/teams/{created.json()['id']}", json={"name": "Renamed"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed"


async def test_patch_touching_a_slot_on_an_unknown_team_is_still_404(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple[User, str],
) -> None:
    """The merged-slot check reads the row first, so it owns the 404 for slot patches.

    ``repo.get_by_id`` is owner-scoped, so this also covers another user's team id:
    the pre-read must not leak it as a 422 or a 200 before ``repo.update``'s own
    404 would have fired.
    """
    a, _ = await _two_builds(db_session, authed_user)
    missing = "01930000-0000-7000-8000-000000000000"

    resp = await authed_client.patch(f"/api/v1/teams/{missing}", json={"build1_id": a})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Team not found"


# ---- A Genshin party is four ------------------------------------------------


async def test_a_team_holds_four_characters(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple[User, str],
) -> None:
    """The fork inherited three slots from ZZZ, where a squad is three agents.

    A Genshin party is four, and a rotation for one cannot be expressed against three slots
    at all — which is how this survived four chunks unnoticed: nothing had needed the fourth.
    """
    user, _ = authed_user
    builds = [Build(owner_id=str(user.id), notes=f"PartyBuild{i}") for i in range(4)]
    db_session.add_all(builds)
    await db_session.flush()

    body = {"name": "FullParty"} | {
        slot: str(build.id) for slot, build in zip(TEAM_SLOTS, builds, strict=True)
    }
    resp = await authed_client.post("/api/v1/teams", json=body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["build4_id"] == str(builds[3].id)


async def test_the_fourth_slot_is_covered_by_the_duplicate_guard(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple[User, str],
) -> None:
    """A slot the guard does not know about is a slot where the same build can sit twice."""
    build_id, other_id = await _two_builds(db_session, authed_user)

    resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "Dup4", "build1_id": build_id, "build4_id": build_id,
              "build2_id": other_id},
    )

    assert resp.status_code == 422, resp.text
    assert "more than one slot" in resp.text


async def test_the_slot_list_has_one_definition():
    """`TEAM_SLOTS` is what the model, schemas, repository and API all read.

    It was four hand-written lists before, and when three became four every one of them had
    to be found. This asserts the model's columns and the shared list agree, so a fifth slot
    (or a rename) cannot half-land.
    """
    from app.models.team import Team

    columns = {c.name for c in Team.__table__.columns if c.name.startswith("build")}
    assert columns == set(TEAM_SLOTS)
    assert len(TEAM_SLOTS) == 4
