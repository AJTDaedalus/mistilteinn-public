"""add_attacks_param_name — persist nanoka's per-hit ``param`` label

Additive and nullable, so there is no data migration and no downtime. The column is
populated by the nanoka importer, **not** by this migration: a DB that runs
``alembic upgrade head`` without a full ``python -m scripts.seed_db`` legitimately has
``param_name`` NULL on every row, and every consumer must treat all-NULL as "cannot
check" rather than "clean" (DESIGN_sequential_variant.md §5.4, the ``ex_energy_cost``
lesson).

Rows may legitimately share a ``param_name`` — one nanoka ``param`` entry can expand to
several attack rows — so this is deliberately not unique.

Revision ID: 6b497e001038
Revises: b1a2c3d4e5f6
Create Date: 2026-07-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "6b497e001038"
down_revision: str | None = "b1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attacks", sa.Column("param_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("attacks", "param_name")
