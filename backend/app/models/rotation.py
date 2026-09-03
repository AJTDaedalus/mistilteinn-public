"""A user-authored rotation: an ordered list of who does what.

`DESIGN_rotation.md` §2. The model is fairy's combo shape — a name, a team, and a flat
sequence of steps — and it deliberately **is not a language**: no conditionals, no loops, no
timing. Everything gcsim's syntax makes a user think about is either derived by the compiler
(readiness gates, swaps) or excluded on purpose.

## Why a rotation hangs off a team, not a build — OQ-R1

A rotation names *several* characters acting in turn. A `Build` is one character with its
weapon and artifacts, so a rotation cannot belong to one. A `Team` is the party, and its
builds supply the stats for whoever is being simulated.

It is also what `sim_context.context_key` already assumes: it hashes `team` and `rotation`
together, so the pairing exists at the cache layer whether or not the schema admits it. fairy
attached combos to a team for the same reason, and the owner named fairy as the model.

## Why a step names a character rather than a slot or a build — OQ-R2

**Not a slot**, because slots are positional: reordering the team would silently change what
the rotation means, and a rotation that quietly becomes a different rotation is worse than one
that breaks.

**Not a build**, because a build is a loadout. Swapping which Ayaka build sits on the team
should not invalidate a rotation that says "Ayaka bursts".

So a step names the **character** by `nanoka_id`, which is stable across both, and is what the
compiler needs anyway to reach a gcsim key.

The consequence is that a rotation can go **stale**: remove Ayaka from the team and a step
naming her no longer resolves. That is reported at compile time and refused, never silently
dropped and never reinterpreted — the same rule D.3 applies to a missing simulated run. A
user's authored steps are their work; deleting them to make a compile succeed would be the
system discarding input to avoid saying no.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import Visibility


class Rotation(TimestampMixin, Base):
    """One saved rotation for one team."""

    __tablename__ = "rotations"
    __table_args__ = (Index("ix_rotations_owner_team", "owner_id", "team_id"),)

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    #: CASCADE, not SET NULL. A rotation without its team is not a partial rotation, it is
    #: an ordered list of characters nobody can place — there is nothing left to interpret.
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: Private unless the author says otherwise (`DECISIONS.md` §21, OQ-4).
    #:
    #: **The default is the whole decision.** Every rotation already saved becomes `private`,
    #: which is what its author expects; a migration defaulting to `published` would
    #: retroactively share work nobody offered, and that is not a mistake anyone can take back.
    visibility: Mapped[Visibility] = mapped_column(
        enum_column(Visibility, 16), nullable=False, default=Visibility.PRIVATE,
        server_default=Visibility.PRIVATE.value, index=True,
    )

    #: `[{"character": "10000002", "action": "burst", "repeat": 1, "note": ""}, …]`
    #:
    #: JSONB rather than a `rotation_steps` table. A step has no identity of its own — it is
    #: meaningful only at its position in the list, is never referenced from elsewhere, and is
    #: always read and written whole. A child table would buy ordering columns and a join to
    #: express something the list already says.
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: The rotation as a tree, once it has one. Nullable through the rollout.
    #:
    #: `DESIGN_rotation_language.md`. `steps` is a tree flattened into a list with a path
    #: column, and it cannot hold `else`, nested loops or a user function. The read path
    #: **prefers `tree` and falls back to `steps`**, so a row written before this column
    #: existed keeps working and no deploy needs a coordinated backfill.
    tree: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    team: Mapped[object] = relationship("Team")

    def __repr__(self) -> str:
        return f"<Rotation {self.name!r} {len(self.steps or [])} steps>"


class RotationCharacter(Base):
    """One character a rotation names, so "rotations for this team" is a query.

    The set is **derivable** from `Rotation.steps` — every step carries a `character` — and
    derivable is not queryable. Answering "which shared rotations field exactly these four"
    from JSONB means reading every published rotation and unpacking it in Python.

    ## Rebuilt whole on every write, never diffed

    The steps are already read and written whole, for the reason the JSONB column gives. A diff
    would be a **second** implementation of "what characters does this rotation name", and the
    two would eventually disagree — at which point the library would offer a rotation for a team
    it cannot actually run on, which reads as a bug in the search rather than in a stale index.

    No `id`: a row is its pair, and nothing references one.
    """

    __tablename__ = "rotation_characters"

    rotation_id: Mapped[str] = mapped_column(
        ForeignKey("rotations.id", ondelete="CASCADE"), primary_key=True,
    )
    #: nanoka id, the same spelling `Rotation.steps` uses — stable across teams and builds.
    nanoka_id: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)

    def __repr__(self) -> str:
        return f"<RotationCharacter {self.rotation_id[:8]}… {self.nanoka_id}>"


class RotationLike(TimestampMixin, Base):
    """One user finding one rotation useful.

    **A table, not a counter column** (`DECISIONS.md` §21, OQ-3). A count alone cannot answer
    *have I liked this*, which the button needs to know, and cannot be un-liked without going
    negative under a race — two users toggling at once on a bare `UPDATE … SET n = n - 1`.

    Deliberately **not a rating**: a five-star scale invites a judgement nobody has the evidence
    to make — *is this a 3 or a 4 for my roster?* — and the question actually asked is binary.
    """

    __tablename__ = "rotation_likes"
    __table_args__ = (
        UniqueConstraint("rotation_id", "user_id", name="uq_rotation_likes_pair"),
    )

    id: Mapped[uuid_pk]
    rotation_id: Mapped[str] = mapped_column(
        ForeignKey("rotations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: CASCADE: a deleted account's likes are not evidence about anything.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    def __repr__(self) -> str:
        return f"<RotationLike {self.rotation_id[:8]}… by {self.user_id[:8]}…>"
