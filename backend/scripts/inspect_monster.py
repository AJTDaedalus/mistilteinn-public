import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


async def inspect() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        r = await session.execute(
            text(
                "select name, hit_index, damage_base, anomaly_buildup from attacks "
                "where agent_id = (select id from agents where name = 'Yanagi') "
                "and name like '%EX Special%'"
            )
        )
        for row in r.all():
            print(row)
    await engine.dispose()


asyncio.run(inspect())
