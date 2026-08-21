"""Shared ORM building blocks: declarative base, UUID7 primary-key type, and timestamp columns."""

import datetime
from typing import Annotated

from sqlalchemy import DateTime, MetaData, func
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
