"""Cached gcsim results, keyed by what makes them valid.

A simulated run is expensive (~3 s in the browser, per DESIGN §3.5) and **immutable for a
given gcsim pin** — the BRIEF's observation that Genshin kits are write-once post-release,
applied one level up. So results are cached rather than recomputed, and invalidated by a
deliberate re-pin rather than by time.

## What the key has to include, and why

`context_key` is a hash of everything that changes the answer *except* the artifacts being
searched: character, weapon, refinement, constellation, talent levels, team, rotation and
target. `er_bucket` is the one artifact-borne stat that feeds back into context, because it
decides whether the burst happens at all (DESIGN §3.5).

`gcsim_pin` is part of the key rather than a column to check afterwards. A cache that
returned a result from a different simulator would be the worst kind of wrong: fast,
confident, and describing a game version nobody asked about.

## Owner-scoped, deliberately

The browser produces these numbers, so a tampered client can submit whatever it likes.
Scoping rows to their owner means that only poisons the caller's own cache. **Sharing
results between users is a separate feature with a separate threat model** — it needs either
server-side verification or a reputation story, and neither is free. `owner_id` is nullable
so a future server-generated corpus can be shared explicitly rather than by accident.
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class SimRun(TimestampMixin, Base):
    """One cached gcsim result for one (context, ER bucket, pin)."""

    __tablename__ = "sim_runs"
    __table_args__ = (
        # The lookup is always all three, so the uniqueness and the index are the same shape.
        UniqueConstraint(
            "owner_id", "context_key", "er_bucket", "gcsim_pin",
            name="uq_sim_runs_owner_context_bucket_pin",
        ),
        Index("ix_sim_runs_lookup", "owner_id", "context_key", "gcsim_pin"),
    )

    id: Mapped[uuid_pk]

    #: Null means server-generated and shareable. A client-submitted run always has one —
    #: see the module docstring on why they are not shared.
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
    )

    #: Hash of the simulated context. Opaque by design: what goes into it is
    #: `sim_context.context_key`'s business, and storing the parts would invite querying by
    #: them and then disagreeing with the hash.
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Coarse energy-recharge bucket, in whole percent (`100` = 1.00 ER). Coarse because the
    #: point is which side of the burst-uptime cliff the build sits on, not its exact ER.
    er_bucket: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The gcsim commit that produced this. Part of the key, not a column to check later.
    gcsim_pin: Mapped[str] = mapped_column(String(40), nullable=False)

    #: What the simulation reported — the aggregated statistics, verbatim.
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: Pulled out of `result` for the common read. A cache whose headline number needs a
    #: JSONB traversal is a cache that gets bypassed.
    dps_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- labels, never key material -------------------------------------------------------
    #
    # `context_key` is a hash, and the docstring above says storing its parts "would invite
    # querying by them and then disagreeing with the hash". These two columns do not reopen
    # that: **neither is in the unique constraint, and no cache lookup reads either.** They
    # exist so the rotation library can find *this caller's* runs for a rotation, which a hash
    # cannot be asked.

    #: Which rotation this run simulated, when it was one. `SET NULL`, not `CASCADE`: the run
    #: is still a valid cached simulation after the rotation is deleted — it simply stops being
    #: attributable to one, which is exactly what null means here.
    rotation_id: Mapped[str | None] = mapped_column(
        ForeignKey("rotations.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    #: The rotation **as it was** when this ran — `rotation_compiler.rotation_signature`,
    #: hashed.
    #:
    #: This is the column that stops a real bug rather than enabling a feature. A rotation is
    #: editable. Edit it and `context_key` changes, so the next run writes a new row — while
    #: the old row keeps its `rotation_id` and its DPS. Ordering a library by `rotation_id`
    #: alone would sort a rotation by a number computed for a **previous version of itself**:
    #: a confident figure describing something the user can no longer see.
    #:
    #: Matching on this as well means your number appears where you have one for the rotation
    #: as it stands, and nothing where you do not — which is what the design's "unsorted rather
    #: than ranked by somebody else's gear" already argues for.
    rotation_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<SimRun {self.context_key[:8]}… er={self.er_bucket} @{self.gcsim_pin[:7]}>"
