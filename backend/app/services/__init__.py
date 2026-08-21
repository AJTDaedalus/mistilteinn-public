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
    job_runner.py  bounded threadpool + cooperative cancellation + job lifecycle

`_ported/` holds read-only porting source and is not importable; see its README.
The Genshin services arrive in Chunks F (stats, damage) and G (artifact optimizer).
"""
