"""One-off backfill of Agent.promotion_stats from ZO's allStat_gen.json.

The nanoka importer didn't populate promotion bonuses (the discrete
ZZZ stat jumps at lv11/21/31/41/51/60), so build_snapshot_from_db was
treating every agent as a level-1 stat block. Match by full_name (or
fall back to name) against the GO/ZO export and copy the
``promotionStats`` array verbatim.

Run inside the backend container::

    docker compose exec backend python -m scripts.backfill_promotion_stats \\
        /references/genshin-optimizer-allStat_gen.json

If you don't have a local mount, point the script at
``libs/zzz/stats/src/allStat_gen.json`` from a clone of GO. The path
argument is required so we don't surprise the operator with a default.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models.agent import Agent

ENGINE = None


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


async def main(zo_path: Path) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    raw = json.loads(zo_path.read_text())
    chars = raw.get("char") or raw.get("characters") or {}
    if not chars:
        msg = f"ZO file at {zo_path} has no 'char' map"
        raise SystemExit(msg)

    # Build lookup keyed on normalized character name.
    by_norm: dict[str, list] = {}
    for key, data in chars.items():
        promo = data.get("promotionStats")
        if not promo:
            continue
        by_norm[_normalize(key)] = promo

    print(f"ZO has {len(by_norm)} characters with promotionStats")

    async with engine.connect() as conn:
        result = await conn.execute(select(Agent.id, Agent.name, Agent.full_name))
        rows = list(result.all())

    matched = 0
    missing: list[str] = []
    async with engine.begin() as conn:
        for agent_id, name, full_name in rows:
            for candidate in (full_name or "", name):
                key = _normalize(candidate)
                if key in by_norm:
                    await conn.execute(
                        Agent.__table__.update()
                        .where(Agent.id == agent_id)
                        .values(promotion_stats=by_norm[key]),
                    )
                    matched += 1
                    break
            else:
                missing.append(name)

    print(f"matched: {matched}/{len(rows)}")
    if missing:
        print("unmatched (need manual mapping):")
        for n in missing:
            print(f"  - {n}")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:  # noqa: PLR2004
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(main(Path(sys.argv[1])))
