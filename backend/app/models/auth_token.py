"""Single-use, hashed, expiring tokens for email verification and password reset.

Deliberately generic rather than an `email_verification_tokens` table: password reset
(`docs/DESIGN_open_registration.md` §9) needs exactly the same mint/hash/expire/consume
discipline, and a second near-identical table is how the two drift apart.

Mirrors `sessions` on purpose — same sha256-only storage, same expiry handling, same
startup purge. Do not invent a second convention for the same problem.
"""

from __future__ import annotations

import datetime  # noqa: TC003 — SQLAlchemy resolves Mapped[datetime.datetime] at runtime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk

PURPOSE_EMAIL_VERIFY = "email_verify"
PURPOSE_PASSWORD_RESET = "password_reset"  # noqa: S105 — a purpose label, not a credential


class AuthToken(TimestampMixin, Base):
    """One issued token. Only its sha256 is stored — the raw value exists in the email."""

    __tablename__ = "auth_tokens"

    id: Mapped[uuid_pk]
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Consumed rows are kept rather than deleted: "was this link used twice?" is a
    # question worth being able to answer during an incident, and the startup purge
    # clears them soon enough that the table cannot grow without bound.
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_auth_tokens_user_purpose", "user_id", "purpose"),)

    def __repr__(self) -> str:
        state = "consumed" if self.consumed_at else "live"
        return f"<AuthToken user={self.user_id} purpose={self.purpose} [{state}]>"
