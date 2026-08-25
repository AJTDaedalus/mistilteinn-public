"""N.3 — a `replace` import keeps builds equipped.

`replace` deletes every artifact this owner has and re-inserts from the export. Every
`Artifact.build_id` goes with them, so **a user re-importing their own scan finds all their
builds stripped** — five empty slots each, with nothing saying why.

The chunk-G marker framed this as team slots, re-keyed on
`Build.character_id`. That is not what breaks: teams point at *builds*, builds are untouched
by an artifact wipe, and team slots come through fine. What breaks is the artifact→build
binding, one layer down.

**Matched on stats, not on identity.** GOOD carries no stable per-artifact id — that is the
whole reason `mode` has no default — so a restore matches a re-inserted piece to a
snapshotted one by what it *is*: set, slot, rarity, level, main stat and substats. Two pieces
identical in all of those are interchangeable for every purpose this app has, so either will
do; a piece with no match stays unequipped and is reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.artifact import Artifact, ArtifactSet
from app.models.build import Build
from app.models.character import Character
from app.models.enums import ArtifactSlot, Element, Rarity, StatType, WeaponType
from app.services.good_import_service import REPLACE, store_good_import

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio


def _good(*pieces: dict) -> dict:
    """A GOOD export holding `pieces`."""
    return {"format": "GOOD", "version": 2, "source": "test", "artifacts": list(pieces)}


def _piece(set_key: str, slot: str, main: str, percent: float, level: int = 20) -> dict:
    """One GOOD artifact.

    `percent` is written the way GOOD writes it — **10.9 means 10.9%** — and the importer
    stores `0.109`. Passing the fraction here instead produced a piece a hundred times
    weaker, which fingerprinted differently and made the restore look broken when the
    fixture was.
    """
    return {
        "setKey": set_key, "slotKey": slot, "level": level, "rarity": 5,
        "mainStatKey": main, "location": "", "lock": False,
        "substats": [{"key": "critRate_", "value": percent}],
    }


@pytest.fixture
async def scene(db_session: AsyncSession, authed_user: tuple[User, str]) -> dict:
    """A build wearing one flower, and the export that would replace it."""
    user, _ = authed_user
    owner_id = str(user.id)
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

    build = Build(owner_id=owner_id, character_id=str(character.id))
    db_session.add(build)
    await db_session.flush()
    build_id = str(build.id)

    worn = Artifact(
        owner_id=owner_id, artifact_set_id=str(artifact_set.id), build_id=build_id,
        slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0,
        substats=[{"stat": "FIGHT_PROP_CRITICAL", "value": 0.109}],
    )
    db_session.add(worn)
    await db_session.flush()
    return {"owner_id": owner_id, "build_id": build_id}


async def _replace(session: AsyncSession, owner_id: str, payload: dict):
    from app.data.importers.good_importer import parse_good

    return await store_good_import(session, owner_id, parse_good(payload), REPLACE)


async def _equipped(session: AsyncSession, build_id: str) -> list[Artifact]:
    return list(
        (await session.execute(
            select(Artifact).where(Artifact.build_id == build_id),
        )).scalars().all(),
    )


async def test_a_replace_keeps_an_identical_piece_equipped(
    db_session: AsyncSession, scene: dict,
):
    """The point of the task. Re-importing the same scan must not strip every build."""
    payload = _good(_piece("BlizzardStrayer", "flower", "hp", 10.9))

    result = await _replace(db_session, scene["owner_id"], payload)

    assert result.deleted == 1
    assert result.inserted == 1
    worn = await _equipped(db_session, scene["build_id"])
    assert len(worn) == 1, "the build was stripped by a re-import of its own artifact"
    assert worn[0].slot is ArtifactSlot.FLOWER


async def test_a_piece_no_longer_in_the_export_is_reported_not_silently_dropped(
    db_session: AsyncSession, scene: dict,
):
    """A user who sold the artifact should be told the slot is empty, not discover it later
    from a damage number."""
    payload = _good(_piece("BlizzardStrayer", "plume", "atk", 5.0))

    result = await _replace(db_session, scene["owner_id"], payload)

    assert await _equipped(db_session, scene["build_id"]) == []
    assert result.unequipped, "the slot emptied and nothing said so"
    assert scene["build_id"] in result.unequipped[0]


async def test_a_changed_piece_does_not_get_matched_to_a_different_one(
    db_session: AsyncSession, scene: dict,
):
    """Levelling the flower makes it a different artifact. Equipping the new one anyway would
    be this app deciding the user meant something they did not say."""
    payload = _good(_piece("BlizzardStrayer", "flower", "hp", 10.9, level=16))

    await _replace(db_session, scene["owner_id"], payload)

    assert await _equipped(db_session, scene["build_id"]) == []


async def test_an_append_import_leaves_equipment_alone(
    db_session: AsyncSession, scene: dict,
):
    """`append` deletes nothing, so there is nothing to restore — and a restore that ran
    anyway could re-point a slot at a newly added duplicate."""
    from app.data.importers.good_importer import parse_good
    from app.services.good_import_service import APPEND

    payload = _good(_piece("BlizzardStrayer", "plume", "atk", 5.0))

    result = await store_good_import(
        db_session, scene["owner_id"], parse_good(payload), APPEND,
    )

    assert result.deleted == 0
    assert result.unequipped == ()
    assert len(await _equipped(db_session, scene["build_id"])) == 1


async def test_another_owner_s_equipment_is_untouched(
    db_session: AsyncSession, scene: dict,
):
    """The subtlety the marker says to keep: a foreign build's slot is never clobbered.

    `replace` is already owner-scoped, so a stranger's artifacts survive the delete — and the
    restore must not reach across and re-point them either.
    """
    from app.models.user import User as UserModel

    stranger = UserModel(email="other@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    their_build = Build(owner_id=str(stranger.id), character_id=None)
    db_session.add(their_build)
    await db_session.flush()
    their_build_id = str(their_build.id)
    theirs = Artifact(
        owner_id=str(stranger.id), artifact_set_id=None, build_id=their_build_id,
        slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0, substats=[],
    )
    db_session.add(theirs)
    await db_session.flush()
    theirs_id = str(theirs.id)

    await _replace(
        db_session, scene["owner_id"],
        _good(_piece("BlizzardStrayer", "flower", "hp", 10.9)),
    )

    still = await db_session.get(Artifact, theirs_id)
    assert still is not None, "a stranger's artifact was deleted"
    assert str(still.build_id) == their_build_id


async def test_one_export_piece_cannot_fill_two_builds_slots(
    db_session: AsyncSession, scene: dict, authed_user: tuple[User, str],
):
    """Two builds wearing identical flowers each had their **own**.

    Handing them the same re-inserted row would leave one build short — and
    `uq_artifacts_build_slot` would reject the second write anyway, so the import would fail
    on a constraint rather than report a slot it could not refill.
    """
    user, _ = authed_user
    owner_id = str(user.id)
    second = Build(owner_id=owner_id, character_id=None)
    db_session.add(second)
    await db_session.flush()
    second_id = str(second.id)

    artifact_set = (await db_session.execute(select(ArtifactSet))).scalars().first()
    db_session.add(Artifact(
        owner_id=owner_id, artifact_set_id=str(artifact_set.id), build_id=second_id,
        slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0,
        substats=[{"stat": "FIGHT_PROP_CRITICAL", "value": 0.109}],
    ))
    await db_session.flush()

    # Two identical flowers in the export — one for each build.
    result = await _replace(db_session, owner_id, _good(
        _piece("BlizzardStrayer", "flower", "hp", 10.9),
        _piece("BlizzardStrayer", "flower", "hp", 10.9),
    ))

    assert result.unequipped == (), result.unequipped
    assert len(await _equipped(db_session, scene["build_id"])) == 1
    assert len(await _equipped(db_session, second_id)) == 1


async def test_only_one_build_is_refilled_when_only_one_piece_returns(
    db_session: AsyncSession, scene: dict, authed_user: tuple[User, str],
):
    """The other half: one flower back for two builds fills one and **names the other**.

    Reusing the row would look like both survived, and the second build would be reported as
    wearing a piece that another build is also wearing.
    """
    user, _ = authed_user
    owner_id = str(user.id)
    second = Build(owner_id=owner_id, character_id=None)
    db_session.add(second)
    await db_session.flush()
    second_id = str(second.id)
    artifact_set = (await db_session.execute(select(ArtifactSet))).scalars().first()
    db_session.add(Artifact(
        owner_id=owner_id, artifact_set_id=str(artifact_set.id), build_id=second_id,
        slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0,
        substats=[{"stat": "FIGHT_PROP_CRITICAL", "value": 0.109}],
    ))
    await db_session.flush()

    result = await _replace(
        db_session, owner_id, _good(_piece("BlizzardStrayer", "flower", "hp", 10.9)),
    )

    filled = len(await _equipped(db_session, scene["build_id"])) + len(
        await _equipped(db_session, second_id),
    )
    assert filled == 1, "one flower filled two slots"
    assert len(result.unequipped) == 1


async def test_a_strangers_matching_piece_is_never_re_pointed(
    db_session: AsyncSession, scene: dict,
):
    """The subtlety the marker says to keep, with a piece that **would** match.

    An unscoped snapshot would record a stranger's equipped flower and then try to refill
    their slot from this owner's import — clobbering untouched data with somebody else's
    artifact.
    """
    from app.models.user import User as UserModel

    stranger = UserModel(email="matcher@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    their_build = Build(owner_id=str(stranger.id), character_id=None)
    db_session.add(their_build)
    await db_session.flush()
    their_build_id = str(their_build.id)

    artifact_set = (await db_session.execute(select(ArtifactSet))).scalars().first()
    theirs = Artifact(
        owner_id=str(stranger.id), artifact_set_id=str(artifact_set.id),
        build_id=their_build_id, slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR,
        level=20, main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0,
        substats=[{"stat": "FIGHT_PROP_CRITICAL", "value": 0.109}],
    )
    db_session.add(theirs)
    await db_session.flush()
    theirs_id = str(theirs.id)

    result = await _replace(
        db_session, scene["owner_id"], _good(_piece("BlizzardStrayer", "flower", "hp", 10.9)),
    )

    # This owner's build gets the one imported flower; the stranger's slot is not considered.
    assert len(await _equipped(db_session, scene["build_id"])) == 1
    assert result.unequipped == (), "a stranger's slot was reported as this owner's loss"
    still = await db_session.get(Artifact, theirs_id)
    assert str(still.build_id) == their_build_id
