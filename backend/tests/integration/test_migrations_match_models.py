"""The migrations must build the same schema the models declare.

**Why this exists.** `tests/conftest.py` builds the test schema with
`Base.metadata.create_all`, so *nothing else in this suite runs a migration*. Every other
test would pass with an empty `alembic/versions/` directory. That means the hand-written
parts of a migration — the parts autogenerate cannot produce — are unverified by CI, which
is precisely the green-by-absence shape `CLAUDE.md` tells this repo not to repeat.

C.7 had to hand-add two `CheckConstraint`s because alembic does not generate them, and
eighteen `server_default`s because it omitted those too. Delete those lines today and the
suite stays green while production loses its range checks. This test is what notices.

It runs `alembic upgrade head` against a scratch database and asserts
`compare_metadata(...)` is empty, then downgrades to base and asserts the schema is gone.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.models import Base
from tests.conftest import TEST_DATABASE_URL

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: A separate database, so the migration run cannot race the schema every other test uses.
_SCRATCH_DB = "mistilteinn_migration_check"


async def _run_alembic(action: str, url: str, revision: str) -> None:
    """Run an alembic command off the event loop.

    `alembic/env.py` drives an async engine with `asyncio.run(...)`. Called directly from an
    async test that is already inside a running loop, that raises
    `RuntimeError: asyncio.run() cannot be called from a running event loop` and leaves a
    `coroutine 'run_async_migrations' was never awaited` warning behind. A worker thread has
    no loop of its own, so `asyncio.run` there behaves exactly as it does on the CLI.
    """
    os.environ["DATABASE_URL"] = url
    config = _alembic_config(url)
    # Leave this process's logging alone — see the note in alembic/env.py.
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(getattr(command, action), config, revision)


def _alembic_config(sync_url: str) -> Config:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    return config


@pytest.fixture
async def scratch_database() -> str:
    """Create an empty database for this test and drop it afterwards."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}"'))
        await conn.execute(text(f'CREATE DATABASE "{_SCRATCH_DB}"'))
    await engine.dispose()

    yield TEST_DATABASE_URL.rsplit("/", 1)[0] + f"/{_SCRATCH_DB}"

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}"'))
    await engine.dispose()


async def test_upgrade_head_produces_exactly_the_model_schema(scratch_database: str):
    """`alembic upgrade head` on an empty database must leave no diff against the models."""
    await _run_alembic("upgrade", scratch_database, "head")

    engine = create_async_engine(scratch_database)
    async with engine.connect() as conn:
        diffs = await conn.run_sync(
            lambda sync_conn: compare_metadata(
                MigrationContext.configure(sync_conn, opts={"compare_type": True}),
                Base.metadata,
            ),
        )
    await engine.dispose()

    assert diffs == [], (
        "The migrations and the models disagree. Either the models changed without a "
        f"migration, or a migration is wrong. Diff: {diffs}"
    )


async def test_the_hand_written_check_constraints_really_exist_after_migrating(
    scratch_database: str,
):
    """The five constraints alembic's autogenerate does not emit.

    Two came from C.7 and three more from the PR #2 review, and every one of them is a
    hand-written line that autogenerate will never regenerate if someone deletes it.

    `test_constellation_level_is_range_checked` proves the *model* declares them. This
    proves the *migration* creates them — a distinction that matters because production is
    built by migration and the test suite is built by `create_all`.
    """
    await _run_alembic("upgrade", scratch_database, "head")

    engine = create_async_engine(scratch_database)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname = 'builds' AND c.contype = 'c' ORDER BY conname",
            ),
        )
        names = [r[0] for r in rows]
    await engine.dispose()

    assert names == [
        "ck_builds_ascension_phase_range",
        "ck_builds_character_level_range",
        "ck_builds_constellation_level_range",
        "ck_builds_refinement_range",
        "ck_builds_weapon_level_range",
    ]


async def test_downgrade_base_removes_everything_the_migrations_created(
    scratch_database: str,
):
    """A history that cannot be reversed is the defect B.10 found in fairy's."""
    await _run_alembic("upgrade", scratch_database, "head")
    await _run_alembic("downgrade", scratch_database, "base")

    engine = create_async_engine(scratch_database)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
        )
        tables = sorted(r[0] for r in rows)
    await engine.dispose()

    assert tables == ["alembic_version"], f"downgrade left tables behind: {tables}"
