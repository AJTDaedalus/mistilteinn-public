"""User repository — email/password, admin-approval flow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.base import BaseRepository
from app.services.email_policy import normalize


class UserRepository(BaseRepository[User]):
    """Sole data-access point for the User entity (login and admin-approval state)."""

    model = User

    async def get_by_email(self, email: str) -> User | None:
        """Look up a user by any form of their address.

        Matches on `email_normalized`, not the stored `email`, so the address a person
        types identifies their account whatever case or Gmail alias they use. The raw
        column keeps the exact form for sending; it is not an identity key.

        Querying the raw column here was an account-lockout bug with no recovery path.
        Registration normalizes (`get_by_normalized_email`), so an account created as
        `Casey.Jones@Example.COM` is found when someone re-registers `casey.jones@…` — but
        login, password reset and resend-verification each queried the raw column, so the
        same person got `401 Invalid email or password` from login, a silent 202 and no
        mail from reset, and "someone tried to register your address" from register. Three
        endpoints, three different answers, and no way to discover the exact string that
        would work.
        """
        return await self.get_by_normalized_email(normalize(email))

    async def get_by_normalized_email(self, normalized: str) -> User | None:
        """Look up by the uniqueness key, so Gmail aliases resolve to one account."""
        stmt = select(User).where(User.email_normalized == normalized)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_stale_unverified(self, max_age_days: int = 30) -> int:
        """Drop PENDING accounts that never confirmed their address; returns rows removed.

        Bots that register and never click would otherwise accumulate forever, and the
        `users` table is where an operator looks to judge whether signups are organic.
        Scoped tightly on purpose: `status == PENDING` **and** never verified. An
        approved account is never touched, and neither is one awaiting manual approval
        that *did* verify — that person is waiting on us, not the other way round.
        """
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        stmt = delete(User).where(
            User.status == UserStatus.PENDING,
            User.email_verified_at.is_(None),
            User.created_at <= cutoff,
        )
        result = await self.session.execute(stmt)
        return result.rowcount
