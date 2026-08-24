"""A.1 — attaching a piece to a build.

`Artifact.build_id` existed on the model and in `ArtifactRead` from Chunk C, and **no
endpoint set it**. A user could import 800 artifacts and attach none of them, which is why
this comes first: it gates the build page's artifact panel, and the optimizer writing its
chosen five.

`uq_artifacts_build_slot` already enforces one piece per slot per build. As with
`uq_builds_owner_character` before T.1a, a constraint enforced only by the database is a 500
waiting for an ordinary action — so the rule is stated here, by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import Artifact, ArtifactSet
from app.models.build import Build
from app.models.character import Character
from app.models.enums import ArtifactSlot, Element, Rarity, StatType, WeaponType
from app.models.user import User

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

ARTIFACTS = "/api/v1/artifacts"
ABSENT = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def scene(db_session: AsyncSession, authed_user: tuple[User, str]) -> dict[str, str]:
    """A build, and three pieces: two flowers and a plume."""
    user, _ = authed_user
    character = Character(
        nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add_all([character, artifact_set])
    await db_session.flush()

    build = Build(owner_id=str(user.id), character_id=str(character.id))
    other_build = Build(owner_id=str(user.id), character_id=None)
    db_session.add_all([build, other_build])
    await db_session.flush()

    made = {}
    for key, slot, main in (
        ("flower", ArtifactSlot.FLOWER, StatType.HP_FLAT),
        ("second_flower", ArtifactSlot.FLOWER, StatType.HP_FLAT),
        ("plume", ArtifactSlot.PLUME, StatType.ATK_FLAT),
    ):
        piece = Artifact(
            owner_id=str(user.id), artifact_set_id=str(artifact_set.id), slot=slot,
            rarity=Rarity.FIVE_STAR, level=20, main_stat_type=main,
            main_stat_value=4780.0, substats=[],
        )
        db_session.add(piece)
        await db_session.flush()
        made[key] = str(piece.id)

    return {**made, "build": str(build.id), "other_build": str(other_build.id)}


async def _equip(client: AsyncClient, artifact: str, build: str | None):
    return await client.patch(f"{ARTIFACTS}/{artifact}", json={"build_id": build})


# ── equipping and unequipping ────────────────────────────────────────────────


async def test_a_piece_can_be_equipped(authed_client: AsyncClient, scene):
    response = await _equip(authed_client, scene["flower"], scene["build"])

    assert response.status_code == 200, response.text
    assert response.json()["build_id"] == scene["build"]


async def test_a_piece_can_be_unequipped_without_being_deleted(
    authed_client: AsyncClient, scene,
):
    """`SET NULL`, not cascade. Taking a flower off a build must not destroy the flower."""
    await _equip(authed_client, scene["flower"], scene["build"])

    unequipped = await _equip(authed_client, scene["flower"], None)

    assert unequipped.status_code == 200, unequipped.text
    assert unequipped.json()["build_id"] is None
    still_there = await authed_client.get(f"{ARTIFACTS}/{scene['flower']}")
    assert still_there.status_code == 200


async def test_a_piece_can_be_moved_between_builds(authed_client: AsyncClient, scene):
    await _equip(authed_client, scene["flower"], scene["build"])

    moved = await _equip(authed_client, scene["flower"], scene["other_build"])

    assert moved.status_code == 200, moved.text
    assert moved.json()["build_id"] == scene["other_build"]


async def test_two_slots_on_one_build_do_not_collide(authed_client: AsyncClient, scene):
    """Guards the guard: the refusal below is about the *same* slot, not about a second
    piece."""
    assert (await _equip(authed_client, scene["flower"], scene["build"])).status_code == 200
    assert (await _equip(authed_client, scene["plume"], scene["build"])).status_code == 200


# ── refusals ─────────────────────────────────────────────────────────────────


async def test_a_filled_slot_is_refused_by_name_not_silently_swapped(
    authed_client: AsyncClient, scene,
):
    """OQ-A2.

    Swapping is a reasonable thing to want and a terrible thing to do unasked: the displaced
    piece is still equipped in the user's head. `uq_artifacts_build_slot` would have made
    this a 500 — the shape `uq_builds_owner_character` had before T.1a.
    """
    await _equip(authed_client, scene["flower"], scene["build"])

    response = await _equip(authed_client, scene["second_flower"], scene["build"])

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert scene["flower"] in detail, "the message must name the piece already there"
    assert "Flower" in detail


async def test_re_equipping_the_same_piece_is_not_a_conflict(
    authed_client: AsyncClient, scene,
):
    """A piece does not collide with itself. Without this, saving a build unchanged would
    refuse every slot it already holds."""
    await _equip(authed_client, scene["flower"], scene["build"])

    again = await _equip(authed_client, scene["flower"], scene["build"])

    assert again.status_code == 200, again.text


async def test_a_build_that_is_not_yours_reads_as_absent(
    authed_client: AsyncClient, db_session: AsyncSession, scene,
):
    """Absent, not forbidden. Confirming it exists would disclose that it does — the same
    answer the team membership check gives."""
    stranger = User(email="stranger@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    theirs = Build(owner_id=str(stranger.id), character_id=None)
    db_session.add(theirs)
    await db_session.flush()

    response = await _equip(authed_client, scene["flower"], str(theirs.id))

    assert response.status_code == 422
    assert "of yours" in response.json()["detail"]


async def test_an_absent_build_is_refused_not_a_500(authed_client: AsyncClient, scene):
    """It would otherwise reach the foreign key."""
    response = await _equip(authed_client, scene["flower"], ABSENT)

    assert response.status_code == 422
    assert ABSENT in response.json()["detail"]


async def test_someone_elses_artifact_is_a_404(
    authed_client: AsyncClient, db_session: AsyncSession, scene,
):
    stranger = User(email="other@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    theirs = Artifact(
        owner_id=str(stranger.id), slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR,
        level=20, main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0, substats=[],
    )
    db_session.add(theirs)
    await db_session.flush()

    response = await _equip(authed_client, str(theirs.id), scene["build"])

    assert response.status_code == 404


async def test_the_patch_takes_nothing_but_the_binding(authed_client: AsyncClient, scene):
    """An artifact's stats come from the import, derived from the committed value table —
    not from a scanner's reading and not from a user. A patch that accepted `level` or
    `main_stat_value` would let the one number this repo derives be overwritten by hand."""
    response = await authed_client.patch(
        f"{ARTIFACTS}/{scene['flower']}", json={"build_id": None, "level": 4},
    )

    assert response.status_code == 422
    assert "level" in str(response.json()["detail"])


async def test_a_race_for_one_slot_is_a_422_not_a_500(
    authed_client: AsyncClient, db_session: AsyncSession, scene, monkeypatch,
):
    """The check and the write are not one operation.

    Two requests equipping the same slot can both pass the check, and
    `uq_artifacts_build_slot` is what keeps the data right afterwards. Without a handler that
    is a 500 for an ordinary race — the failure this endpoint exists to remove rather than
    relocate.

    Simulated by making the pre-check lie, which is exactly what a concurrent request does to
    it: reports the slot free when it is not.
    """
    from app.repositories.artifact import ArtifactRepository

    await _equip(authed_client, scene["flower"], scene["build"])
    monkeypatch.setattr(
        ArtifactRepository, "equipped_in_slot", lambda self, build_id, slot: _none(),
    )

    response = await _equip(authed_client, scene["second_flower"], scene["build"])

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "in flight" in detail
    # Named, and read *before* the write: a failed flush expires the instance, so reading
    # `artifact.slot` in the handler would emit SQL from inside the exception path and turn
    # this 422 back into the 500 it exists to prevent.
    assert "Flower" in detail


async def _none() -> None:
    """An awaitable `None`, standing in for a pre-check that saw the slot free."""
