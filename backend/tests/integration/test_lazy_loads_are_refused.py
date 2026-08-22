"""G.11 — a relationship the query did not load must say so, not go and fetch it.

**Three separate `MissingGreenlet` bugs in Chunk G**, each an eager-load chain that stopped
one relationship short of what a response schema read:

* `Talent.scalings` — G.6a, `CharacterRead` returns the per-level table
* `ArtifactSet.affixes` from an artifact — G.6c, `set_bonuses` reads them
* `ArtifactSet.affixes` from a build — G.6c, same read down the other path

Every one looked correct in review, passed every unit test, and failed only when a route
actually ran. Three instances of one shape is a pattern, not three mistakes.

`lazy="raise_on_sql"` on the relationships services read turns that into an immediate,
named error. Two things make it better than the 500 it replaces:

1. **The message names the relationship.** `MissingGreenlet` says "IO attempted in an
   unexpected place" and leaves you to find which attribute did it.
2. **It raises in synchronous contexts too.** `MissingGreenlet` only appears under asyncio,
   so a plain script or a sync test would silently emit the extra query and pass. This
   fails everywhere, which is what makes it a guard rather than a nicer error message.

It is `raise_on_sql`, not `raise`: a relationship that is already loaded — by an eager
option, or because the object is pending — resolves normally. Only a load that would emit
SQL is refused, so the importers, which never touch these attributes, are unaffected, and a
route with the right `selectinload` is unaffected too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import selectinload

from app.models.artifact import ArtifactSet, ArtifactSetAffix
from app.models.character import Character, Talent, TalentScaling
from app.models.enums import Element, Rarity, TalentType, WeaponType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _character(db: AsyncSession) -> Character:
    character = Character(
        nanoka_id="10000002", name="Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        prop_curves={}, ascension_stats=[],
    )
    db.add(character)
    await db.flush()
    talent = Talent(
        character_id=str(character.id), nanoka_id=1,
        talent_type=TalentType.ELEMENTAL_BURST, name="Soumetsu", description="",
    )
    db.add(talent)
    await db.flush()
    db.add(TalentScaling(talent_id=str(talent.id), level=1, labels=[], params=[1.0]))
    await db.flush()
    db.expunge_all()
    return character


@pytest.mark.asyncio
async def test_an_unloaded_collection_raises_instead_of_querying(db_session: AsyncSession):
    """The bug G.6a shipped, caught at the attribute rather than at the response."""
    await _character(db_session)
    row = await db_session.scalar(select(Character).where(Character.nanoka_id == "10000002"))

    with pytest.raises(InvalidRequestError, match="raise_on_sql"):
        _ = row.talents


@pytest.mark.asyncio
async def test_an_eager_load_one_relationship_short_is_caught_at_that_relationship(
    db_session: AsyncSession,
):
    """This is exactly the G.6a bug: loading `talents` and not `Talent.scalings`.

    Before, it read as a `MissingGreenlet` from inside Pydantic during response
    serialisation. Now it names `Talent.scalings` at the moment the gap is reached.
    """
    await _character(db_session)
    row = await db_session.scalar(
        select(Character)
        .where(Character.nanoka_id == "10000002")
        .options(selectinload(Character.talents)),
    )

    assert row.talents, "the half that *was* loaded still works"
    with pytest.raises(InvalidRequestError, match="scalings"):
        _ = row.talents[0].scalings


@pytest.mark.asyncio
async def test_the_full_chain_loads_normally(db_session: AsyncSession):
    """`raise_on_sql` refuses a *query*, not access. The fixed chain is unaffected."""
    await _character(db_session)
    row = await db_session.scalar(
        select(Character)
        .where(Character.nanoka_id == "10000002")
        .options(selectinload(Character.talents).selectinload(Talent.scalings)),
    )

    assert [s.level for s in row.talents[0].scalings] == [1]


@pytest.mark.asyncio
async def test_a_pending_object_can_still_have_its_collection_touched(
    db_session: AsyncSession,
):
    """Nothing to query yet, so nothing to refuse.

    This is what keeps the importers working: they build rows and never read these
    attributes back, and a guard that broke object construction would have to be reverted
    rather than kept.
    """
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )

    assert artifact_set.affixes == []
    artifact_set.affixes.append(
        ArtifactSetAffix(position=0, pieces_required=2, name="", description=""),
    )
    db_session.add(artifact_set)
    await db_session.flush()

    assert len(artifact_set.affixes) == 1


@pytest.mark.asyncio
async def test_another_query_in_the_same_session_can_mask_a_missing_eager_load(
    db_session: AsyncSession,
):
    """Why removing one eager load does not always fail a test — and why that is not proof.

    Verifying this guard, I deleted the `selectinload(ArtifactSet.affixes)` from the artifact
    repository and the build-endpoint test still passed. The guard was fine; the *check* was
    wrong. `BuildRepository.get_full` had already loaded the same `ArtifactSet` rows with
    their affixes, and the identity map handed the second query the hydrated objects — so no
    SQL was needed and nothing was refused. Removing both eager loads fails immediately, with
    `'ArtifactSet.affixes' is not available due to lazy='raise_on_sql'`.

    The lesson is about integration tests generally, not about this guard: **a missing eager
    load can be invisible whenever another query in the same session already fetched the
    object.** Two routes that overlap will cover for each other, and the one that does not
    overlap is the one that 500s in production.
    """
    character = await _character(db_session)
    loaded = await db_session.scalar(
        select(Character)
        .where(Character.id == character.id)
        .options(selectinload(Character.talents).selectinload(Talent.scalings)),
    )
    assert loaded.talents[0].scalings

    # A second query with *no* eager options at all. It returns the same identity-mapped
    # object, already hydrated, so the guard has nothing to refuse.
    again = await db_session.scalar(
        select(Character).where(Character.id == character.id),
    )

    assert again is loaded
    assert again.talents[0].scalings, "already loaded, so no query and no refusal"


@pytest.mark.asyncio
async def test_the_guard_covers_every_relationship_a_response_schema_reads(
    db_session: AsyncSession,
):
    """A relationship added later without the flag would reopen the hole silently.

    Listed by name rather than derived, so adding one is a deliberate decision: a reader has
    to say whether a service reads it, and an omission shows up here as a failing test
    rather than as a 500 six months later.
    """
    from app.models.build import Build
    from app.models.weapon import Weapon

    guarded = {
        (Character, "talents"), (Character, "constellations"),
        (Character, "ascension_passives"), (Talent, "scalings"),
        (Weapon, "refinements"), (ArtifactSet, "affixes"),
        (Build, "character"), (Build, "weapon"), (Build, "artifacts"),
    }
    from app.models.artifact import Artifact
    guarded.add((Artifact, "artifact_set"))

    # Compared against the **literal**, not `models.base.GUARDED_LAZY`. Asserting the
    # constant would pass happily if someone redefined it to `"select"` — the guard would be
    # gone and its own test would agree that everything was guarded.
    unguarded = [
        f"{model.__name__}.{name}"
        for model, name in sorted(guarded, key=lambda pair: (pair[0].__name__, pair[1]))
        if getattr(model, name).property.lazy != "raise_on_sql"
    ]

    assert not unguarded, (
        f"{unguarded} lost `lazy=\"raise_on_sql\"`. A service reading one of these without "
        f"an eager load would go back to a 500 from inside response serialisation."
    )
