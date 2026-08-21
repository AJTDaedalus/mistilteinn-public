"""fix_scanner_main_stat_progression — F-29, migrate existing disc rows

Scanner/eZOD imports computed ``main_stat_value`` as
``int(max_main * max(0.1, level / max_level))``, missing the game's 25%
floor. The correct curve is ``int(max_main * (0.25 + 0.75 * level /
max_level))``. Recompute in place for every row whose stored value matches
the old (buggy) formula's output for its rarity/slot/stat/level — rows that
don't match (e.g. manually entered via the API) are left untouched, since
there's no import-source column to key off directly.

Revision ID: a7b8c9d0e1f2
Revises: f0a1b2c3d4e5
Create Date: 2026-07-05
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import column, table

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors scanner_importer._MAIN_STAT_MAX_S / _MAX_LEVEL. Duplicated here
# (rather than imported) because migrations must stay stable even if the
# application table changes shape later.
_MAX_LEVEL: dict[str, int] = {"S": 15, "A": 12, "B": 9}

_MAIN_STAT_MAX_S: dict[tuple[int, str], int] = {
    (1, "hp"): 2200,
    (2, "atk"): 316,
    (3, "def"): 184,
    (4, "hp_pct"): 3000,
    (4, "atk_pct"): 3000,
    (4, "def_pct"): 4800,
    (4, "crit_rate"): 2400,
    (4, "crit_dmg"): 4800,
    (4, "anomaly_proficiency"): 92,
    (5, "hp_pct"): 3000,
    (5, "atk_pct"): 3000,
    (5, "def_pct"): 4800,
    (5, "pen_ratio"): 2400,
    (5, "physical_dmg"): 3000,
    (5, "fire_dmg"): 3000,
    (5, "ice_dmg"): 3000,
    (5, "electric_dmg"): 3000,
    (5, "ether_dmg"): 3000,
    (6, "hp_pct"): 3000,
    (6, "atk_pct"): 3000,
    (6, "def_pct"): 4800,
    (6, "anomaly_mastery"): 92,
    (6, "impact_pct"): 1800,
    (6, "energy_regen"): 6000,
}

_RARITY_SCALE: dict[str, float] = {"S": 1.0, "A": 0.80, "B": 0.50}

discs_table = table(
    "discs",
    column("id", sa.String),
    column("rarity", sa.String),
    column("slot", sa.Integer),
    column("main_stat_type", sa.String),
    column("level", sa.Integer),
    column("main_stat_value", sa.Integer),
)


def _max_main(rarity: str, slot: int, stat: str) -> int | None:
    base = _MAIN_STAT_MAX_S.get((slot, stat))
    if base is None:
        return None
    return int(base * _RARITY_SCALE[rarity])


def _migrate(*, old_to_new: bool) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            discs_table.c.id,
            discs_table.c.rarity,
            discs_table.c.slot,
            discs_table.c.main_stat_type,
            discs_table.c.level,
            discs_table.c.main_stat_value,
        )
    ).fetchall()

    for row in rows:
        max_level = _MAX_LEVEL.get(row.rarity)
        if max_level is None or max_level == 0:
            continue
        max_main = _max_main(row.rarity, row.slot, row.main_stat_type)
        if max_main is None:
            continue
        old_value = int(max_main * max(0.1, row.level / max_level))
        new_value = int(max_main * (0.25 + 0.75 * row.level / max_level))
        if old_to_new:
            source_value, target_value = old_value, new_value
        else:
            source_value, target_value = new_value, old_value
        if row.main_stat_value == source_value and source_value != target_value:
            bind.execute(
                discs_table.update()
                .where(discs_table.c.id == row.id)
                .values(main_stat_value=target_value)
            )


def upgrade() -> None:
    _migrate(old_to_new=True)


def downgrade() -> None:
    _migrate(old_to_new=False)
