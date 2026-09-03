"""Seed furnishing suites from the pinned nanoka fixture.

`TASKS_account_tracking.md` 3.4. Reads `tests/fixtures/nanoka_gi/suite.json` — the **committed**
capture at `FIXTURE_VERSION`, not a live fetch — for the reason `app/data/yuanshen/` records:
a seed that depends on the network is a seed that fails differently on different days.

    cd backend && python -m scripts.seed_teapot
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.base import generate_uuid7
from app.models.teapot import FurnishingSuite, FurnishingSuiteFavorite

#: The committed capture, **under `app/data/` rather than `tests/fixtures/`**.
#:
#: `tests/` is excluded from the production image (`backend/.dockerignore`), so seed data kept
#: there deploys as a `FileNotFoundError` — which is exactly how the first deploy of this
#: tracker failed. Data the running app needs lives beside the app, like
#: `app/data/yuanshen/snapshot/` already does.
FIXTURE = Path(__file__).resolve().parent.parent / "app" / "data" / "teapot" / "suite.json"

#: Below this, the capture is broken rather than the patch being small.
#:
#: The same reasoning `seed_db`'s prune refusal uses: an index that comes back empty or
#: truncated is a valid HTTP 200 that no retry detects, and wiping the table on one would be a
#: silent loss. 109 suites at 7.0.51; a patch removing more than a handful is not a patch.
MINIMUM_SUITES = 90


async def seed() -> int:
    """Insert or update every suite, returning how many were written."""
    published: dict[str, dict] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if len(published) < MINIMUM_SUITES:
        msg = (
            f"the fixture holds {len(published)} suites and at least {MINIMUM_SUITES} are "
            f"expected. Refusing to seed: a truncated capture would delete real rows."
        )
        raise SystemExit(msg)

    engine = create_async_engine(settings.DATABASE_URL)
    written = 0
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        existing = {
            suite.nanoka_id: suite
            for suite in (await session.execute(select(FurnishingSuite))).scalars()
        }
        for nanoka_id, entry in published.items():
            suite = existing.get(nanoka_id)
            if suite is None:
                suite = FurnishingSuite(id=generate_uuid7(), nanoka_id=nanoka_id)
                session.add(suite)
            suite.name = entry.get("en") or nanoka_id
            suite.placement = entry.get("type") or ""
            suite.icon = entry.get("icon") or ""
            suite.units = entry.get("units") or {}
            written += 1

        await session.flush()

        # **Favourites are replaced wholesale, per suite.** A patch can take a character off a
        # set as well as add one, and merging would leave the removed one behind for ever.
        suites = {
            suite.nanoka_id: suite
            for suite in (await session.execute(select(FurnishingSuite))).scalars()
        }
        await session.execute(delete(FurnishingSuiteFavorite))
        for nanoka_id, entry in published.items():
            suite = suites[nanoka_id]
            for character in entry.get("favorite") or []:
                session.add(FurnishingSuiteFavorite(
                    suite_id=suite.id, character_nanoka_id=str(character),
                ))
        await session.commit()
    await engine.dispose()
    return written


async def main() -> int:
    """Seed, and report how many suites were written."""
    written = await seed()
    print(f"seeded {written} furnishing suites")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
