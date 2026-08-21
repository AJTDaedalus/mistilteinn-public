"""Seed the database with Genshin game data.

**STUB — not implemented yet.** B.9 deleted fairy's ZZZ implementation, which orchestrated
the hakushin/nanoka/dimbreath ZZZ importers against tables that no longer exist.

D.7 rewrites this to orchestrate four passes over the nanoka GI source — character, weapon,
artifact, monster — and to write a **seed-provenance row** recording the version pinned from
`manifest.json -> gi.latest` plus the run timestamp, so "which patch is this database" is a
query rather than a guess. Re-running it must produce an identical database (keep fairy's
stale-prune pattern).

Recover the transport and orchestration shape from
/root/fairy/backend/scripts/seed_db.py and
/root/fairy/backend/app/data/importers/nanoka_importer.py.

Usage, once implemented:
    cd backend && python -m scripts.seed_db
"""

from __future__ import annotations

import sys

_MESSAGE = """\
scripts/seed_db.py is a STUB. There is no Genshin importer yet (Chunk D).

This exits non-zero on purpose. A seed script that runs and does nothing is
indistinguishable from a seed script that succeeded, and this repo's CLAUDE.md is
explicit that a check which could not run must block rather than pass.

Implement in D.7, after D.1 lands the importer transport layer and D.2 commits the
detail-payload samples the mappings are written against.
"""


def main() -> int:
    """Refuse to run and say why."""
    sys.stderr.write(_MESSAGE)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
