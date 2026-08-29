"""Reconstituting builds from a GOOD export, against a real database.

**These exist because the first version of this feature was tested without them.** The
original unit tests asserted on parser dataclasses and on `lookup_key`, never calling
`rebuild_builds` at all — so two real bugs shipped through a green suite:

* the Traveler branch was **unreachable**. All 28 catalogue variants are named `Traveler`, so
  `by_key["traveler"]` was a 28-row list rather than a miss, the resolver keyed on `rows is
  None` never ran, and every Traveler build came out as the lowest id (Pyro Aether) at level
  1 with no talents — whatever element the user actually played;
* the weapon's level and refinement came from the **first export entry sharing the name**
  rather than the copy the character holds, so an R5 L90 sword could be recorded as the R1 L1
  spare, silently changing every damage number computed for that build.

Both are asserted below. A test that cannot fail when the thing it is named for is broken is
worse than no test, because it is counted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.data.importers.good_importer import (
    GoodImportResult,
    ParsedArtifact,
    ParsedCharacter,
    ParsedWeapon,
)
from app.models.artifact import Artifact
from app.models.build import Build
from app.models.character import Character
from app.models.enums import (
    ArtifactSlot,
    Element,
    Rarity,
    StatType,
    UserStatus,
    WeaponType,
)
from app.models.user import User
from app.models.weapon import Weapon
from app.services.good_build_service import rebuild_builds

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def catalogue(db_session: AsyncSession) -> dict[str, object]:
    """Two Traveler variants that share a name, plus a character and two weapon copies."""
    rows = {
        # Both Pyro-and-Cryo, both genders: the exact shape that made the resolver unreachable.
        "aether_pyro": Character(
            nanoka_id="10000005-2", name="Traveler", element=Element.PYRO,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
            base_hp=912.0, base_atk=18.0, base_def=57.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        ),
        "aether_cryo": Character(
            nanoka_id="10000005-5", name="Traveler", element=Element.CRYO,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
            base_hp=912.0, base_atk=18.0, base_def=57.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        ),
        "lumine_cryo": Character(
            nanoka_id="10000007-5", name="Traveler", element=Element.CRYO,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
            base_hp=912.0, base_atk=18.0, base_def=57.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        ),
        "ayaka": Character(
            nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
            base_hp=1001.0, base_atk=26.6, base_def=61.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        ),
        "favonius": Weapon(
            nanoka_id=11301, name="Favonius Sword", weapon_type=WeaponType.SWORD,
            rarity=Rarity.FOUR_STAR, base_atk=41.0, sub_stat_type=StatType.ENERGY_RECHARGE,
            sub_stat_base_value=0.133,
        ),
    }
    db_session.add_all(list(rows.values()))
    await db_session.flush()
    return rows


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    user = User(
        email="importer@example.com",
        password_hash="not-a-real-hash",  # noqa: S106 — a fixture, never authenticated
        status=UserStatus.APPROVED,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _piece(location: str, slot: ArtifactSlot, index: int) -> ParsedArtifact:
    return ParsedArtifact(
        slot=slot, rarity=Rarity.FIVE_STAR, level=20, main_stat="FIGHT_PROP_HP",
        substats=(), set_key="EmblemOfSeveredFate", location=location, source_index=index,
    )


async def _row(db_session: AsyncSession, owner: User, slot: ArtifactSlot) -> Artifact:
    row = Artifact(
        owner_id=owner.id, slot=slot, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type="FIGHT_PROP_HP", main_stat_value=4780.0, substats=[],
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_the_traveler_gets_the_element_the_export_names(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """`artifacts[].location` says only `Traveler`; `characters[]` says which one.

    The regression: this produced a **Pyro** Traveler at level 1, because the ambiguous key
    was a 28-row hit rather than a miss and the resolver only handled misses.
    """
    flower = await _row(db_session, owner, ArtifactSlot.FLOWER)
    parsed = GoodImportResult(
        artifacts=(_piece("Traveler", ArtifactSlot.FLOWER, 0),),
        rejected=(), source="Irminsul", version=3,
        characters=(
            ParsedCharacter(
                key="TravelerCryo", level=80, ascension=6, constellation=2,
                talents={"normal_attack": 7, "elemental_skill": 8, "elemental_burst": 9},
            ),
        ),
        weapons=(),
    )

    report = await rebuild_builds(
        db_session, owner_id=str(owner.id), parsed=parsed, stored={0: flower},
    )

    assert report.created == 1
    build = (await db_session.execute(select(Build))).scalars().one()
    character = await db_session.get(Character, build.character_id)
    assert character is not None
    assert character.element is Element.CRYO, "took the wrong Traveler's element"
    assert build.character_level == 80
    assert build.constellation_level == 2
    assert build.talent_levels == {
        "normal_attack": 7, "elemental_skill": 8, "elemental_burst": 9,
    }
    # The gender is not in a GOOD export at all, so the choice is arbitrary but stated.
    assert "Traveler gender" in build.notes


async def test_the_build_holds_the_copy_of_the_weapon_that_is_equipped(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """Owning several copies of one weapon is routine. The held one is not always first.

    The regression: `_new_build` re-found the weapon by *name* and took the first entry, so a
    character holding an R5 L90 sword was recorded with the R1 L1 spare's numbers.
    """
    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="Irminsul", version=3,
        characters=(
            ParsedCharacter(
                key="KamisatoAyaka", level=90, ascension=6, constellation=0,
                talents={"normal_attack": 10, "elemental_skill": 9, "elemental_burst": 9},
            ),
        ),
        weapons=(
            # The spare, listed first and held by nobody.
            ParsedWeapon(key="FavoniusSword", level=1, ascension=0, refinement=1),
            # The one she is actually holding.
            ParsedWeapon(
                key="FavoniusSword", level=90, ascension=6, refinement=5,
                location="KamisatoAyaka",
            ),
        ),
    )

    await rebuild_builds(db_session, owner_id=str(owner.id), parsed=parsed, stored={})

    build = (await db_session.execute(select(Build))).scalars().one()
    assert build.weapon_id == catalogue["favonius"].id
    assert build.weapon_level == 90, "took a different copy of the weapon"
    assert build.refinement == 5


async def test_a_weapon_the_catalogue_does_not_know_is_reported(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """A build with no weapon is a legitimate state, so an unresolved one is invisible."""
    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="s", version=3,
        characters=(
            ParsedCharacter(key="KamisatoAyaka", level=90, ascension=6, constellation=0,
                            talents={}),
        ),
        weapons=(
            ParsedWeapon(key="SomeUnreleasedSword", level=90, ascension=6, refinement=1,
                         location="KamisatoAyaka"),
        ),
    )

    report = await rebuild_builds(
        db_session, owner_id=str(owner.id), parsed=parsed, stored={},
    )

    assert report.unresolved_weapons == ["Kamisato Ayaka: SomeUnreleasedSword"]
    build = (await db_session.execute(select(Build))).scalars().one()
    assert build.weapon_id is None


async def test_taking_a_piece_from_another_build_is_reported(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """`_restore_equipment` may already have bound the row to a build the user made.

    Reassigning it is sometimes right — they moved it in-game — but doing it silently leaves
    that build a slot short with nothing anywhere saying so.
    """
    existing = Build(owner_id=owner.id, character_id=catalogue["ayaka"].id)
    db_session.add(existing)
    await db_session.flush()
    flower = await _row(db_session, owner, ArtifactSlot.FLOWER)
    flower.build_id = existing.id
    await db_session.flush()

    parsed = GoodImportResult(
        artifacts=(_piece("Traveler", ArtifactSlot.FLOWER, 0),),
        rejected=(), source="s", version=3,
        characters=(ParsedCharacter(key="TravelerCryo", level=80, ascension=6,
                                    constellation=0, talents={}),),
        weapons=(),
    )

    report = await rebuild_builds(
        db_session, owner_id=str(owner.id), parsed=parsed, stored={0: flower},
    )

    assert len(report.reassigned) == 1
    # The slot is the source's own spelling (`EQUIP_BRACER`), not the display name — the
    # report names what the database holds so it can be matched back to a row.
    assert str(ArtifactSlot.FLOWER) in report.reassigned[0]
    assert "Traveler" in report.reassigned[0]


async def test_a_character_that_already_has_a_build_is_kept_and_named(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """A re-import refreshes the inventory. A build carries decisions no scanner knows."""
    existing = Build(
        owner_id=owner.id, character_id=catalogue["ayaka"].id, notes="mine, hand-tuned",
    )
    db_session.add(existing)
    await db_session.flush()

    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="s", version=3,
        characters=(ParsedCharacter(key="KamisatoAyaka", level=90, ascension=6,
                                    constellation=0, talents={}),),
        weapons=(ParsedWeapon(key="FavoniusSword", level=90, ascension=6, refinement=5,
                              location="KamisatoAyaka"),),
    )

    report = await rebuild_builds(
        db_session, owner_id=str(owner.id), parsed=parsed, stored={},
    )

    assert report.created == 0
    assert report.skipped_existing == ["Kamisato Ayaka"]
    await db_session.refresh(existing)
    assert existing.notes == "mine, hand-tuned"


async def test_an_over_long_source_does_not_take_the_import_down(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """`Build.notes` is `String(1000)`; `source` is unvalidated export text of any length.

    Untruncated this raised `StringDataRightTruncation` on flush, rolling back the artifacts
    too and returning a 500 — a whole import lost to a field nobody reads.
    """
    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="x" * 5000, version=3,
        characters=(ParsedCharacter(key="KamisatoAyaka", level=90, ascension=6,
                                    constellation=0, talents={}),),
        weapons=(ParsedWeapon(key="FavoniusSword", level=90, ascension=6, refinement=5,
                              location="KamisatoAyaka"),),
    )

    report = await rebuild_builds(
        db_session, owner_id=str(owner.id), parsed=parsed, stored={},
    )

    assert report.created == 1
    build = (await db_session.execute(select(Build))).scalars().one()
    assert len(build.notes) < 200


async def test_only_equipped_characters_get_a_build(
    db_session: AsyncSession, owner: User, catalogue: dict,
) -> None:
    """An export lists every character an account owns, mannequins included.

    Holding something is the signal that separates the ones a user plays, and it excludes the
    mannequins without this code ever having to know their names.
    """
    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="s", version=3,
        characters=(
            ParsedCharacter(key="KamisatoAyaka", level=90, ascension=6, constellation=0,
                            talents={}),
            ParsedCharacter(key="Manekin", level=1, ascension=0, constellation=0, talents={}),
        ),
        weapons=(ParsedWeapon(key="FavoniusSword", level=90, ascension=6, refinement=5,
                              location="KamisatoAyaka"),),
    )

    report = await rebuild_builds(
        db_session, owner_id=str(owner.id), parsed=parsed, stored={},
    )

    assert report.created == 1
    assert report.unresolved == []
