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


async def test_the_character_key_downgrade_drops_the_rows_it_cannot_represent(
    scratch_database: str,
):
    """D.3's downgrade deletes data, so it needs testing against data.

    `characters.nanoka_id` widened to `String(24)` for the 28 Traveler keys like
    `10000005-2`, which have no integer form at all. The downgrade therefore deletes those
    rows rather than failing halfway through the cast — and the same for the
    condition-gated passives whose `unlock_ascension` is NULL. Every other migration test
    here runs against an *empty* database, where a conditional DELETE is a no-op and proves
    nothing.
    """
    await _run_alembic("upgrade", scratch_database, "head")
    engine = create_async_engine(scratch_database)
    async with engine.begin() as conn:
        for nanoka_id in ("10000002", "10000005-2"):
            await conn.execute(
                text(
                    "INSERT INTO characters (id, nanoka_id, name, weapon_type, rarity, "
                    "base_hp, base_atk, base_def, ascension_stats) VALUES "
                    "(:id, :nanoka_id, 'Test', 'WEAPON_SWORD_ONE_HAND', 'five_star', "
                    "0, 0, 0, '[]'::jsonb)",
                ),
                {"id": f"id-{nanoka_id}", "nanoka_id": nanoka_id},
            )
        await conn.execute(
            text(
                "INSERT INTO ascension_passives (id, character_id, nanoka_id, name, "
                "description, icon, unlock_ascension, unlock_condition_ids) VALUES "
                "('p1', 'id-10000002', 1, 'Gated', '', '', 1, '[]'::jsonb), "
                "('p2', 'id-10000002', 2, 'Conditional', '', '', NULL, "
                "'[603101]'::jsonb)",
            ),
        )

    await _run_alembic("downgrade", scratch_database, "852f0b1613ff")

    async with engine.connect() as conn:
        keys = sorted(
            row[0] for row in await conn.execute(text("SELECT nanoka_id FROM characters"))
        )
        passives = sorted(
            row[0] for row in await conn.execute(text("SELECT name FROM ascension_passives"))
        )
    await engine.dispose()

    # The Traveler key is gone; the ordinary one survived the cast as an integer.
    assert keys == [10000002]
    # The condition-gated passive is gone rather than being given a `0` it never had.
    assert passives == ["Gated"]
