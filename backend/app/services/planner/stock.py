"""Reading and correcting the material stock a plan is priced against.

`docs/DESIGN_planner_materials.md`. The GOOD import is no longer the only writer of
`user_materials`: a scanner that gets a count wrong used to be a bill the user could not
correct, and this is the correction.

**An import still replaces every row.** That is a ruling rather than an oversight — §2 of the
design argues it, and `tests/integration/test_planner_materials.py` pins it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.planner import Material
from app.repositories.user_material import UserMaterialRepository

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class StockError(ValueError):
    """An edit the stock cannot hold. Every one of these names what it refused."""


#: The largest count a row can hold, **because `user_materials.count` is `int4`**.
#:
#: It is not a claim about the game's own stack limit, which this repository has not sourced
#: and will not invent. Unbounded, a pasted twenty-digit number reaches asyncpg and comes back
#: as a 500 from a route whose whole job was to say no.
MAX_COUNT = 2_147_483_647


@dataclass(frozen=True)
class StockLine:
    """One material, and how many of it this account holds."""

    material_id: int
    name: str
    icon: str | None
    rarity: int
    count: int


async def list_stock(session: AsyncSession, owner_id: str) -> list[StockLine]:
    """Every material the catalogue holds, with this caller's count — zero where absent.

    **Zero-filled here and nowhere else.** The repository reports absence as absence because
    the planner reads it straight into `stock_is_empty`; a list for a user to edit has the
    opposite need, since the row worth typing into is usually the one that is missing.

    Sorted **owned first, then by name**. Not by rarity: rarity 0 is *unranked*, not worst, and
    it is where the local specialties live — Sakura Bloom, Philanemo Mushroom, Valberry — so a
    rarity sort buries sixty real ascension materials under the gem tiers.
    """
    counts = await UserMaterialRepository(session, owner_id).counts()
    materials = (await session.execute(select(Material))).scalars().all()
    lines = [
        StockLine(
            material_id=material.id,
            name=material.name,
            icon=material.icon,
            rarity=material.rarity,
            count=counts.get(material.id, 0),
        )
        for material in materials
    ]
    lines.sort(key=lambda line: (line.count == 0, line.name.lower()))
    return lines


async def set_stock(
    session: AsyncSession,
    owner_id: str,
    updates: Sequence[tuple[int, int]],
) -> list[StockLine]:
    """Write the named counts and return the rows as they now stand.

    Only the materials named are touched. Everything validated before anything is written, so
    a body with one bad row changes nothing — a partial write is the failure mode where a user
    fixes five numbers, sees an error, and cannot tell which of the five landed.
    """
    if not updates:
        return []

    _refuse_duplicates(material_id for material_id, _ in updates)
    for material_id, count in updates:
        _refuse_bad_count(material_id, count)

    wanted = {material_id for material_id, _ in updates}
    known = set(
        (
            await session.execute(select(Material.id).where(Material.id.in_(wanted)))
        ).scalars(),
    )
    missing = sorted(wanted - known)
    if missing:
        # **By name.** An export newer than the seeded patch is the usual cause, and a user who
        # is told which id can act on it; a silent drop leaves a number that appears to save.
        raise StockError(
            "No such material: " + ", ".join(str(material_id) for material_id in missing),
        )

    # No `commit` here: the route commits, as `roster.set_owned` does. A service that commits
    # takes the choice away from a caller that wants to write two things or neither.
    await UserMaterialRepository(session, owner_id).set_counts(dict(updates))

    counts = await UserMaterialRepository(session, owner_id).counts()
    materials = {
        material.id: material
        for material in (
            await session.execute(select(Material).where(Material.id.in_(wanted)))
        ).scalars()
    }
    return [
        StockLine(
            material_id=material_id,
            name=materials[material_id].name,
            icon=materials[material_id].icon,
            rarity=materials[material_id].rarity,
            count=counts.get(material_id, 0),
        )
        for material_id in sorted(wanted)
    ]


def _refuse_duplicates(material_ids: Iterable[int]) -> None:
    """Two counts for one material is two answers, and picking one discards the other."""
    seen: set[int] = set()
    repeated: set[int] = set()
    for material_id in material_ids:
        if material_id in seen:
            repeated.add(material_id)
        seen.add(material_id)
    if repeated:
        raise StockError(
            "Material listed twice: "
            + ", ".join(str(material_id) for material_id in sorted(repeated)),
        )


def _refuse_bad_count(material_id: int, count: int) -> None:
    if count < 0:
        raise StockError(f"Material {material_id}: a count cannot be negative")
    if count > MAX_COUNT:
        raise StockError(
            f"Material {material_id}: a count cannot exceed {MAX_COUNT}",
        )
