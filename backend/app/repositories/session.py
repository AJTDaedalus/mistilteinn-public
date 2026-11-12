"""Session repository — token-based auth sessions."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.models.session import Session
from app.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    """Sole data-access point for auth Session records (hashed bearer tokens)."""

    model = Session

    async def create_for_user(self, user_id: str, raw_token: str, ttl_seconds: int) -> Session:
        """Create a session row, storing only the SHA-256 hash of the raw token."""
        now = datetime.now(UTC)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return await self.create(
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": now + timedelta(seconds=ttl_seconds),
                "last_used_at": now,
            }
        )

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        """Look up a session by its hashed bearer token."""
        stmt = select(Session).where(Session.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def touch(self, session: Session) -> None:
        """Bump a session's ``last_used_at`` timestamp on activity."""
        session.last_used_at = datetime.now(UTC)
        await self.session.flush()

    async def delete_by_token_hash(self, token_hash: str) -> bool:
        """Log out a session by its hashed token; returns False if not found."""
        instance = await self.get_by_token_hash(token_hash)
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def delete_for_user(self, user_id: str) -> int:
        """Delete every session belonging to *user_id*; returns the number removed."""
        stmt = delete(Session).where(Session.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.rowcount

    async def delete_expired(self, now: datetime | None = None) -> int:
        """Purge sessions past their expiry; returns the number of rows removed."""
        if now is None:
            now = datetime.now(UTC)
        stmt = delete(Session).where(Session.expires_at <= now)
        result = await self.session.execute(stmt)
        return result.rowcount
