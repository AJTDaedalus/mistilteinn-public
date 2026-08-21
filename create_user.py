import asyncio, sys
from app.database import async_session_factory
from app.repositories.user import UserRepository
from app.models.user import User
from app.models.enums import UserStatus
from app.services.password import hash_password, validate_password

async def main():
    email, pw = sys.argv[1], sys.argv[2]
    validate_password(pw, email=email)
    async with async_session_factory() as s:
        repo = UserRepository(s)
        existing = await repo.get_by_email(email)
        if existing:
            existing.password_hash = hash_password(pw)
            existing.status = UserStatus.APPROVED
            print(f"Updated existing user {email}")
        else:
            user = User(
                email=email,
                label=email.split("@")[0],
                password_hash=hash_password(pw),
                status=UserStatus.APPROVED,
            )
            s.add(user)
            print(f"Created user {email}")
        await s.commit()

asyncio.run(main())
