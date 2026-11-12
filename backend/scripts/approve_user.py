"""Admin CLI — approve a pending user by email.

Usage:
    python -m scripts.approve_user <email> [--allow-unverified]

**An unverified address is refused unless `--allow-unverified` is passed.** Until the
address is verified, nobody has shown that the person who chose the account's password
owns the inbox — approving it approves whoever registered first, which is the
pre-registration takeover in security audit F1. The flag is for accounts that predate
verification, or a local dev account whose mail goes to the console.
"""

from __future__ import annotations

import asyncio
import datetime
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.enums import UserStatus
from app.repositories.user import UserRepository

_USAGE = "Usage: python -m scripts.approve_user <email> [--allow-unverified]"
_ALLOW_UNVERIFIED = "--allow-unverified"


async def approve_user(email: str, *, allow_unverified: bool = False) -> None:
    """Mark the account at *email* APPROVED; refuse an unverified one without the flag."""
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

        if user.email_verified_at is None and not allow_unverified:
            print(
                f"Error: '{email}' has not verified its address, so nothing yet shows the "
                "password on the account belongs to the inbox's owner. Wait for the "
                f"verification link to be clicked, or pass {_ALLOW_UNVERIFIED} if you have "
                "confirmed the account another way.",
                file=sys.stderr,
            )
            sys.exit(1)

        user.status = UserStatus.APPROVED
        user.approved_at = datetime.datetime.now(datetime.UTC)
        await session.commit()

    await engine.dispose()
    print(f"Approved user '{email}'.")


def main() -> None:
    """Parse argv and run `approve_user`."""
    args = sys.argv[1:]
    allow_unverified = _ALLOW_UNVERIFIED in args
    positional = [a for a in args if a != _ALLOW_UNVERIFIED]
    if len(positional) != 1 or any(a.startswith("--") for a in positional):
        print(_USAGE, file=sys.stderr)
        sys.exit(1)

    asyncio.run(approve_user(positional[0], allow_unverified=allow_unverified))


if __name__ == "__main__":
    main()
