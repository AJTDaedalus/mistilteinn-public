"""Print the nanoka GI version published right now.

    cd backend && python -m scripts.nanoka_latest_version

One line of output and nothing else, so a caller can read it into a shell variable. The
prod re-seed job does exactly that and hands the result to `seed_db --version`.

**Why a re-seed follows upstream rather than a pin** (owner ruling, 2026-09-19): nanoka
keeps only the current cycle. `gi/6.7` is already a 404, and this repo commits 9 of the
~1,086 payloads a seed reads, so a pinned version is one nobody can re-seed from once
upstream drops it — and the failure arrives on the day prod needs re-seeding.

**One pin per run is still the rule.** That is what this script is for: resolving the
version *once*, visibly, and passing it on. `seed_db` would otherwise resolve its own, and
the failure N.2 and the first run of the re-seed job both hit was a version nobody could
name afterwards — not the following of upstream as such.
"""

from __future__ import annotations

import asyncio

from app.data.importers.nanoka_gi_importer import HttpNanokaTransport


async def _latest() -> str:
    transport = HttpNanokaTransport()
    try:
        return await transport.resolve_version()
    finally:
        await transport.close()


def main() -> int:
    """Print the resolved version, or fail loudly."""
    print(asyncio.run(_latest()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
