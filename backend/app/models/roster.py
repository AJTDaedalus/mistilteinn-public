"""Which characters a user actually has.

`DESIGN_character_roster.md`. Owner ruling 2026-09-03, choosing the broader of the two
candidates in `BACKLOG_frontend.md` §14:

> *"we could take the broader approach and make a character table (with ownership) and a build
> table (with builds) and track them separately, but we need a tab for both so users can change
> ownership manually if needed."*

## Why this is not a column on `builds`

It was one, for three days. Two facts moved it, both measured on the owner's own account rather
than argued.

**The schema lets a character have several builds, and nothing would make them agree.** No user
holds two today — 84 builds, 4 orphaned, zero per-owner duplicates — so this half is latent. But
`Build`'s own docstring records that `uq_builds_owner_character` was *deliberately dropped*
(owner, 2026-08-24) because comparing a C0 against a C6 is an ordinary thing to want. Do that
ordinary thing, mark one of the two a test build — `owned`'s entire stated purpose — and the
account holds two answers to "do you have Eula?" with no correct reducer: `bool_or` says yes
when the user meant no for that build, `bool_and` says no when they plainly own her. A per-build
flag cannot express a per-character fact, and this repo has already ruled that a user may have
many builds per character.

**And twelve characters had no build to carry the flag at all.** `good_build_service` creates a
build only for a character holding a weapon or an artifact — a good rule, which excludes GO's
practice mannequins without ever naming them. Measured on the reference export: 89 characters,
75 holding something, 12 real characters wearing nothing (Dahlia, Yun Jin, Ningguang, Amber,
Razor, Yaoyao, Mika, Kaveh, Sethos, Shikanoin Heizou, Alyosha, Ifa). Eleven favour two
furnishing sets each, so the teapot tracker could not see 22 sets — 440 Primogems. The rule
excluded the mannequins **correctly by accident**, and twelve real characters paid for it.

Equipment was standing in for ownership. This table is ownership.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — a runtime annotation for SQLAlchemy

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: Written by a GOOD import. Refreshed by the next one.
SOURCE_IMPORT = "import"
#: Written by the user, on the roster tab. **Never overwritten by an import.**
SOURCE_MANUAL = "manual"

SOURCES = (SOURCE_IMPORT, SOURCE_MANUAL)


class CharacterRosterEntry(Base):
    """One user's answer about one character: do they have them.

    **Composite-keyed on purpose.** `(owner_id, character_id)` is what makes the divergence in
    the module docstring unrepresentable — a character has exactly one ownership answer per
    user, enforced by the database rather than by whoever writes the next query. It follows the
    precedent already here: `teapot_progress` and `teapot_built` are keyed the same way rather
    than carrying a surrogate id, because the tuple *is* the identity.

    **An absent row is not `owned=False`.** Absent means nobody has said — a catalogue character
    this user has never imported or touched. `owned=False` means they said no. The API keeps the
    two distinguishable, because a fresh account should not read as *"you own none of the 150
    characters"*, and a character explicitly un-owned must not quietly come back on the next
    import.
    """

    __tablename__ = "character_roster"
    __table_args__ = (
        CheckConstraint(
            "source IN ('import', 'manual')", name="ck_character_roster_source",
        ),
    )

    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True,
    )
    owned: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    #: **Who said so**, and the reason a re-import is safe.
    #:
    #: A row the user set by hand is `manual` and an import leaves it alone; an `import` row is
    #: refreshed. This is the rule `good_build_service` already applies to builds — *"a build
    #: carries decisions that no scanner knows about"* — applied to the one fact kept here.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'import'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
        onupdate=text("now()"),
    )
