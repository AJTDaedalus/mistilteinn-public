"""Give every stored rotation a `tree`, refusing if any would change meaning.

`TASKS_rotation_language.md` 4.3 and 4.4. The gate on Phase 4 is that **no saved rotation
changes meaning**, and this is where that is enforced against real data rather than fixtures:
each rotation is converted to a tree, converted back, and both forms compiled. A single
character of difference in the emitted gcsim text fails the run and nothing is written.

    cd backend && python -m scripts.backfill_rotation_trees            # dry run, the default
    cd backend && python -m scripts.backfill_rotation_trees --write

**Dry run by default**, for the same reason `seed_db` refuses to prune an implausible share of
a table: a migration that silently rewrites user data is one nobody can review afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.services.rotation_compiler import compile_rotation
from app.services.rotation_tree_migration import steps_from_tree, tree_from_steps


class _Character:
    """What `compile_rotation` reads off a catalogue row, and nothing more."""

    def __init__(self, nanoka_id: str, name: str, element: str) -> None:
        self.nanoka_id, self.name, self.element = nanoka_id, name, element


async def _load(conn: AsyncConnection) -> tuple[list, dict[str, _Character]]:
    rotations = (await conn.execute(text(
        "select id, name, steps from rotations order by created_at"))).all()
    rows = (await conn.execute(text(
        "select nanoka_id, name, element from characters"))).all()
    return rotations, {r.nanoka_id: _Character(r.nanoka_id, r.name, r.element) for r in rows}


def _check(rotation: object, roster: dict[str, _Character]) -> tuple[dict | None, str]:
    """`(tree, "")` when the conversion is provably faithful, or `(None, reason)`."""
    steps = [dict(s) for s in (rotation.steps or [])]
    if not steps:
        return None, "no steps"
    try:
        tree = tree_from_steps(steps)
        back = steps_from_tree(tree)
    except ValueError as exc:
        return None, f"cannot be represented as steps again: {exc}"
    try:
        before = compile_rotation(steps, roster)
        after = compile_rotation([dict(s) for s in back], roster)
    except Exception as exc:  # any compile failure is a refusal, not a crash
        return None, f"did not compile: {type(exc).__name__}: {exc}"
    if before != after:
        return None, "compiles to different gcsim text"
    return tree.model_dump(mode="json"), ""


async def main() -> int:
    """Run the check, and write only when told to and only when nothing refused."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="actually write; without it this only reports")
    args = parser.parse_args()

    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://mistilteinn:mistilteinn_dev@localhost:5432/mistilteinn",
    )
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rotations, roster = await _load(conn)

    ready, refused = [], []
    for rotation in rotations:
        tree, reason = _check(rotation, roster)
        (ready if tree is not None else refused).append((rotation, tree, reason))

    for rotation, _, reason in refused:
        print(f"  REFUSED  {rotation.name!r}: {reason}")
    print(f"\n{len(rotations)} rotations: {len(ready)} convert faithfully, "
          f"{len(refused)} refused")

    if refused:
        print("\nNothing written. A rotation that compiles differently is the one thing this "
              "migration may not do, so a single refusal stops the run.")
        await engine.dispose()
        return 1
    if not args.write:
        print("\nDry run. Re-run with --write to store these trees.")
        await engine.dispose()
        return 0

    async with engine.begin() as conn:
        for rotation, tree, _ in ready:
            await conn.execute(
                text("update rotations set tree = cast(:tree as jsonb) where id = :id"),
                {"tree": __import__("json").dumps(tree), "id": rotation.id},
            )
    print(f"\nWrote {len(ready)} trees.")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
