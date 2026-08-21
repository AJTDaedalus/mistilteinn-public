"""A user's saved Build and the EnemyProfile it is calculated against.

**Port state — these are skeletons, not the finished tables.** B.4 stripped every
ZZZ column; C.6 rewrites both for Genshin. What is left is the minimum that keeps
the schema coherent: `builds.id` is an FK target for `teams.build{1,2,3}_id`, and
both tables keep owner scoping so the repository layer's owner checks still apply.

Deleted from `Build` (was fairy@76909c4): `agent_id`, `w_engine_id`,
`w_engine_level`, `w_engine_refinement`, `mindscape_level`, `agent_level`,
`skill_levels`, `core_skill_level`, `potential_rank` and its check constraint, the
`disabled_buffs` / `active_conditions` / `stack_counts` modifier state, and the
`agent` / `w_engine` / `discs` relationships.

Deleted from `EnemyProfile`: every anomaly capacity and anomaly RES column, the
anomaly duration and stun-buildup factors, the stun threshold and stun DMG-taken
ratio, and the six ZZZ elemental RES columns.

The whole `Combo` model is gone. Genshin's rotation model is Chunk I and is
expected to be *smaller* than what it replaces (cooldown-gated rather than
freeform), so it is written against that design rather than inherited from this one.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.user import User  # noqa: F401 — ensures FK target is registered


class Build(TimestampMixin, Base):
    """A saved character build.

    TODO(chunk-C, C.6): add `character_id` FK, `weapon_id` FK + refinement, the five
    artifact slots, talent levels, constellation level, and character/weapon level.
    Do not reintroduce a column because its ZZZ counterpart existed — the BRIEF names
    leaked ZZZ shapes in the Genshin model as this fork's main long-term hazard.
    """

    __tablename__ = "builds"

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    notes: Mapped[str] = mapped_column(String(1000), default="")
    optimizer_priority: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None, index=True,
    )

    def __repr__(self) -> str:
        return f"<Build {self.id}>"


class EnemyProfile(TimestampMixin, Base):
    """Enemy stat profile for damage calculations.

    TODO(chunk-C, C.6): add per-element RES for the seven visions plus physical, and
    the base stats the Genshin DEF term needs. **No daze, anomaly, or stun columns** —
    those mechanics do not exist in this game (DESIGN §2.5).
    """

    __tablename__ = "enemy_profiles"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(Integer, default=90)

    def __repr__(self) -> str:
        return f"<EnemyProfile {self.name} lv{self.level}>"
