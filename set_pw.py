import asyncio, sys
from app.database import async_session_factory
from app.repositories.user import UserRepository
from app.services.password import hash_password, validate_password

async def main():
    email, pw = sys.argv[1], sys.argv[2]
    validate_password(pw, email=email)
    async with async_session_factory() as s:
        repo = UserRepository(s)
        u = await repo.get_by_email(email)
        u.password_hash = hash_password(pw)
        await s.commit()
        print("Password set.")

asyncio.run(main())
