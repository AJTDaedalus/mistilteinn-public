"""The account entity: credentials plus the admin-approval status gate for new signups."""

from __future__ import annotations

import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime.datetime] at runtime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import UserStatus


class User(TimestampMixin, Base):
    """Authenticated user — email/password, admin-approval flow."""

    __tablename__ = "users"

    id: Mapped[uuid_pk]
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, 16), nullable=False, default=UserStatus.PENDING,
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_users_status", "status"),)

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.status}]>"
