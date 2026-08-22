"""The crossval database, and the require-DB gate.

**This file exists because a skipped check is not a pass.** fairy's crossval suite was
green-by-absence on CI for months: the database it needed was not there, every level
skipped, the summary said green, and it shipped a stale golden fixture on the strength of
it. That is the most expensive bug in this project's lineage, and `docs/CROSSVAL_gcsim.md`
promised this gate would exist from the harness's first commit rather than be retrofitted.

## Where the data comes from

The schema is built and then seeded **from the committed nanoka fixtures, through the real
importer** — not from the live source, and not by hand-writing rows.

* Not live: CI's backend lane is hermetic by design, and a crossval that needed nanoka to
  be up would fail for reasons that have nothing to do with the damage chain.
* Not hand-written: then the harness would validate the damage chain against rows it made
  up, and an importer regression would sail through. Going through `NanokaGIImporter` means
  a mapping bug fails crossval, which is most of the point.

## The gate

Without a reachable database these tests **skip** — and with `CROSSVAL_REQUIRE_DB=1` they
**fail** instead. CI sets that variable. A developer without Postgres gets a skip and a
message; CI gets a failure, which is the only outcome that cannot be mistaken for a pass.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.base import Base
from tests.conftest import TEST_DATABASE_URL
from tests.unit.nanoka_transport import FIXTURE_DIR, FixtureTransport

#: Set this in CI. When set, an unreachable database is a **failure**, never a skip.
REQUIRE_DB_ENV = "CROSSVAL_REQUIRE_DB"

#: The entities the committed cases need, as `(entity, index key)` pairs. Kept explicit so
#: that adding a case which needs a new character also has to commit its payload — the
#: fixture and the seed cannot drift.
#:
#: A **set of pairs**, not `{entity: key}`: the mapping form could hold only one id per
#: entity type, so adding a second character would have silently dropped one of them at the
#: dict-key collision. The second crossval case needs exactly that, so the shape was wrong
#: one case before it would have mattered.
SEEDED: set[tuple[str, str]] = {("character", "10000002"), ("weapon", "11101")}


def _required() -> bool:
    return os.environ.get(REQUIRE_DB_ENV, "") not in ("", "0", "false", "False")


def _unavailable(reason: str) -> None:
    """Fail if a database was required, skip otherwise — never pass quietly."""
    message = (
        f"crossval needs a reachable database: {reason}. Start one (see CLAUDE.md "
        f"§Database) or set {REQUIRE_DB_ENV}=0 to skip."
    )
    if _required():
        pytest.fail(message)
    pytest.skip(message)


def _transport() -> FixtureTransport:
    """Serve exactly the committed payloads the cases need."""
    details = {}
    indexes: dict[str, dict] = {}
    for entity, key in sorted(SEEDED):
        path = Path(FIXTURE_DIR) / "detail" / f"{entity}_{key}.json"
        details[entity, key] = json.loads(path.read_text(encoding="utf-8"))
        indexes.setdefault(entity, {})[key] = {}
    return FixtureTransport(indexes=indexes, details=details)


@pytest.fixture
async def crossval_session():
    """A session over a schema seeded from the committed fixtures by the real importer."""
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:  # deliberately broad — see below
        # **Deliberately broad.** The question this gate asks is "could the check run?", and
        # any failure to reach the database answers it. A narrower catch was wrong in a way
        # worth recording: `(OSError, SQLAlchemyError)` missed
        # `asyncpg.InvalidCatalogNameError`, which escapes SQLAlchemy's wrapping when the
        # failure happens while establishing the connection rather than while executing.
        # The result was a pytest *error* where a skip was intended — which in CI reads as a
        # failure (harmless) and locally reads as a broken test (not harmless: that is how a
        # gate gets disabled).
        await engine.dispose()
        _unavailable(f"cannot reach it ({type(exc).__name__}: {exc})")

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            importer = NanokaGIImporter(session, transport=_transport())
            await importer.import_characters()
            await importer.import_weapons()
            _check_import(importer)
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        # The engine is function-scoped, so a run that failed part way used to leave one
        # live connection pool per failing test.
        await engine.dispose()


def _check_import(importer: NanokaGIImporter) -> None:
    """Fail here if the importer could not map what crossval needs.

    `_run_pass` records a per-item mapping failure in `EntityResult.failed` and carries on,
    which is right for a 1,000-entity seed and wrong here: without this, a field-mapping
    regression on Ayaka would show up much later as "no Ayaka in the database, re-run
    seed_db" — remediation advice for a script this harness does not use, pointing the
    reader away from the importer bug the harness exists to catch.
    """
    for result in importer.results:
        if result.failed or result.imported != len(
            [pair for pair in SEEDED if pair[0] == result.entity],
        ):
            pytest.fail(
                f"crossval could not seed {result.entity}: {result}. This is an importer "
                f"mapping failure against a committed payload, not a database problem.",
            )
