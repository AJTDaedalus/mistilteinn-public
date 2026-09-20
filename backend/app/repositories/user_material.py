"""Data access for how many of each material a user holds.

`docs/DESIGN_planner_materials.md`. Sole data-access point for `user_materials`.

**Not a `BaseRepository` subclass**, for the reason `repositories/roster.py` gives: that base
addresses a row by a surrogate `id`, and this table is composite-keyed on
`(owner_id, material_id)` because the tuple *is* the identity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.models.planner import UserMaterial

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession


class UserMaterialRepository:
    """One user's stock, and the only place it is read or written."""

    def __init__(self, session: AsyncSession, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    async def counts(self) -> dict[int, int]:
        """`{material_id: count}`. **An absent material is absent**, not zero-filled here.

        The planner reads this straight into `stock_is_empty=not stock`, so zero-filling would
        make every account look stocked. The zero-fill belongs to the surface that lists the
        catalogue, and lives in `services/planner/stock.py`.
        """
        result = await self.session.execute(
            select(UserMaterial.material_id, UserMaterial.count).where(
                UserMaterial.owner_id == self.owner_id,
            ),
        )
        return dict(result.all())

    async def set_counts(self, counts: Mapping[int, int]) -> None:
        """Write these counts, leaving every material not named here alone.

        **A zero deletes the row rather than storing a zero.** `UserMaterial`'s docstring makes
        an absent row mean zero and records that a real export carries no zero-valued entry, so
        a stored zero is a second spelling of the same fact — and the spelling that breaks
        `stock_is_empty`, which asks whether there are any rows at all rather than whether they
        sum to anything.

        Partial by construction: this is what lets one caller fix one number without a body
        that has to restate an entire inventory. `DESIGN_planner_materials.md` §3.
        """
        if not counts:
            return

        present = {material_id: count for material_id, count in counts.items() if count > 0}
        absent = [material_id for material_id, count in counts.items() if count <= 0]

        if present:
            statement = insert(UserMaterial).values([
                {
                    "owner_id": self.owner_id,
                    "material_id": material_id,
                    "count": count,
                }
                for material_id, count in present.items()
            ])
            # `statement.excluded`, not a second `insert()` — the proposed row belongs to
            # *this* statement, and a fresh one would be a different `EXCLUDED` alias.
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["owner_id", "material_id"],
                    set_={"count": statement.excluded.count},
                ),
            )
        if absent:
            await self.session.execute(
                delete(UserMaterial).where(
                    UserMaterial.owner_id == self.owner_id,
                    UserMaterial.material_id.in_(absent),
                ),
            )
        await self.session.flush()
