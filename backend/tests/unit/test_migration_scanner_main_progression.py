"""Task B2 — F-29: unit tests for the data migration that recomputes
``discs.main_stat_value`` for rows produced by the buggy pre-fix formula.

The migration module lives under ``alembic/versions`` (not an installed
package), so it's loaded by file path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "a7b8c9d0e1f2_fix_scanner_main_stat_progression.py"
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location(
        "migration_a7b8c9d0e1f2", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestMaxMain:
    def test_s_rank_is_unscaled(self, migration):
        assert migration._max_main("S", 4, "anomaly_proficiency") == 92

    def test_a_rank_is_80_pct(self, migration):
        assert migration._max_main("A", 4, "anomaly_proficiency") == int(92 * 0.80)

    def test_b_rank_is_50_pct(self, migration):
        assert migration._max_main("B", 4, "anomaly_proficiency") == int(92 * 0.50)

    def test_unknown_slot_stat_returns_none(self, migration):
        assert migration._max_main("S", 4, "energy_regen") is None


class TestMigrateRowSelection:
    """Only rows whose stored value matches the OLD buggy formula move."""

    def _row(self, **kw):
        base = {
            "id": "disc-1",
            "rarity": "S",
            "slot": 4,
            "main_stat_type": "anomaly_proficiency",
            "level": 0,
            "main_stat_value": 9,  # old buggy value: int(92 * 0.1)
        }
        base.update(kw)
        return MagicMock(**base)

    def _run_upgrade(self, migration, rows):
        bind = MagicMock()
        bind.execute.return_value.fetchall.return_value = rows
        migration.op.get_bind = MagicMock(return_value=bind)
        migration._migrate(old_to_new=True)
        return bind

    def test_plus_0_buggy_row_is_updated_to_23(self, migration):
        bind = self._run_upgrade(migration, [self._row()])
        select_call = bind.execute.call_args_list[0]
        update_calls = [c for c in bind.execute.call_args_list if c is not select_call]
        assert len(update_calls) == 1
        stmt = update_calls[0].args[0]
        compiled = stmt.compile()
        assert compiled.params["main_stat_value"] == 23

    def test_maxed_row_is_left_alone(self, migration):
        row = self._row(level=15, main_stat_value=92)
        bind = self._run_upgrade(migration, [row])
        # Only the initial select executed; no UPDATE issued.
        assert bind.execute.call_count == 1

    def test_non_matching_row_is_left_alone(self, migration):
        """A row whose value doesn't match either formula (e.g. hand-entered) is untouched."""
        row = self._row(level=12, main_stat_value=74)
        bind = self._run_upgrade(migration, [row])
        assert bind.execute.call_count == 1
