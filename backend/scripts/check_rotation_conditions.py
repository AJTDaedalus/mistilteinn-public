"""Operator CLI — list stored rotations whose `group_condition` is outside the vocabulary.

Usage:
    python -m scripts.check_rotation_conditions

Security audit F2. The request schema now refuses such a condition and the compiler refuses
to emit one, but rows saved before that check are still in the table. Nothing they hold can
reach a config any more — compile, copy and the library all refuse or skip them — so this is
a report for the operator, not a repair: it prints each offending rotation's id, owner,
visibility and the condition, and exits 1 if there are any. It changes nothing.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.rotation import Rotation
from app.services.rotation_conditions import is_allowed_condition


async def find_offending() -> list[tuple[str, str | None, str, str]]:
    """`(rotation id, owner id, visibility, condition)` for every condition that fails."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    found: list[tuple[str, str | None, str, str]] = []
    try:
        async with async_sessionmaker(engine)() as session:
            rows = (await session.execute(select(Rotation))).scalars()
            for rotation in rows:
                for step in rotation.steps or []:
                    condition = str(step.get("group_condition") or "") if isinstance(
                        step, dict) else ""
                    if condition and not is_allowed_condition(condition):
                        found.append((
                            str(rotation.id), rotation.owner_id,
                            str(rotation.visibility), condition,
                        ))
    finally:
        await engine.dispose()
    return found


def main() -> None:
    """Print the offending rows; exit 1 if there are any."""
    found = asyncio.run(find_offending())
    for rotation_id, owner_id, visibility, condition in found:
        print(f"{rotation_id}\towner={owner_id}\t{visibility}\t{condition!r}")
    print(f"{len(found)} step(s) carry a condition outside the vocabulary.", file=sys.stderr)
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
