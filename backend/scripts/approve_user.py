"""Admin CLI — approve a pending user by email.

Usage:
    python -m scripts.approve_user <email>
"""

from __future__ import annotations

import asyncio
import datetime
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.enums import UserStatus
from app.repositories.user import UserRepository


async def approve_user(email: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(email)

        if user is None:
            print(f"Error: no user found with email '{email}'", file=sys.stderr)
            sys.exit(1)

        if user.status == UserStatus.APPROVED:
            print(f"User '{email}' is already approved.")
            return

        user.status = UserStatus.APPROVED
        user.approved_at = datetime.datetime.now(datetime.UTC)
        await session.commit()

    await engine.dispose()
    print(f"Approved user '{email}'.")


def main() -> None:
    if len(sys.argv[1:]) != 1:
        print("Usage: python -m scripts.approve_user <email>", file=sys.stderr)
        sys.exit(1)

    asyncio.run(approve_user(sys.argv[1]))


if __name__ == "__main__":
    main()
