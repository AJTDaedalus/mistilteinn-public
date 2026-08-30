"""Data access for the gcsim result cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.models.sim_run import SimRun
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class SimRunRepository(BaseRepository[SimRun]):
    """Sole data-access point for cached gcsim results."""

    model = SimRun

    async def get(
        self, *, context_key: str, er_bucket: int, gcsim_pin: str, any_pin: bool = False,
    ) -> SimRun | None:
        """One cached run, or None. Prefers this pin; `any_pin` will settle for an older one.

        ## Why a re-pin no longer empties the cache

        This used to require all three parts, on the argument that *"a lookup that omitted the
        pin would happily return a result from a different simulator, which is the failure this
        cache is keyed to prevent."* Owner ruling, 2026-08-29:

        > a prior version of gcsim likely doesn't mean much for a rotation. It is rare for
        > existing characters to change behavior, especially in game. If a rotation did change
        > performance, it'd likely be because of a bug found in gcsim.

        That defeats *invalidation*, not *disclosure*. The original objection was to serving
        another simulator's number **silently** — so the pin is still stored, still returned,
        and a caller can see that what it got was computed by an older build. What it no longer
        does is throw the whole corpus away on a re-pin, which for a demand-driven cache means
        every user re-simulating everything they had.

        **The current pin still wins.** `any_pin` is a fallback, ordered newest-first, not a
        licence to ignore which build produced a number.
        """
        stmt = select(SimRun).where(
            SimRun.owner_id == self.owner_id,
            SimRun.context_key == context_key,
            SimRun.er_bucket == er_bucket,
        )
        exact = (
            await self.session.execute(stmt.where(SimRun.gcsim_pin == gcsim_pin))
        ).scalar_one_or_none()
        if exact is not None or not any_pin:
            return exact
        # Newest first, so a fallback is the closest build rather than the oldest one lying
        # around. `created_at` is the only ordering available: a pin is a commit hash and
        # carries no order of its own.
        older = stmt.order_by(SimRun.created_at.desc()).limit(1)
        return (await self.session.execute(older)).scalars().first()

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
        rotation_id: str | None = None,
        rotation_signature: str | None = None,
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
                rotation_id=rotation_id,
                rotation_signature=rotation_signature,
            )
            .on_conflict_do_update(
                constraint="uq_sim_runs_owner_context_bucket_pin",
                # The labels are updated too. A row can be written before the client knows
                # which rotation it belongs to and again after; keeping the older, emptier
                # label would leave a run permanently unattributable for no reason.
                set_={
                    "result": result,
                    "dps_mean": dps_mean,
                    "rotation_id": rotation_id,
                    "rotation_signature": rotation_signature,
                },
            )
            .returning(SimRun, (literal_column("xmax") == 0).label("created"))
        )
        row = (await self.session.execute(stmt)).one()
        return row[0], bool(row.created)

    async def dps_by_rotation(
        self, pairs: Mapping[str, str],
    ) -> dict[str, float]:
        """This caller's best DPS per rotation, for the rotations they have actually run.

        `pairs` is `{rotation_id: signature}` — **both**, because a run whose signature no
        longer matches is a number computed for a previous version of that rotation, and
        showing it would be worse than showing nothing. A rotation absent from the result is
        one this user has no current run for, which the library renders as unsorted rather
        than as zero.

        `max`, because a user may have run the same rotation at several ER buckets and the
        question the library answers is *what does this do on my gear*, not *what did the
        worst-cased bucket do*.

        One query for the whole page. A lookup per row is the shape that turns twenty rows
        into twenty-one round trips.
        """
        if not pairs:
            return {}
        stmt = (
            select(SimRun.rotation_id, func.max(SimRun.dps_mean))
            .where(SimRun.rotation_id.in_(list(pairs)))
            .where(SimRun.dps_mean.is_not(None))
            .group_by(SimRun.rotation_id)
        )
        if self.owner_id is not None:
            stmt = stmt.where(SimRun.owner_id == self.owner_id)
        # The signature is matched per rotation, so a row for rotation A cannot satisfy the
        # signature of rotation B. `or_` over pairs rather than `IN` over signatures.
        stmt = stmt.where(
            or_(*[
                (SimRun.rotation_id == rotation_id) & (SimRun.rotation_signature == signature)
                for rotation_id, signature in pairs.items()
            ]),
        )
        rows = (await self.session.execute(stmt)).all()
        return {rotation_id: float(dps) for rotation_id, dps in rows if dps is not None}
