"""L5 must still reach the DB after L4 has run — a regression guard.

Separate module because it must NOT be an async test: `check_l4` and `check_l5` each call
`asyncio.run()` themselves, which is illegal from inside a running loop, and reproducing
the real CLI path is the entire point.

**The bug this guards.** L4's `asyncio.run()` closes its event loop with the shared
SQLAlchemy engine still holding pooled connections bound to it, so L5's query raised
"attached to a different loop" — which L5's own no-DB skip contract then reported as
"DB not reachable". The result: **L5 silently no-opped in every full-harness run**, i.e.
in the only way the harness is actually used, while printing green.

That is the `ex_energy_cost` failure shape wearing a lint's clothing — a check that looks
green because it never ran — and it is exactly what L5 exists to prevent. So it gets a
test, not a comment. The fix is `await engine.dispose()` before L5 queries, rebuilding the
pool in the current loop.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr

import pytest

from scripts.validate_kits import L4_STATUS, L5_STATUS, check_l4, check_l5


class TestL5RunsAfterL4:
    def test_l5_still_reaches_the_db_after_l4_has_run(self) -> None:
        # Sync on purpose: check_l4/check_l5 call asyncio.run() themselves, which cannot
        # be done from inside a running loop. Reproducing the real CLI path is the point.
        buf = io.StringIO()
        with redirect_stderr(buf):
            check_l4([])
            # This guard is about what L4 does to the event loop that L5 then inherits,
            # so it is only meaningful once L4 has actually TALKED to a database. Against
            # an unseeded one (a fresh CI Postgres, a colleague's box) L4 skips, L5 skips
            # for that reason rather than the regression's, and asserting would report a
            # missing seed as a returned bug. Same skip contract every other seeded-DB
            # test in this directory carries — this module was simply missing it, which
            # is why it was the one red test when the integration suite first ran in CI.
            if not L4_STATUS["db_reachable"]:
                pytest.skip("L4 could not reach a seeded DB — seeded DB required")
            check_l5([])
        assert L5_STATUS["db_reachable"] is True, (
            "L5 skipped after L4 ran — the event-loop/engine interaction is back: "
            + buf.getvalue()
        )
        if not L5_STATUS["param_name_populated"]:
            # Environment, not regression: `param_name` is populated by the nanoka
            # importer and not by its migration, so a migrated-but-not-re-seeded DB has
            # it all-NULL. That is the documented `ex_energy_cost` shape and it is what
            # L5's own guard is for — it is not this test's subject.
            pytest.skip("attacks.param_name is all-NULL — DB needs a full re-seed")
