"""Service layer — business logic.

Per CLAUDE.md's layering (routes -> services -> repositories), this package sits
between `app/api/v1/` (thin route handlers) and `app/repositories/` (data access):
it owns all domain logic and never imports SQLAlchemy directly. Routes call into
services and get back Pydantic schemas / dataclasses, not ORM models.

**Port state.** The ZZZ service layer — 28 modules covering anomaly simulation,
stun, disc optimization/ranking/scoring, lumiflux, resource banks, and the combo
model — was deleted in B.2 (`refactor: delete ZZZ services`). What survives is
game-agnostic infrastructure:

    password.py    bcrypt hashing

`job_runner.py` was here too, and C.6 deleted it with the endpoints it served: searching
moved to the browser (DESIGN §3.5), so there is no long-running server work left to queue,
cancel or sweep after a restart.

`_ported/` holds read-only porting source and is not importable; see its README.

**What C.6 kept, and why.** `artifact_optimizer` and `artifact_prefilter` have no route and
are not dead: `scripts/kernel/generate_search_cases.py` runs `optimize()` to produce the 40
fixtures the browser kernel's search gate is checked against, and `tests/perf` measures it to
pin `SECONDS_PER_COMBINATION`. They ship as the oracle the client is verified against, the
same role gcsim already has. `build_combination_log` and its helpers stay for a second
reason: `build_explanation` and `weapon_comparison` read a build's damage through them, and
that must remain the single definition of what five artifacts are worth.
"""
