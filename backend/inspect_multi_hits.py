import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.agent import Agent, Attack


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(select(Agent).order_by(Agent.name))
        agents = result.scalars().all()

        output = []
        for agent in agents:
            result = await session.execute(
                select(Attack)
                .where(Attack.agent_id == agent.id)
                .order_by(Attack.skill_key, Attack.name, Attack.hit_index)
            )
            attacks = result.scalars().all()

            move_groups = {}
            for att in attacks:
                move_groups.setdefault(att.name, []).append(att)

            multi_moves = {name: hits for name, hits in move_groups.items() if len(hits) > 1}

            if multi_moves:
                output.append("==================================================")
                output.append(f"Agent: {agent.name}")
                output.append("==================================================")
                for move_name, hits in sorted(multi_moves.items()):
                    output.append(
                        f"Move: {move_name} ({len(hits)} hits, Key: {hits[0].skill_key})"
                    )
                    output.extend(
                        f"  - hit_index={hit.hit_index}: damage_base={hit.damage_base}, "
                        f"stun_base={hit.stun_base}, energy_gain={hit.energy_gain}, "
                        f"anomaly_buildup={hit.anomaly_buildup}"
                        for hit in hits
                    )
                output.append("\n")

        with open("all_multi_moves.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(output))

if __name__ == "__main__":
    import sys
    sys.path.append("/app")
    asyncio.run(main())
