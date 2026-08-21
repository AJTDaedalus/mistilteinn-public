"""Admin CLI — create an approved user directly, or reset an existing one's password.

Usage:
    cd backend && python -m scripts.create_user <email>

Prompts for the password rather than taking it on the command line.

Why this exists alongside `POST /api/v1/auth/register` + `scripts.approve_user`: that pair
needs a running server, and it leaves the new account `PENDING` until an admin approves it.
This one talks to the database directly, which is what bootstrapping the *first* account
requires — there is nobody to approve it yet.

Ported from the untracked-purpose `create_user.py` that sat in the repo root (B.11), with the
house-style engine setup, the missing existence checks, and `getpass` in place of reading the
password from `sys.argv` — where it lands in shell history and in `ps` output.
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.password import hash_password, validate_password


async def create_user(email: str, password: str) -> None:
    """Create `email` as an APPROVED user, or reset its password if it already exists."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(email)

        if existing is not None:
            existing.password_hash = hash_password(password)
            existing.status = UserStatus.APPROVED
            await session.commit()
            print(f"Updated and approved existing user {email}")
        else:
            session.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    status=UserStatus.APPROVED,
                ),
            )
            await session.commit()
            print(f"Created approved user {email}")

    await engine.dispose()


def main() -> int:
    """Parse args, prompt for the password, and run."""
    if len(sys.argv) != 2:  # noqa: PLR2004
        print("Usage: python -m scripts.create_user <email>", file=sys.stderr)
        return 1

    email = sys.argv[1]
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1

    try:
        validate_password(password, email=email)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    asyncio.run(create_user(email, password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
