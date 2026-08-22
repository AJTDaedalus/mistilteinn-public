"""Data access for the gcsim result cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert

from app.models.sim_run import SimRun
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class SimRunRepository(BaseRepository[SimRun]):
    """Sole data-access point for cached gcsim results."""

    model = SimRun

    async def get(self, *, context_key: str, er_bucket: int, gcsim_pin: str) -> SimRun | None:
        """One cached run, or None.

        All three parts of the key, always. A lookup that omitted the pin would happily
        return a result from a different simulator, which is the failure this cache is
        keyed to prevent.
        """
        stmt = select(SimRun).where(
            SimRun.owner_id == self.owner_id,
            SimRun.context_key == context_key,
            SimRun.er_bucket == er_bucket,
            SimRun.gcsim_pin == gcsim_pin,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_buckets(
        self, *, context_key: str, gcsim_pin: str,
    ) -> Sequence[SimRun]:
        """Every cached bucket for one context, so a search can see what it already has."""
        stmt = (
            select(SimRun)
            .where(
                SimRun.owner_id == self.owner_id,
                SimRun.context_key == context_key,
                SimRun.gcsim_pin == gcsim_pin,
            )
            .order_by(SimRun.er_bucket)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def store(
        self,
        *,
        context_key: str,
        er_bucket: int,
        gcsim_pin: str,
        result: dict[str, Any],
        dps_mean: float | None,
    ) -> tuple[SimRun, bool]:
        """Insert, or replace what is there for the same key. Returns `(run, created)`.

        Upsert rather than insert-or-fail: two tabs can finish the same context run at once,
        and a unique-violation surfacing to the user as an error would be a worse answer than
        keeping either result — they are the same simulation of the same thing.

        `created` is read from `xmax`, which an upsert leaves at 0 on the rows it inserted
        and non-zero on the rows it updated. Obscure, but it is the only way to learn which
        branch fired without a second query that a concurrent tab could invalidate between
        the two — and a POST that reports 201 while it replaced is a lie about what happened.
        """
        stmt = (
            insert(SimRun)
            .values(
                owner_id=self.owner_id,
                context_key=context_key,
                er_bucket=er_bucket,
                gcsim_pin=gcsim_pin,
                result=result,
                dps_mean=dps_mean,
            )
            .on_conflict_do_update(
                constraint="uq_sim_runs_owner_context_bucket_pin",
                set_={"result": result, "dps_mean": dps_mean},
            )
            .returning(SimRun, (literal_column("xmax") == 0).label("created"))
        )
        row = (await self.session.execute(stmt)).one()
        return row[0], bool(row.created)
