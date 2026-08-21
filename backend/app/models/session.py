"""Authenticated login session, kept separate from `User` so a token can be revoked on its own."""

from __future__ import annotations

import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime.datetime] at runtime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Session(TimestampMixin, Base):
    """Authenticated session — one row per active login token."""

    __tablename__ = "sessions"

    id: Mapped[uuid_pk]
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Session user={self.user_id} expires={self.expires_at}>"
