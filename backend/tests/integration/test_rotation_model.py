"""R.1 — rotations over real rows, and the two questions the DESIGN left open.

**OQ-R1: a rotation belongs to a team**, because it names several characters acting in turn
and a `Build` is one character. `sim_context.context_key` already hashes team and rotation
together, so the pairing existed at the cache layer before the schema admitted it.

**OQ-R2: a step names a character**, not a slot and not a build — stable across team
reordering and build edits alike — and a rotation whose team loses that character goes
**stale** rather than being silently repaired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.rotation import Rotation
from app.models.team import Team
from app.repositories.rotation import RotationRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _character(db: AsyncSession, nanoka_id: str, name: str) -> Character:
    character = Character(
        nanoka_id=nanoka_id, name=name, element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    db.add(character)
    await db.flush()
    return character


async def _team_of(db: AsyncSession, user: User, *names: tuple[str, str]) -> Team:
    """A team whose slots hold builds of the named characters, in order."""
    builds = []
    for nanoka_id, name in names:
        character = await _character(db, nanoka_id, name)
        build = Build(owner_id=str(user.id), character_id=str(character.id))
        db.add(build)
        builds.append(build)
    await db.flush()
    team = Team(owner_id=str(user.id), name="Party")
    for index, build in enumerate(builds, start=1):
        setattr(team, f"build{index}_id", str(build.id))
    db.add(team)
    await db.flush()
    return team


# ── The rotation ──────────────────────────────────────────────────────────────


async def test_a_rotation_saves_and_reads_back_in_order(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Order is the whole content of a rotation; a set would say nothing."""
    user, _ = authed_user
    team = await _team_of(db_session, user, ("10000002", "Ayaka"), ("10000014", "Barbara"))
    steps = [
        {"character": "10000014", "action": "skill", "repeat": 1, "note": "shield first"},
        {"character": "10000002", "action": "burst", "repeat": 1, "note": ""},
        {"character": "10000002", "action": "attack", "repeat": 3, "note": ""},
    ]
    rotation = Rotation(
        owner_id=str(user.id), team_id=str(team.id), name="Ayaka melt", steps=steps,
    )
    db_session.add(rotation)
    await db_session.flush()

    found = await RotationRepository(db_session, owner_id=str(user.id)).get_by_id(
        str(rotation.id),
    )

    assert [s["action"] for s in found.steps] == ["skill", "burst", "attack"]
    assert found.steps[2]["repeat"] == 3


async def test_the_team_reports_its_characters(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """What a step is validated against, and it must reach all four slots."""
    user, _ = authed_user
    team = await _team_of(
        db_session, user,
        ("10000002", "Ayaka"), ("10000014", "Barbara"),
        ("10000023", "Xiangling"), ("10000025", "Xingqiu"),
    )

    repo = RotationRepository(db_session, owner_id=str(user.id))

    assert await repo.team_characters(str(team.id)) == {
        "10000002", "10000014", "10000023", "10000025",
    }


async def test_the_fourth_slot_is_reachable(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """R.1a added it; this proves the rotation path actually reads it.

    A `team_characters` that stopped at three would refuse every step naming the fourth
    character, and the message would blame the user's rotation for the schema's gap.
    """
    user, _ = authed_user
    team = await _team_of(
        db_session, user,
        ("10000002", "A"), ("10000014", "B"), ("10000023", "C"), ("10000025", "D"),
    )
    repo = RotationRepository(db_session, owner_id=str(user.id))

    assert "10000025" in await repo.team_characters(str(team.id))


async def test_a_partial_team_reports_only_what_it_holds(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Empty slots are ordinary — a team is built up over time."""
    user, _ = authed_user
    team = await _team_of(db_session, user, ("10000002", "Ayaka"))

    repo = RotationRepository(db_session, owner_id=str(user.id))

    assert await repo.team_characters(str(team.id)) == {"10000002"}


async def test_an_unknown_team_reports_no_characters(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Empty, not an exception: the caller's next move is to refuse the step either way, and
    a missing team and an empty team are the same answer to "who can act"."""
    user, _ = authed_user
    repo = RotationRepository(db_session, owner_id=str(user.id))

    assert await repo.team_characters("01a02987-0000-7000-0000-000000000000") == set()


# ── Scoping and cascade ───────────────────────────────────────────────────────


async def test_rotations_are_owner_scoped(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    user, _ = authed_user
    team = await _team_of(db_session, user, ("10000002", "Ayaka"))
    rotation = Rotation(owner_id=str(user.id), team_id=str(team.id), name="Mine", steps=[])
    db_session.add(rotation)
    await db_session.flush()

    stranger = RotationRepository(db_session, owner_id="01a02987-0000-7000-0000-00000000ffff")

    assert await stranger.get_by_id(str(rotation.id)) is None


async def test_listing_by_team_is_scoped_to_that_team(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    user, _ = authed_user
    one = await _team_of(db_session, user, ("10000002", "Ayaka"))
    two = await _team_of(db_session, user, ("10000014", "Barbara"))
    db_session.add_all([
        Rotation(owner_id=str(user.id), team_id=str(one.id), name="For one", steps=[]),
        Rotation(owner_id=str(user.id), team_id=str(two.id), name="For two", steps=[]),
    ])
    await db_session.flush()

    repo = RotationRepository(db_session, owner_id=str(user.id))
    found = await repo.list_for_team(str(one.id))

    assert [r.name for r in found] == ["For one"]


async def test_deleting_a_team_deletes_its_rotations(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """CASCADE, not SET NULL.

    A rotation without its team is not a partial rotation — it is an ordered list of
    characters nobody can place. Keeping it would leave a row that can never compile and
    that no screen could sensibly show.
    """
    user, _ = authed_user
    team = await _team_of(db_session, user, ("10000002", "Ayaka"))
    rotation = Rotation(owner_id=str(user.id), team_id=str(team.id), name="Doomed", steps=[])
    db_session.add(rotation)
    await db_session.flush()
    rotation_id = str(rotation.id)

    await db_session.delete(team)
    await db_session.flush()
    db_session.expunge_all()

    repo = RotationRepository(db_session, owner_id=str(user.id))

    assert await repo.get_by_id(rotation_id) is None
