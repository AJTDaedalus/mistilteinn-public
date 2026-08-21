import asyncio
import sys

# Add backend directory to path
sys.path.append("/app")

from app.db.session import SessionLocal
from sqlalchemy import text


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT DISTINCT faction FROM agents"))
        factions = [row[0] for row in result.fetchall() if row[0]]
        print("Unique Factions in Database:")
        for f in sorted(factions):
            print(f"  - '{f}'")


if __name__ == "__main__":
    # Set DB URL
    import asyncio

    asyncio.run(main())
