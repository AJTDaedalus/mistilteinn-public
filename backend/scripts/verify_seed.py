"""Post-seed sanity checks.

**STUB — not implemented yet.** B.9 deleted fairy's ZZZ implementation.

D.8 rewrites this as per-table row counts asserted against the nanoka index lengths, plus a
short list of hand-checked anchor values that fail loudly on drift. Two rules carry over from
fairy and are the reason this script exists at all:

1. Keep the tripwire list **short**, and comment *why* each entry is trustworthy. A long list
   of unverified expectations rots and then gets deleted instead of fixed.
2. D.8's acceptance requires proving the gate can fail — deliberately corrupt an anchor and
   watch it go red. A gate never observed failing is not a gate.

fairy's version existed because a field-mapping regression (Anomaly Mastery and Proficiency
stored swapped on every agent) reached production silently: `seed_db.py` had no post-seed
assertions at all until it was written. That is the failure this replaces, not a nicety.

Usage, once implemented:
    cd backend && python -m scripts.verify_seed
"""

from __future__ import annotations

import sys

_MESSAGE = """\
scripts/verify_seed.py is a STUB. There is nothing seeded to verify yet (Chunk D).

This exits non-zero on purpose: a verifier that runs and asserts nothing reports a
pass it did not earn, which is exactly the green-by-absence failure this repo's
CLAUDE.md calls out.

Implement in D.8.
"""


def main() -> int:
    """Refuse to run and say why."""
    sys.stderr.write(_MESSAGE)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
