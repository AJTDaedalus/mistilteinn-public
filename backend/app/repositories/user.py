"""User repository — email/password, admin-approval flow."""

from __future__ import annotations

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Sole data-access point for the User entity (login and admin-approval state)."""

    model = User

    async def get_by_email(self, email: str) -> User | None:
        """Look up a user by email, used for login and registration checks."""
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
