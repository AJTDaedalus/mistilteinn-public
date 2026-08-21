"""Shared ORM building blocks: declarative base, UUID7 primary-key type, and timestamp columns."""

import datetime
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_utils import uuid7


def generate_uuid7() -> str:
    """Generate a time-ordered UUID7 string for use as a model's primary key default."""
    return str(uuid7())


class Base(DeclarativeBase):
    """Declarative base every model inherits from, so all tables share one `MetaData`."""


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
