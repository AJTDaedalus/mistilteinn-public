"""Shared ORM building blocks: declarative base, UUID7 primary-key type, and timestamp columns."""

import datetime
import enum
from typing import Annotated

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_utils import uuid7

# Deterministic names for every constraint and index.
#
# fairy did not set this, and the cost showed up in B.10: `alembic downgrade base` on its
# 39-migration history died with `Can't emit DROP CONSTRAINT for constraint
# ForeignKeyConstraint(..., None, table=Table('combos', ...)); it has no name`. An
# auto-generated downgrade cannot drop a constraint the database named for it. Nobody
# noticed because nothing ever downgraded — the history had to be reset with
# `DROP SCHEMA public CASCADE` instead.
#
# Set here, before mistilteinn's first migration is generated, so every constraint
# autogenerate emits is named and every downgrade is expressible. Changing this later
# means renaming live constraints, which is why it is not a later problem.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def generate_uuid7() -> str:
    """Generate a time-ordered UUID7 string for use as a model's primary key default."""
    return str(uuid7())


class Base(DeclarativeBase):
    """Declarative base every model inherits from, so all tables share one `MetaData`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Common column types
uuid_pk = Annotated[
    str,
    mapped_column(primary_key=True, default=generate_uuid7),
]


class TimestampMixin:
    """Adds `created_at`/`updated_at` columns to a model, populated via DB `server_default`."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


#: JSONB columns in this package are plain `Mapped[list]` / `Mapped[dict]`, **not**
#: `MutableList` / `MutableDict`. In-place mutation is therefore invisible to the session:
#:
#:     build.talent_levels["elemental_burst"] = 12   # NOT flushed
#:     build.talent_levels = {**build.talent_levels, "elemental_burst": 12}   # flushed
#:
#: Left as-is deliberately. Every JSONB column here is written whole by an importer or a
#: request body, never patched in place, and `MutableDict` adds a change-tracking wrapper to
#: every load. Revisit if a service ever needs to edit one field of one blob.
_JSONB_IS_NOT_MUTATION_TRACKED = True


def enum_column(enum_cls: type[enum.Enum], length: int) -> Enum:
    """A VARCHAR column that loads back as the enum member, not as a bare `str`.

    `mapped_column(String(16))` under a `Mapped[Element]` annotation does **not** coerce:
    SQLAlchemy sees a plain `String` and hands back whatever Postgres returned. The
    annotation is then a lie for every row that was actually read from the database rather
    than constructed in the same session:

        fresh.element        -> 'Cryo'   (str, not Element.CRYO)
        fresh.element is Element.CRYO    -> False
        fresh.rarity.stars               -> AttributeError

    `==` still works because these are `StrEnum`s, so the breakage is asymmetric and only
    shows up the first time someone writes `is` or calls a member property — which
    `Rarity.stars` is, and which is the entire reason `Rarity` is an enum rather than an int.

    Settings, and why:

    * `native_enum=False` — render as `VARCHAR(length)`, not a Postgres `ENUM` type. A
      native enum would need `ALTER TYPE … ADD VALUE` in a migration every time a patch
      introduces an element or a `FIGHT_PROP`.
    * `create_constraint=False` — no `CHECK (col IN (…))`, for the same reason. The
      unmapped-value path in `enums.py` is this codebase's chosen mechanism for a vocabulary
      that grows every patch: warn, do not reject.
    * `values_callable` — store the member *value* (`"Cryo"`), not its *name* (`"CRYO"`),
      which is what the payload and every importer speak.

    The rendered DDL is identical to `String(length)`, so switching an existing column to
    this needs no migration.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        create_constraint=False,
        values_callable=lambda e: [m.value for m in e],
    )
