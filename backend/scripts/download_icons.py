"""Utility script to download and vendor icons from static.nanoka.cc to local repository.

Queries the database for all agents, W-engines, and disc sets, parses their
icon basenames, and downloads them concurrently.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.agent import Agent
from app.models.disc import DiscSet
from app.models.w_engine import WEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CDN_BASE_URL = "https://static.nanoka.cc/assets/zzz"
CONCURRENCY_LIMIT = 10
HTTP_OK = 200


def get_icons_dir() -> str:
    """Determine the icons directory to write to (handles Docker and local running)."""
    if os.path.exists("/frontend_icons"):
        return "/frontend_icons"
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public", "icons")
    )


def extract_basename(path: str | None) -> str | None:
    """Extract the clean basename without directory path or extension."""
    if not path:
        return None
    # e.g., "UI_Icon_Agent_Miyabi.png" or "icon/UI_Icon_Agent_Miyabi"
    basename = os.path.basename(path)
    # Strip extension
    for ext in (".png", ".webp", ".jpg", ".jpeg"):
        if basename.lower().endswith(ext):
            basename = basename[: -len(ext)]
            break
    return basename.strip()


async def download_one_icon(
    client: httpx.AsyncClient,
    basename: str,
    icons_dir: str,
    semaphore: asyncio.Semaphore,
) -> bool:
    """Download a single icon from the CDN and save it locally as .webp."""
    dest_path = os.path.join(icons_dir, f"{basename}.webp")
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        # File already exists and is not empty, skip downloading
        return True

    url = f"{CDN_BASE_URL}/{basename}.webp"
    async with semaphore:
        try:
            resp = await client.get(url)
        except Exception:
            logger.exception("Error downloading icon %s", basename)
            return False

        if resp.status_code == HTTP_OK:
            try:
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
            except OSError:
                # Same contract as the directory guard above: vendoring icons must
                # never fail a seed that has already committed (#115). The dir was
                # writable when we checked, but a per-file write can still fail
                # (ENOSPC, a read-only remount, a clobbered path).
                logger.warning(
                    "Could not write icon %s to %s; skipping it. "
                    "Icons are vendored in the repo, so this does not affect the seeded data.",
                    basename,
                    dest_path,
                    exc_info=True,
                )
                return False
            logger.info("Successfully downloaded: %s.webp", basename)
            return True
        logger.warning(
            "Failed to download icon %s (Status: %d) from url: %s",
            basename,
            resp.status_code,
            url,
        )
        return False


def ensure_icons_dir_writable(icons_dir: str) -> bool:
    """Create ``icons_dir`` if needed; return False with a warning if it is unusable.

    Vendoring icons is a repo-authoring step, not part of a database seed. In a prod
    container the dev ``/frontend_icons`` bind mount is absent (``docker-compose.prod.yml``
    sets ``volumes: !reset []``), so ``get_icons_dir`` falls back to ``/frontend/public/icons``
    and ``/`` is not writable. Degrading to a warning keeps a seed that has already committed
    its data from exiting non-zero on its last line — a traceback there is indistinguishable
    from a failed seed and invites an operator to back a good one out (#115).
    """
    try:
        os.makedirs(icons_dir, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Skipping icon download: cannot create icons directory %s (%s). "
            "Icons are vendored in the repo, so this does not affect the seeded data.",
            icons_dir,
            exc,
        )
        return False

    if not os.access(icons_dir, os.W_OK):
        logger.warning(
            "Skipping icon download: icons directory %s is not writable. "
            "Icons are vendored in the repo, so this does not affect the seeded data.",
            icons_dir,
        )
        return False

    return True


async def _icon_basenames_from_db() -> set[str]:
    """Collect every referenced icon basename from agents, W-Engines and disc sets."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    basenames: set[str] = set()
    try:
        async with session_factory() as session:
            for column in (Agent.icon_path, WEngine.icon_path, DiscSet.icon_path):
                result = await session.execute(select(column).where(column != ""))
                for row in result.all():
                    base = extract_basename(row[0])
                    if base:
                        basenames.add(base)
    finally:
        await engine.dispose()

    return basenames


async def download_all_icons() -> None:
    """Query the database for all agents, W-engines, and disc sets, and download missing icons."""
    icons_dir = get_icons_dir()
    if not ensure_icons_dir_writable(icons_dir):
        return
    logger.info("Localizing and vendoring icons to: %s", icons_dir)

    basenames = await _icon_basenames_from_db()

    if not basenames:
        logger.info("No icon paths found in the database.")
        return

    logger.info("Found %d unique icon assets to localize.", len(basenames))

    # Concurrency control
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            download_one_icon(client, basename, icons_dir, semaphore)
            for basename in sorted(basenames)
        ]
        # return_exceptions: one unexpected failure among 200-odd downloads must not
        # propagate out of a post-commit seed step (#115). Anything that escapes
        # download_one_icon's own handlers is logged and counted as a miss.
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for basename, r in zip(sorted(basenames), results, strict=True):
        if isinstance(r, BaseException):
            logger.warning("Unexpected error localizing icon %s: %r", basename, r)

    success_count = sum(1 for r in results if r is True)
    logger.info(
        "Icon download and localization summary: %d/%d successfully localized locally.",
        success_count,
        len(basenames),
    )


def run_download_icons() -> None:
    """Synchronous entry point to run the async download process."""
    try:
        asyncio.run(download_all_icons())
    except Exception:
        logger.exception("Failed to run icon downloader")


if __name__ == "__main__":
    run_download_icons()
