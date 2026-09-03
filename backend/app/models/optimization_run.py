"""A saved optimization run — what a search was asked, what it ran against, what it concluded.

`DESIGN_account_tracking.md` Track 2. Owner: *"Users should also be able to save their
optimization runs and see a list of previous runs when first going to the optimization page.
These should be sharable, like the gcsim database sharing results."*

## Why this stores snapshots rather than foreign keys

A build changes. Artifacts get levelled, weapons get swapped, a rotation gets edited. A saved
result that held only ids and re-read them at display time would show **a number that no
longer matches what actually ran**, and would do it silently — the reader would have no way to
tell a stale figure from a fresh one.

That is the recipe cache's own lesson, arrived at from the other side: `recipe-cache.ts` names
everything that changes what gcsim would produce *in its key*, so a mismatch is a miss rather
than a wrong answer. Here there is no key to miss against, so the inputs are frozen instead.

Ids are kept **beside** the snapshots, not instead of them: the id is what makes the rotation
findable and the character drawable; the snapshot is what makes the number honest.
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import Visibility


class OptimizationRun(TimestampMixin, Base):
    """One completed search, saved."""

    __tablename__ = "optimization_runs"
    __table_args__ = (
        Index("ix_optimization_runs_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid_pk]
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: The user's own label. Never interpreted.
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    #: Private by default, like a rotation.
    #:
    #: The same reasoning `Visibility` records: a private thing becoming visible is not a
    #: mistake anyone can take back, so sharing is something a user does rather than something
    #: that happens to them. Reusing the enum rather than inventing a second sharing model is
    #: the point — the owner's framing is *"sharable, like the gcsim database"*, and this repo
    #: already solved that for rotations.
    visibility: Mapped[Visibility] = mapped_column(
        enum_column(Visibility, 16), nullable=False, default=Visibility.PRIVATE,
        server_default=Visibility.PRIVATE.value, index=True,
    )
    share_key: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)

    #: What the search was **asked**: sets considered, weapons compared, energy model, enemy.
    #:
    #: Without it a shared result cannot be interpreted, let alone reproduced. "This build
    #: scored 1.4 M" means nothing until you know it was against a level-100 hilichurl with
    #: waiting on and four sets in the pool.
    objective: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: What it **ran against**, frozen: the build, the artifacts *with their substats at the
    #: time*, and the rotation. See the module docstring.
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: What it **concluded**: the winning pieces and their scores.
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: How far ahead of the runner-up, as a fraction.
    #:
    #: *"It won by 0.3 %"* and *"it won by 12 %"* are different claims, and a reader deciding
    #: whether to refarm needs the second one. Nullable because a search with one candidate
    #: has no runner-up, which is different from a margin of zero.
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)

    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: A different simulator is a different result, and this is the one that would otherwise
    #: go unnoticed for months — the same argument `recipe-cache.ts` makes about its key.
    gcsim_pin: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    character_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    rotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rotations.id", ondelete="SET NULL"), nullable=True,
    )
    #: What makes two runs comparable, where `rotation_id` only makes one findable.
    rotation_signature: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<OptimizationRun {self.name!r} {self.score:.0f}>"
