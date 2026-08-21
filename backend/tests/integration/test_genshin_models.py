"""Round-trip every Genshin table against a real Postgres (C.8).

One row per table, read back, plus the cascade behaviour each relationship declares. These
are the tests that catch a mapping that only *looks* right: a `String(16)` too short for its
enum values, a cascade that deletes a user's artifacts when they delete a build, a unique
constraint on the wrong pair of columns.

Values come from the committed nanoka fixtures where a real value exists, so the column
widths are exercised against data the importer will actually produce rather than against
`"x"`.

**Every read-back goes through `_reload`, which expires the object first.** The session is
built with `expire_on_commit=False`, so `session.get()` after a `flush()` returns the
instance the test just constructed — straight out of the identity map, with no SELECT. Tests
written that way assert against their own Python objects and pass regardless of what the
database or the column types do. That is not hypothetical: it hid a real defect through a
whole review round, where `Mapped[Element]` over a bare `String` came back as `str` and
`Rarity.stars` raised `AttributeError` on any row loaded in a new session.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.artifact import (
    Artifact,
    ArtifactMainStatPoolUnavailableError,
    ArtifactSet,
    ArtifactSetAffix,
    main_stats_for,
)
from app.models.build import Build, EnemyProfile
from app.models.character import (
    AscensionPassive,
    Character,
    Constellation,
    Talent,
    TalentScaling,
)
from app.models.enums import (
    ArtifactSlot,
    Element,
    Rarity,
    StatType,
    TalentType,
    UserStatus,
    WeaponType,
)
from app.models.user import User
from app.models.weapon import Weapon, WeaponRefinement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"


def _ayaka() -> dict:
    return json.loads((_FIX / "detail" / "character_10000002.json").read_text())


def _unique_id() -> int:
    """A nanoka_id that cannot collide with another test's row."""
    return uuid.uuid4().int % 10_000_000


async def _reload(db: AsyncSession, instance: object) -> object:
    """Expire and re-SELECT `instance`, so the assertion exercises the load path."""
    db.expire(instance)
    await db.refresh(instance)
    return instance


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"models_{uuid.uuid4().hex[:8]}@test.example",
        password_hash="x" * 60,
        status=UserStatus.APPROVED,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_character(db: AsyncSession) -> Character:
    payload = _ayaka()
    character = Character(
        nanoka_id=_unique_id(),
        name=payload["name"],
        element=Element.parse(payload["element"]),
        # Through the parser, not raw: the same passthrough on the *weapon* index would
        # write `ITEM_TPS_WEAPON` where characters hold `WEAPON_CROSSBOW`, and any join on
        # weapon type would silently lose the eight crossbows. D.3 should copy this line.
        weapon_type=WeaponType.parse(payload["weapon"]),
        rarity=Rarity.parse(payload["rarity"]),
        region=payload["chara_info"].get("region"),
        base_hp=payload["base_hp"],
        base_atk=payload["base_atk"],
        base_def=payload["base_def"],
        ascension_stat_type=StatType.CRIT_DMG,
        ascension_stats=payload["stats_modifier"]["ascension"],
        burst_energy_cost=80,
        icon=payload["icon"],
    )
    db.add(character)
    await db.flush()
    return character


async def _make_weapon(db: AsyncSession) -> Weapon:
    weapon = Weapon(
        nanoka_id=_unique_id(),
        name="Mistsplitter Reforged",
        weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR,
        base_atk=47.537,
        base_atk_curve="GROW_CURVE_ATTACK_302",
        sub_stat_type=StatType.CRIT_DMG,
        sub_stat_base_value=0.096,
        sub_stat_curve="GROW_CURVE_CRITICAL_301",
        ascension_atk={"1": {"fight_prop_base_attack": 31.1}},
    )
    db.add(weapon)
    await db.flush()
    return weapon


async def _make_set(db: AsyncSession) -> ArtifactSet:
    artifact_set = ArtifactSet(
        nanoka_id=_unique_id(),
        name="Deepwood Memories",
        piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db.add(artifact_set)
    await db.flush()
    return artifact_set


# ── round trips ───────────────────────────────────────────────────────────────


async def test_character_round_trips_with_its_fixture_values(db_session: AsyncSession):
    character = await _make_character(db_session)

    fetched = await _reload(db_session, character)

    assert fetched.name == "Kamisato Ayaka"
    assert fetched.element is Element.CRYO
    assert fetched.rarity is Rarity.FIVE_STAR
    assert fetched.ascension_stat_type is StatType.CRIT_DMG
    assert len(fetched.ascension_stats) == 6
    assert fetched.ascension_stats[5]["fight_prop_critical_hurt"] == pytest.approx(0.384)


async def test_a_character_with_no_vision_is_storable(db_session: AsyncSession):
    """Two of the 150 entries carry element "None" — the column must accept NULL."""
    character = await _make_character(db_session)
    character.element = None
    await db_session.flush()

    assert (await _reload(db_session, character)).element is None


async def test_talent_and_scaling_round_trip(db_session: AsyncSession):
    character = await _make_character(db_session)
    payload = _ayaka()["skills"][0]
    talent = Talent(
        character_id=character.id,
        nanoka_id=payload["id"],
        talent_type=TalentType.NORMAL_ATTACK,
        name=payload["name"],
        description=payload["desc"],
    )
    db_session.add(talent)
    await db_session.flush()
    promote = payload["promote"]["0"]
    db_session.add(
        TalentScaling(
            talent_id=talent.id,
            level=1,
            labels=promote["desc"],
            params=promote["param"],
        ),
    )
    await db_session.flush()

    fetched = await _reload(db_session, talent)
    await db_session.refresh(fetched, ["scalings"])

    assert fetched.talent_type is TalentType.NORMAL_ATTACK
    assert len(fetched.scalings) == 1
    assert fetched.scalings[0].labels[0].startswith("1-Hit DMG")
    # The long multi-line skill description must survive a Text column intact.
    assert fetched.description == payload["desc"]


async def test_constellations_and_passives_round_trip(db_session: AsyncSession):
    character = await _make_character(db_session)
    payload = _ayaka()
    for i, con in enumerate(payload["constellations"], start=1):
        db_session.add(
            Constellation(
                character_id=character.id, nanoka_id=con["id"], position=i,
                name=con["name"], description=con["desc"],
            ),
        )
    for passive in payload["passives"]:
        db_session.add(
            AscensionPassive(
                character_id=character.id, nanoka_id=passive["id"],
                unlock_ascension=passive["unlock"], name=passive["name"],
                description=passive["desc"],
            ),
        )
    await db_session.flush()

    fetched = await _reload(db_session, character)
    await db_session.refresh(fetched, ["constellations", "ascension_passives"])

    assert [c.position for c in fetched.constellations] == [1, 2, 3, 4, 5, 6]
    assert sorted(p.unlock_ascension for p in fetched.ascension_passives) == [0, 1, 4]


async def test_weapon_and_refinements_round_trip(db_session: AsyncSession):
    weapon = await _make_weapon(db_session)
    for level in range(1, 6):
        db_session.add(
            WeaponRefinement(
                weapon_id=weapon.id, level=level, name="Falcon's Defiance", description="…",
            ),
        )
    await db_session.flush()

    fetched = await _reload(db_session, weapon)
    await db_session.refresh(fetched, ["refinements"])

    assert [r.level for r in fetched.refinements] == [1, 2, 3, 4, 5]
    assert fetched.sub_stat_type is StatType.CRIT_DMG


def _longest(values) -> str:
    return max((v for v in values if isinstance(v, str)), key=len, default="")


@pytest.mark.parametrize(
    ("column", "longest"),
    [
        (Character.name, lambda f: _longest(v["en"] for v in f["character"].values())),
        (Character.icon, lambda f: _longest(v["icon"] for v in f["character"].values())),
        (
            Character.release_date,
            lambda f: _longest(v["release"] for v in f["character"].values()),
        ),
        (Weapon.name, lambda f: _longest(v["en"] for v in f["weapon"].values())),
        (Weapon.icon, lambda f: _longest(v["icon"] for v in f["weapon"].values())),
        (
            ArtifactSetAffix.name,
            lambda f: _longest(
                a["name"]["en"] for s in f["artifact"].values() for a in s["set"].values()
            ),
        ),
        (
            ArtifactSet.icon,
            lambda f: _longest(v["icon"] for v in f["artifact"].values()),
        ),
    ],
)
def test_every_string_column_is_wide_enough_for_the_committed_payloads(column, longest):
    """A `String(n)` narrower than real data fails at import time, on one unlucky row.

    Derived from the fixtures rather than hardcoded, so a longer value in a future patch is
    caught by refreshing `tests/fixtures/nanoka_gi/` — the same mechanism as the enum tests.
    The original version of this test asserted a 49-character name against `String(120)` and
    called it covered; it could not have failed.
    """
    import json

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"
    payloads = {
        name: json.loads((fixtures / f"{name}.json").read_text())
        for name in ("character", "weapon", "artifact")
    }
    value = longest(payloads)
    limit = column.type.length

    assert value, "fixture produced no value for this column — the accessor is wrong"
    assert len(value) <= limit, (
        f"{column} is String({limit}) but the longest committed value is "
        f"{len(value)} chars: {value!r}"
    )


def test_the_enum_columns_are_wide_enough_for_their_own_members():
    """A `String(n)` narrower than the longest enum value truncates or errors on write."""
    for column, enum_cls in (
        (Character.element, Element),
        (Character.weapon_type, WeaponType),
        (Character.rarity, Rarity),
        (Character.ascension_stat_type, StatType),
        (Talent.talent_type, TalentType),
        (Artifact.slot, ArtifactSlot),
    ):
        longest = max(len(m.value) for m in enum_cls)
        assert longest <= column.type.length, (
            f"{column} holds {enum_cls.__name__}, whose longest value is {longest} chars"
        )


async def test_a_long_affix_description_survives_a_text_column(db_session: AsyncSession):
    """The longest committed affix description is 858 characters — hence `Text`, not `String`."""
    import json

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"
    artifacts = json.loads((fixtures / "artifact.json").read_text())
    longest_desc = _longest(
        a["desc"]["en"] for s in artifacts.values() for a in s["set"].values()
    )
    artifact_set = await _make_set(db_session)
    affix = ArtifactSetAffix(
        artifact_set_id=artifact_set.id, position=0, pieces_required=4,
        name="Long", description=longest_desc,
    )
    db_session.add(affix)
    await db_session.flush()

    assert (await _reload(db_session, affix)).description == longest_desc


async def test_a_weapon_with_no_base_atk_or_substat_is_storable(db_session: AsyncSession):
    """The 8 ITEM_TPS_WEAPON rows carry null atk and sub — importing them must not 500."""
    weapon = Weapon(
        nanoka_id=_unique_id(),
        name="Frag Crystal - Pyro",
        weapon_type=WeaponType.CROSSBOW,
        rarity=Rarity.FOUR_STAR,
    )
    db_session.add(weapon)
    await db_session.flush()

    fetched = await _reload(db_session, weapon)
    assert fetched.base_atk is None
    assert fetched.sub_stat_type is None


async def test_artifact_set_round_trips_including_a_one_piece_set(db_session: AsyncSession):
    two_four = await _make_set(db_session)
    prayers = ArtifactSet(
        nanoka_id=_unique_id(), name="Prayers for Illumination",
        piece_thresholds=[1], available_ranks=[3, 4, 5],
    )
    db_session.add(prayers)
    await db_session.flush()
    db_session.add(
        ArtifactSetAffix(
            artifact_set_id=two_four.id, position=0, pieces_required=2,
            name="Deepwood Memories", description="Dendro DMG Bonus +15%.",
            add_props=[{"prop_type": "FIGHT_PROP_GRASS_ADD_HURT", "value": 0.15}],
        ),
    )
    await db_session.flush()

    assert (await _reload(db_session, prayers)).piece_thresholds == [1]
    fetched = await _reload(db_session, two_four)
    await db_session.refresh(fetched, ["affixes"])
    assert fetched.affixes[0].add_props[0]["prop_type"] == "FIGHT_PROP_GRASS_ADD_HURT"


async def test_artifact_round_trips_with_substats(db_session: AsyncSession):
    owner = await _make_user(db_session)
    artifact_set = await _make_set(db_session)
    artifact = Artifact(
        owner_id=owner.id, artifact_set_id=artifact_set.id,
        slot=ArtifactSlot.GOBLET, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.DENDRO_DMG_BONUS, main_stat_value=0.466,
        substats=[{"stat": StatType.CRIT_RATE.value, "value": 0.101, "rolls": 3}],
    )
    db_session.add(artifact)
    await db_session.flush()

    fetched = await _reload(db_session, artifact)
    assert fetched.slot is ArtifactSlot.GOBLET
    assert fetched.main_stat_type is StatType.DENDRO_DMG_BONUS
    assert fetched.substats[0]["rolls"] == 3


async def test_build_round_trips_with_its_relationships(db_session: AsyncSession):
    owner = await _make_user(db_session)
    character = await _make_character(db_session)
    weapon = await _make_weapon(db_session)
    build = Build(
        owner_id=owner.id, character_id=character.id, weapon_id=weapon.id,
        constellation_level=2, refinement=1,
        talent_levels={"normal_attack": 10, "elemental_skill": 10, "elemental_burst": 10},
    )
    db_session.add(build)
    await db_session.flush()
    artifact_set = await _make_set(db_session)
    db_session.add(
        Artifact(
            owner_id=owner.id, artifact_set_id=artifact_set.id, build_id=build.id,
            slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR, level=20,
            main_stat_type=StatType.HP_FLAT, main_stat_value=4780,
        ),
    )
    await db_session.flush()

    fetched = await _reload(db_session, build)
    await db_session.refresh(fetched, ["artifacts", "character", "weapon"])

    assert fetched.character.name == "Kamisato Ayaka"
    assert fetched.weapon.name == "Mistsplitter Reforged"
    assert [a.slot for a in fetched.artifacts] == [ArtifactSlot.FLOWER]
    assert fetched.talent_levels["elemental_burst"] == 10


async def test_enemy_profile_round_trips_all_eight_resistance_channels(db_session: AsyncSession):
    enemy = EnemyProfile(
        name="Ruin Guard", level=90, base_hp=1_000_000, base_atk=500, base_def=500,
        physical_res=0.7, anemo_res=0.1, cryo_res=0.1, dendro_res=0.1,
        electro_res=0.1, geo_res=0.1, hydro_res=0.1, pyro_res=-0.5,
    )
    db_session.add(enemy)
    await db_session.flush()

    fetched = await _reload(db_session, enemy)
    assert fetched.physical_res == pytest.approx(0.7)
    assert fetched.pyro_res == pytest.approx(-0.5), "negative RES is a weakness, not invalid"


# ── constraints ───────────────────────────────────────────────────────────────


async def test_constellation_position_is_unique_per_character(db_session: AsyncSession):
    character = await _make_character(db_session)
    db_session.add(Constellation(character_id=character.id, nanoka_id=1, position=1, name="A"))
    await db_session.flush()
    db_session.add(Constellation(character_id=character.id, nanoka_id=2, position=1, name="B"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_constellation_level_is_range_checked(db_session: AsyncSession):
    """The CheckConstraint alembic's autogenerate silently omitted (C.7)."""
    owner = await _make_user(db_session)
    db_session.add(Build(owner_id=owner.id, constellation_level=7))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_refinement_is_range_checked(db_session: AsyncSession):
    owner = await _make_user(db_session)
    db_session.add(Build(owner_id=owner.id, refinement=6))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_the_accepted_boundaries_really_are_accepted(db_session: AsyncSession):
    """The other half of a range check.

    `test_constellation_level_is_range_checked` inserts 7 and expects a failure — but so
    would `BETWEEN 0 AND 5`. Without this, an off-by-one that rejects legitimate values is
    invisible: nobody notices C6 is unsavable until a user tries.
    """
    owner = await _make_user(db_session)
    build = Build(
        owner_id=owner.id,
        constellation_level=6,
        refinement=5,
        ascension_phase=6,
        character_level=90,
        weapon_level=90,
    )
    db_session.add(build)
    await db_session.flush()

    reloaded = await _reload(db_session, build)
    assert reloaded.constellation_level == 6
    assert reloaded.refinement == 5

    floor_build = Build(
        owner_id=owner.id,
        constellation_level=0,
        refinement=1,
        ascension_phase=0,
        character_level=1,
        weapon_level=1,
    )
    db_session.add(floor_build)
    await db_session.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ascension_phase", 7),
        ("character_level", 91),
        ("character_level", 0),
        ("weapon_level", 91),
    ],
)
async def test_the_other_bounded_columns_are_range_checked(
    db_session: AsyncSession, field: str, value: int,
):
    """Added in the PR #2 review — three of the five bounded columns had no check at all."""
    owner = await _make_user(db_session)
    db_session.add(Build(owner_id=owner.id, **{field: value}))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_build_cannot_hold_two_artifacts_in_the_same_slot(db_session: AsyncSession):
    """Two flowers on one build would make every set count and stat sum silently wrong."""
    owner = await _make_user(db_session)
    build = Build(owner_id=owner.id)
    db_session.add(build)
    await db_session.flush()
    for _ in range(2):
        db_session.add(
            Artifact(
                owner_id=owner.id, build_id=build.id, slot=ArtifactSlot.FLOWER,
                rarity=Rarity.FIVE_STAR, main_stat_type=StatType.HP_FLAT,
                main_stat_value=4780,
            ),
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unequipped_artifacts_are_exempt_from_the_slot_uniqueness(
    db_session: AsyncSession,
):
    """The index is partial: an inventory of twenty spare flowers is normal."""
    owner = await _make_user(db_session)
    for _ in range(3):
        db_session.add(
            Artifact(
                owner_id=owner.id, slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR,
                main_stat_type=StatType.HP_FLAT, main_stat_value=4780,
            ),
        )
    await db_session.flush()

    count = await db_session.execute(
        select(func.count()).select_from(Artifact).where(Artifact.owner_id == owner.id),
    )
    assert count.scalar_one() == 3


async def test_build_artifacts_come_back_in_conventional_slot_order(db_session: AsyncSession):
    """Ordering on the column alone would give flower, *circlet*, plume, goblet, sands."""
    owner = await _make_user(db_session)
    build = Build(owner_id=owner.id)
    db_session.add(build)
    await db_session.flush()
    for slot in (ArtifactSlot.CIRCLET, ArtifactSlot.FLOWER, ArtifactSlot.GOBLET,
                 ArtifactSlot.PLUME, ArtifactSlot.SANDS):
        db_session.add(
            Artifact(
                owner_id=owner.id, build_id=build.id, slot=slot, rarity=Rarity.FIVE_STAR,
                main_stat_type=StatType.ATK_PCT, main_stat_value=0.466,
            ),
        )
    await db_session.flush()

    fetched = await _reload(db_session, build)
    await db_session.refresh(fetched, ["artifacts"])

    assert [a.slot for a in fetched.artifacts] == [
        ArtifactSlot.FLOWER,
        ArtifactSlot.PLUME,
        ArtifactSlot.SANDS,
        ArtifactSlot.GOBLET,
        ArtifactSlot.CIRCLET,
    ]


async def test_nanoka_ids_are_unique_per_catalogue_table(db_session: AsyncSession):
    """Re-running the importer must collide rather than duplicate the roster."""
    character = await _make_character(db_session)
    db_session.add(
        Character(
            nanoka_id=character.nanoka_id, name="Impostor", weapon_type=WeaponType.SWORD,
            rarity=Rarity.FOUR_STAR,
        ),
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_one_build_per_character_per_owner(db_session: AsyncSession):
    """Inherited from fairy's `uq_builds_owner_agent`; see the note in the Build docstring."""
    owner = await _make_user(db_session)
    character = await _make_character(db_session)
    db_session.add(Build(owner_id=owner.id, character_id=character.id))
    await db_session.flush()
    db_session.add(Build(owner_id=owner.id, character_id=character.id))

    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── cascades ──────────────────────────────────────────────────────────────────


async def test_deleting_a_character_cascades_to_its_talents(db_session: AsyncSession):
    character = await _make_character(db_session)
    talent = Talent(
        character_id=character.id, nanoka_id=1,
        talent_type=TalentType.ELEMENTAL_BURST, name="Soumetsu",
    )
    db_session.add(talent)
    await db_session.flush()
    db_session.add(TalentScaling(talent_id=talent.id, level=1, labels=[], params=[]))
    await db_session.flush()

    await db_session.delete(character)
    await db_session.flush()

    remaining = await db_session.execute(
        select(func.count()).select_from(Talent).where(Talent.character_id == character.id),
    )
    assert remaining.scalar_one() == 0
    # The grandchild too — `talent_scalings` cascades from `talents`, which cascades from
    # `characters`. Setting that up without asserting it proves nothing.
    orphaned = await db_session.execute(
        select(func.count())
        .select_from(TalentScaling)
        .where(TalentScaling.talent_id == talent.id),
    )
    assert orphaned.scalar_one() == 0


async def test_deleting_a_build_does_not_delete_the_users_artifacts(db_session: AsyncSession):
    """Unequipping is not destroying. `Artifact.build_id` is SET NULL for this reason."""
    owner = await _make_user(db_session)
    build = Build(owner_id=owner.id)
    db_session.add(build)
    await db_session.flush()
    artifact = Artifact(
        owner_id=owner.id, build_id=build.id, slot=ArtifactSlot.PLUME,
        rarity=Rarity.FIVE_STAR, main_stat_type=StatType.ATK_FLAT, main_stat_value=311,
    )
    db_session.add(artifact)
    await db_session.flush()

    await db_session.delete(build)
    await db_session.flush()
    # `refresh`, not `expire_all` + `get`: the database nulls the FK via ON DELETE SET NULL,
    # so the in-session object still holds the old value until it is re-read. (`get` returns
    # the identity-mapped instance and would then load it expired, synchronously, which
    # under asyncio raises MissingGreenlet.)
    await db_session.refresh(artifact)

    assert artifact.build_id is None


async def test_deleting_an_artifact_set_does_not_delete_owned_pieces(db_session: AsyncSession):
    """A set row is catalogue data; a piece is user data. Re-seeding must not eat inventory."""
    owner = await _make_user(db_session)
    artifact_set = await _make_set(db_session)
    artifact = Artifact(
        owner_id=owner.id, artifact_set_id=artifact_set.id, slot=ArtifactSlot.SANDS,
        rarity=Rarity.FIVE_STAR, main_stat_type=StatType.ATK_PCT, main_stat_value=0.466,
    )
    db_session.add(artifact)
    await db_session.flush()

    await db_session.delete(artifact_set)
    await db_session.flush()
    await db_session.refresh(artifact)

    assert artifact.artifact_set_id is None


# ── the main-stat pool is not guessed ─────────────────────────────────────────


def test_main_stats_for_raises_until_chunk_e_populates_the_table():
    """An empty pool must fail loudly, not read as "this slot allows nothing"."""
    with pytest.raises(ArtifactMainStatPoolUnavailableError, match="Chunk E"):
        main_stats_for(ArtifactSlot.SANDS)
