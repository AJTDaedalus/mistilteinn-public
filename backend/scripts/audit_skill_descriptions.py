"""B1: Read-only audit of skill description rows across all description-bearing import categories.

Outputs per-agent delta report: agents with >1 row per skill_key (agent_skills),
duplicate core_skill rows per level, and full name listings for priority agents.

Usage: docker compose exec backend python -m scripts.audit_skill_descriptions
"""

import asyncio
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        await audit_agent_skills(session)
        await audit_core_skills(session)
        await audit_priority_agents(session)


async def audit_agent_skills(session: AsyncSession) -> None:
    print("=" * 70)
    print("AGENT_SKILLS — agents with >1 row per skill_key (Part A delta)")
    print("=" * 70)

    result = await session.execute(
        text("""
        SELECT a.name AS agent, ags.skill_key, COUNT(*) AS cnt,
               array_agg(ags.name ORDER BY ags.name) AS names
        FROM agent_skills ags
        JOIN agents a ON ags.agent_id = a.id
        GROUP BY a.name, ags.skill_key
        HAVING COUNT(*) > 1
        ORDER BY a.name, ags.skill_key
    """)
    )
    rows = result.fetchall()
    print(f"  {len(rows)} (agent, skill_key) pairs with >1 row\n")

    by_agent: dict[str, list] = defaultdict(list)
    for r in rows:
        by_agent[r.agent].append((r.skill_key, r.cnt, r.names))

    for agent in sorted(by_agent):
        print(f"  {agent}:")
        for skill_key, cnt, names in sorted(by_agent[agent]):
            print(f"    [{skill_key}] ({cnt} rows):")
            for n in names:
                print(f"      - {n}")
    print()


async def audit_core_skills(session: AsyncSession) -> None:
    print("=" * 70)
    print("CORE_SKILLS — agents with >1 row per level (duplicate check)")
    print("=" * 70)

    result = await session.execute(
        text("""
        SELECT a.name AS agent, cs.level, COUNT(*) AS cnt,
               COUNT(DISTINCT cs.name) AS distinct_names,
               COUNT(DISTINCT cs.description) AS distinct_descs
        FROM core_skills cs
        JOIN agents a ON cs.agent_id = a.id
        GROUP BY a.name, cs.level
        HAVING COUNT(*) > 1
        ORDER BY a.name, cs.level
        LIMIT 40
    """)
    )
    rows = result.fetchall()
    if rows:
        print(f"  {len(rows)} (agent, level) pairs with >1 row:")
        current_agent = None
        for r in rows:
            if r.agent != current_agent:
                print(f"\n  {r.agent}:")
                current_agent = r.agent
            print(
                f"    L{r.level}: {r.cnt} rows, {r.distinct_names} distinct names, "
                f"{r.distinct_descs} distinct descs"
            )
    else:
        print("  No duplicate core_skill rows found.")
    print()


async def audit_priority_agents(session: AsyncSession) -> None:
    print("=" * 70)
    print("PRIORITY AGENTS — full agent_skill name listing (Aria, Grace, Burnice)")
    print("=" * 70)

    for agent_name in ("Aria", "Grace", "Burnice"):
        result = await session.execute(
            text("""
            SELECT ags.skill_key, ags.name, LEFT(ags.description, 200) AS desc_snippet
            FROM agent_skills ags
            JOIN agents a ON ags.agent_id = a.id
            WHERE a.name = :name
            ORDER BY ags.skill_key, ags.name
        """),
            {"name": agent_name},
        )
        rows = result.fetchall()
        if not rows:
            # Try partial match
            result2 = await session.execute(
                text("""
                SELECT DISTINCT a.name FROM agents a WHERE a.name ILIKE :pattern
            """),
                {"pattern": f"%{agent_name}%"},
            )
            matches = [r.name for r in result2.fetchall()]
            print(f"\n  {agent_name}: not found. Similar names: {matches}")
            continue

        print(f"\n  {agent_name} ({len(rows)} skill rows):")
        current_key = None
        for r in rows:
            if r.skill_key != current_key:
                print(f"    [{r.skill_key}]")
                current_key = r.skill_key
            print(f"      '{r.name}'")
            if r.desc_snippet:
                print(f"        > {r.desc_snippet[:180]}")

    # Also show core_skills for priority agents
    print()
    print("PRIORITY AGENTS — core_skills (full desc for L7 = max level):")
    for agent_name in ("Aria", "Grace", "Burnice"):
        result = await session.execute(
            text("""
            SELECT DISTINCT ON (cs.level) cs.level, cs.name, cs.description
            FROM core_skills cs
            JOIN agents a ON cs.agent_id = a.id
            WHERE a.name = :name
            ORDER BY cs.level, cs.name
        """),
            {"name": agent_name},
        )
        rows = result.fetchall()
        if not rows:
            continue
        print(f"\n  {agent_name} core skills:")
        for r in rows:
            print(f"    L{r.level}: '{r.name}'")
            print(f"      {r.description[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
