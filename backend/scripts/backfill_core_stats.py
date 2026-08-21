r"""One-off backfill of Agent.core_stats from ZO's allStat_gen.json.

SUPERSEDED (2026-07-25). ``nanoka_importer.py`` now populates ``core_stats``
directly from nanoka's ``extra_level`` block, covering all 58 agents including
ones newer than any ZO snapshot, so a normal ``scripts/seed_db.py`` run no
longer needs this script at all.

**Do not run this after a nanoka seed.** ZO's snapshot lags, and this script
would overwrite verified nanoka values with staler ones. When the two were
compared, nanoka reproduced 51 of ZO's 53 rows exactly; the 2 that differed
were both hand-authored overrides that turned out to be wrong (see the header
of ``app/data/core_stats_overrides.yaml``). This script is retained only for
seeding paths that do not go through nanoka — e.g. the offline hakushin
importer, which does not populate ``core_stats``.

ZO stores per-tier core passive bonuses (atk/crit_/...) in the
``coreStats`` array (6 entries, A=index 0..F=index 5). The nanoka
importer doesn't capture these — without them YSG, Caesar, etc. miss
their +14.4% / +24% crit rate from a maxed core, and ATK is similarly
underestimated. Match agents by full_name then name against ZO and
copy ``coreStats`` verbatim.

Agents missing from ZO's snapshot (newer than its last refresh) fall
through to ``app/data/core_stats_overrides.yaml`` — a hand-authored
table keyed by normalized name. The override always wins when present;
if neither source has the agent, ``core_stats`` is left as ``NULL`` and
the snapshot builder treats it as a zero contribution.

Run from the conda env (container DNS is broken on WSL2 hosts, so
``docker compose exec`` cannot even resolve the ``db`` service name)::

    cd backend
    DATABASE_URL="postgresql+asyncpg://fairy:fairy_dev@localhost:5432/fairy" \\
        python -m scripts.backfill_core_stats ../references/zo-allStat_gen.json
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models.agent import Agent

_OVERRIDES_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "data" / "core_stats_overrides.yaml"
)


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


async def main(zo_path: Path) -> None:  # noqa: PLR0912 — flat backfill flow
    """Copy ZO/override ``coreStats`` onto every matching agent row."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    raw = json.loads(zo_path.read_text())
    chars = raw.get("char") or raw.get("characters") or {}
    if not chars:
        msg = f"ZO file at {zo_path} has no 'char' map"
        raise SystemExit(msg)

    by_norm: dict[str, list] = {}
    for key, data in chars.items():
        cs = data.get("coreStats")
        if not cs:
            continue
        by_norm[_normalize(key)] = cs

    overrides: dict[str, list] = {}
    if _OVERRIDES_PATH.exists():
        raw_yaml = yaml.safe_load(_OVERRIDES_PATH.read_text()) or {}
        overrides = {_normalize(k): v for k, v in raw_yaml.items()}

    print(f"ZO has {len(by_norm)} characters with coreStats; {len(overrides)} overrides loaded")

    async with engine.connect() as conn:
        result = await conn.execute(select(Agent.id, Agent.name, Agent.full_name))
        rows = list(result.all())

    matched_zo = 0
    matched_override = 0
    missing: list[str] = []
    async with engine.begin() as conn:
        for agent_id, name, full_name in rows:
            chosen: list | None = None
            origin = ""
            for candidate in (full_name or "", name):
                key = _normalize(candidate)
                # Override beats ZO; useful when an agent's ZO entry lags
                # behind a kit revision.
                if key in overrides:
                    chosen = overrides[key]
                    origin = "override"
                    break
                if key in by_norm:
                    chosen = by_norm[key]
                    origin = "zo"
                    break
            if chosen is not None:
                await conn.execute(
                    Agent.__table__.update().where(Agent.id == agent_id).values(core_stats=chosen),
                )
                if origin == "override":
                    matched_override += 1
                else:
                    matched_zo += 1
            else:
                missing.append(name)

    total = matched_zo + matched_override
    print(f"matched: {total}/{len(rows)} (ZO={matched_zo}, override={matched_override})")
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
