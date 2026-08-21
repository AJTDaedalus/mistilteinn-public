"""Seed the database with Genshin game data from nanoka.cc.

    cd backend && python -m scripts.seed_db                  # all four passes
    cd backend && python -m scripts.seed_db --dry-run        # fetch and count, write nothing
    cd backend && python -m scripts.seed_db --only character weapon
    cd backend && python -m scripts.seed_db --version 7.0.50 # reproduce an older run
    cd backend && python -m scripts.seed_db --force-prune     # allow a large prune

Four passes over the nanoka GI source — character, weapon, artifact, monster — followed by
a **provenance row** recording the version pinned from `manifest.json -> gi.latest` and how
the run went (`seed_runs`). Re-running against an unchanged index is a no-op: every pass
upserts on `nanoka_id` and prunes what left the index.

**Exit codes are load-bearing.** 0 only when every pass completed with no failed ids **and**
no pass refused to prune; 1 otherwise, with the reasons listed. A seed that reports success
while three characters failed to map is the green-by-absence failure this repo's CLAUDE.md
exists to prevent, and it is how fairy shipped a silent field-mapping regression.

A pass **refuses to prune** when an implausible share of a table is missing from the index —
nanoka answering `{}` with HTTP 200 during a deploy is a valid response no retry can detect,
and deleting the whole catalogue on it would take every user's builds with it through
`ON DELETE CASCADE`. `--force-prune` overrides that once a human has read the numbers.

The version is pinned once per run, so a seed never straddles two patches, and `--version`
reproduces an old one exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.data.importers.nanoka_gi_importer import ENTITIES, NanokaGIImporter
from app.database import async_session_factory
from app.models.seed_provenance import SeedRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("seed_db")

#: Entity name → the importer method that seeds it, in seed order.
PASSES: dict[str, str] = {
    "character": "import_characters",
    "weapon": "import_weapons",
    "artifact": "import_artifact_sets",
    "monster": "import_enemies",
}


async def dry_run(version: str | None) -> int:
    """Fetch every index and one detail each, report counts, write nothing."""
    importer = NanokaGIImporter(_NoSession(), version=version)
    try:
        pinned = await importer.version()
        print(f"nanoka GI {pinned} (dry run — nothing written)")
        summaries = await importer.dry_run(sample_details=True)
    finally:
        await importer.close()
    failed = False
    for summary in summaries.values():
        print(f"  {summary}")
        failed = failed or not summary.ok
    return 1 if failed else 0


async def run_passes(
    session: AsyncSession,
    importer: NanokaGIImporter,
    entities: list[str],
    *,
    commit: bool = True,
) -> tuple[SeedRun, dict[str, dict], bool]:
    """Run the passes against an open session and record a `SeedRun` row.

    Separate from `seed()` so the tests can drive it with a fixture-backed transport and a
    rolled-back session. `commit=False` flushes instead, for exactly that.
    """
    save = session.commit if commit else session.flush
    pinned = await importer.version()
    run = SeedRun(
        source="nanoka-gi",
        version=pinned,
        started_at=datetime.now(UTC),
        succeeded=False,
        entity_counts={},
    )
    session.add(run)
    # Saved before the first pass, so a run that dies mid-seed still leaves a row saying
    # which version it was part way through — `succeeded` stays False until the end.
    await save()
    print(f"nanoka GI {pinned} — seeding {', '.join(entities)}")

    for entity in entities:
        await getattr(importer, PASSES[entity])()
        await save()
        print(f"  {importer.results[-1]}")

    counts = {
        result.entity: {
            "total": result.total,
            "imported": result.imported,
            "skipped": result.skipped,
            "pruned": result.pruned,
            "failed": result.failed,
            # Recorded, not just printed: a run that refused to prune left rows the index
            # no longer lists, and the next reader of `seed_runs` should see that.
            "prune_blocked": result.prune_blocked,
        }
        for result in importer.results
    }
    ok = all(result.ok for result in importer.results)
    run.entity_counts = counts
    run.finished_at = datetime.now(UTC)
    run.succeeded = ok
    await save()
    return run, counts, ok


async def seed(version: str | None, entities: list[str], *, force_prune: bool = False) -> int:
    """Run the requested passes against the configured database; return an exit code."""
    async with async_session_factory() as session:
        importer = NanokaGIImporter(session, version=version, force_prune=force_prune)
        try:
            _run, counts, ok = await run_passes(session, importer, entities)
        finally:
            await importer.close()

    if not ok:
        print("\nThis run did NOT succeed (nothing was rolled back):", file=sys.stderr)
        for entity, entry in counts.items():
            if entry["failed"]:
                print(f"  {entity}: failed ids {entry['failed']}", file=sys.stderr)
            if entry["prune_blocked"]:
                print(f"  {entity}: prune refused — {entry['prune_blocked']}", file=sys.stderr)
        return 1
    return 0


class _NoSession:
    """A stand-in that turns any database call on the dry-run path into a crash.

    `NanokaGIImporter` needs a session to construct, and `dry_run()` must not touch one.
    Passing `None` would let an accidental write raise a confusing `AttributeError` on
    `None`; this raises something that says what went wrong.
    """

    def __getattr__(self, name: str) -> object:
        msg = f"--dry-run touched the database (session.{name}). It must not write."
        raise AssertionError(msg)


def main() -> int:
    """Parse arguments and run the seed."""
    parser = argparse.ArgumentParser(description="Seed Genshin game data from nanoka.cc.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch every index and one detail each, report counts, and write nothing",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="nanoka GI version to seed from (default: pin manifest.json -> gi.latest)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=ENTITIES,
        default=list(ENTITIES),
        metavar="ENTITY",
        help=f"run only these passes (of {', '.join(ENTITIES)})",
    )
    parser.add_argument(
        "--force-prune",
        action="store_true",
        help="delete stale rows even when the guard considers the index implausible",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.dry_run:
        return asyncio.run(dry_run(args.version))
    return asyncio.run(seed(args.version, args.only, force_prune=args.force_prune))


if __name__ == "__main__":
    raise SystemExit(main())
