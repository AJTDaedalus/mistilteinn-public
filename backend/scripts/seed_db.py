"""Seed database with game data from nanoka.cc.

Usage:
    python -m scripts.seed_db              # Default: fetch from nanoka.cc (latest, includes beta)
    python -m scripts.seed_db --version 2.7  # Specific version
    python -m scripts.seed_db --local /path/to/zzz-hakushin-data  # Offline (PascalCase JSON)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.data.importers.dimbreath_resource_cost_importer import DimbreathResourceCostImporter
from app.data.importers.hakushin_core_description_patch_importer import (
    HakushinCoreDescriptionPatchImporter,
)
from app.data.importers.hakushin_json_importer import HakushinJsonImporter
from app.data.importers.hakushin_mindscape_description_patch_importer import (
    HakushinMindscapeDescriptionPatchImporter,
)
from app.data.importers.nanoka_importer import NanokaImporter
from scripts.download_icons import download_all_icons
from scripts.seed_skill_overrides import apply_skill_overrides
from scripts.verify_seed import (
    SeedVerificationError,
    verify_every_agent_has_attacks,
    verify_tripwires,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _verify_post_seed() -> None:
    """Check the post-seed tripwires; exit non-zero on mismatch instead of shipping silently."""
    logger.info("Verifying post-seed tripwires…")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await verify_tripwires(session)
            await verify_every_agent_has_attacks(session)
    except SeedVerificationError:
        logger.exception("Post-seed sanity check failed")
        sys.exit(1)
    finally:
        await engine.dispose()
    logger.info("Post-seed tripwires OK.")


async def main(args: argparse.Namespace) -> None:
    """Run the full seed pipeline: primary import, patches, overrides, icons."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        if args.local:
            logger.info("Seeding from local directory: %s", args.local)
            importer = HakushinJsonImporter(session, data_dir=args.local)
            counts = await importer.import_all()
        else:
            logger.info(
                "Seeding from nanoka.cc (version=%s)",
                args.version or "latest",
            )
            importer = NanokaImporter(session, version=args.version)
            try:
                counts = await importer.import_all()
            finally:
                await importer.close()

    async with session_factory() as session, session.begin():
        logger.info("Patching blank CoreSkill descriptions from zzz-hakushin-data…")
        desc_importer = HakushinCoreDescriptionPatchImporter(session)
        try:
            desc_patch_count = await desc_importer.patch_blank_core_descriptions()
        finally:
            await desc_importer.close()
        logger.info("  core_skill descriptions patched: %d", desc_patch_count)

    async with session_factory() as session, session.begin():
        logger.info("Patching blank Mindscape descriptions from zzz-hakushin-data…")
        mindscape_desc_importer = HakushinMindscapeDescriptionPatchImporter(session)
        try:
            mindscape_patch_count = (
                await mindscape_desc_importer.patch_blank_mindscape_descriptions()
            )
        finally:
            await mindscape_desc_importer.close()
        logger.info("  mindscape descriptions patched: %d", mindscape_patch_count)

    async with session_factory() as session, session.begin():
        logger.info("Seeding ex_energy_cost from Dimbreath extract…")
        rc_importer = DimbreathResourceCostImporter(session)
        rc_count = await rc_importer.seed_ex_energy_costs()
        logger.info("  ex_energy_cost: %d agents updated", rc_count)
        # Same file, second pass: every priced action verbatim, no "which one is THE cost?"
        # judgement. In the same transaction as the scalar above so the two cannot disagree
        # about which extract they came from.
        row_count = await rc_importer.seed_resource_cost_rows()
        logger.info("  agent_resource_costs: %d rows written", row_count)

    async with session_factory() as session, session.begin():
        logger.info("Applying skill overrides…")
        await apply_skill_overrides(session)

    await engine.dispose()

    await _finish(counts, skip_icons=args.skip_icons)


async def _finish(counts: dict[str, int], *, skip_icons: bool) -> None:
    """Log final counts, run post-seed tripwires, then download icons."""
    logger.info("Seed complete:")
    for entity, count in counts.items():
        logger.info("  %s: %d", entity, count)

    await _verify_post_seed()

    if not skip_icons:
        logger.info("Downloading and localizing missing assets/icons…")
        await download_all_icons()
    else:
        logger.info("Skipping icon download (--skip-icons)")


def cli() -> None:
    """Parse CLI args and run the seed pipeline."""
    parser = argparse.ArgumentParser(description="Seed fairy database with game data")
    parser.add_argument(
        "--version",
        help="nanoka.cc game version to fetch (default: latest, includes beta)",
    )
    parser.add_argument(
        "--local",
        help="Path to local zzz-hakushin-data directory (offline mode)",
    )
    parser.add_argument(
        "--skip-icons",
        action="store_true",
        help="Skip icon download (useful in prod containers without a writable frontend volume)",
    )
    args = parser.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
