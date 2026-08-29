"""Persist the weapons a GOOD export lists, not only the ones a build wears.

**This is the gap that made `ParsedWeapon`'s docstring true**: *"Unheld weapons are parsed and
simply unused."* A real Irminsul export carries 320 weapons; the build importer read the 68 that
named a holder, purely to set `builds.weapon_id`, and discarded the other 252. So there was a
260-row weapon *catalogue* and no weapon *inventory* — no page could show what a user owns, and
"who is holding this" could not be asked of a weapon at all.

## Replace, always

An import replaces the owned-weapon rows wholesale rather than merging. GOOD carries **no stable
per-weapon id** — the same absence that makes artifact merging impossible (`good_import_service`
makes the same argument at length) — so there is nothing to match an old row to a new one by.
Two copies of Favonius Sword at the same level and refinement are indistinguishable, and
guessing which is which would silently move a build's weapon.

The equip link is rebuilt from `location` in the same pass, so it cannot outlive the rows it
points at.

## What is deliberately *not* done here

`builds.weapon_id` is left alone. It says which **catalogue** weapon a build uses and is what
the damage chain reads; it works for a build assembled by hand from a weapon nobody owns.
`OwnedWeapon.build_id` says which **physical copy** is on that build. They must agree after an
import, and `tests/integration/test_weapon_inventory.py` checks that they do — but they are
different questions, and collapsing them would break hypothetical builds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.models.build import Build
from app.models.weapon import OwnedWeapon, Weapon
from app.services.good_build_service import lookup_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.data.importers.good_importer import GoodImportResult


async def store_owned_weapons(
    session: AsyncSession, *, owner_id: str, parsed: GoodImportResult,
) -> tuple[int, list[str]]:
    """Replace this owner's weapon inventory from the export.

    Returns `(stored, unresolved)` — how many rows were written, and the export keys the
    catalogue could not identify. Unresolved weapons are **reported, not stored**: a row with a
    null `weapon_id` has no name, no rarity and no icon, so it would appear in the inventory as
    a blank the user could neither identify nor act on.
    """
    if not parsed.weapons:
        return 0, []

    catalogue = {
        lookup_key(row.name): row
        for row in (await session.execute(select(Weapon))).scalars().all()
    }
    # `location` is a character *name*, and a build already knows its character — so the link
    # is made through the build rather than by re-resolving the key against the catalogue. A
    # second resolution could disagree with the build importer about which Traveler variant a
    # `location` means, and then the inventory would show a weapon on one Traveler while the
    # build showed it on another.
    build_by_character_name: dict[str, Build] = {}
    for build in (
        await session.execute(
            # Eager, because `Build.character` is `lazy="raise_on_sql"` — a lazy hop here is an
            # `InvalidRequestError` inside a request rather than a slow query, which is the
            # whole point of that setting and is how this was caught.
            select(Build)
            .where(Build.owner_id == owner_id)
            .options(selectinload(Build.character)),
        )
    ).scalars().all():
        if build.character is not None:
            build_by_character_name.setdefault(lookup_key(build.character.name), build)

    await session.execute(delete(OwnedWeapon).where(OwnedWeapon.owner_id == owner_id))

    stored = 0
    unresolved: list[str] = []
    taken: set[str] = set()
    for weapon in parsed.weapons:
        row = catalogue.get(lookup_key(weapon.key))
        if row is None:
            unresolved.append(weapon.key)
            continue

        build_id = None
        if weapon.location:
            held_by = build_by_character_name.get(lookup_key(weapon.location))
            # The partial unique index allows one weapon per build, so a second copy claiming
            # the same build would fail the flush. Left unequipped instead: the inventory is
            # still right about what is owned, which is the part that would otherwise be lost.
            if held_by is not None and str(held_by.id) not in taken:
                build_id = str(held_by.id)
                taken.add(build_id)

        session.add(
            OwnedWeapon(
                owner_id=owner_id,
                weapon_id=str(row.id),
                build_id=build_id,
                level=weapon.level,
                ascension=weapon.ascension,
                refinement=weapon.refinement,
            ),
        )
        stored += 1

    await session.flush()
    return stored, sorted(set(unresolved))
