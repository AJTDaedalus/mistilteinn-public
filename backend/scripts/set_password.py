"""Admin CLI — set password for a user by email.

Usage:
    python -m scripts.set_password <email>
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.repositories.user import UserRepository
from app.services.password import hash_password, validate_password


async def set_password(email: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(email)

        if user is None:
            print(f"Error: no user found with email '{email}'", file=sys.stderr)
            sys.exit(1)

        password = getpass.getpass(f"New password for '{email}': ")

        try:
            validate_password(password, email=email)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        user.password_hash = hash_password(password)
        await session.commit()

    await engine.dispose()
    print(f"Password updated for '{email}'.")


def main() -> None:
    if len(sys.argv[1:]) != 1:
        print("Usage: python -m scripts.set_password <email>", file=sys.stderr)
        sys.exit(1)

    asyncio.run(set_password(sys.argv[1]))


if __name__ == "__main__":
    main()
