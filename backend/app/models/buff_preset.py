"""A saved, reusable set of custom (stage) buffs — issue #64, DESIGN_buff_context.md §2.4."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class BuffPreset(TimestampMixin, Base):
    """A named list of ``CustomBuff`` objects, saved independently of any build.

    Deadly Assault and Shiyu stage buffs rotate with the patch cycle and get re-applied
    across many builds and many runs, so they have to be storable somewhere that is
    neither a build nor a request. A preset is that place.

    It is a **client-side convenience only** (DESIGN §2.4): applying a preset copies its
    buffs into the request's ``custom_buffs``. No calculation path ever resolves a preset
    id, which is what makes a stored result immutable — editing a preset after a
    calculation cannot retroactively change that calculation's numbers.

    ``owner_id`` cascades rather than nulling out, unlike ``builds``/``teams``/``combos``:
    an ownerless build is still a build a UI can show, but an ownerless preset is a row
    nobody can ever list, apply or delete, because every read path is owner-scoped.
    """

    __tablename__ = "buff_presets"

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: ``list[CustomBuff]`` as validated by ``schemas.damage.CustomBuff`` — stored as
    #: plain JSON rather than a child table because the whole list is always read,
    #: written and applied as one unit, and nothing queries an individual buff.
    buffs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    def __repr__(self) -> str:
        return f"<BuffPreset {self.name} ({len(self.buffs or [])} buffs)>"
