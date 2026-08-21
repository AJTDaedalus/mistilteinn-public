"""reclassify_wengine_am_secondary_stat

W-Engine secondary stat "Anomaly Mastery" is AM% (12% = 1200 bp), not flat AM.
Reclassify existing rows from secondary_stat_type='anomaly_mastery' to
'anomaly_mastery_pct' to match the importer fix in RAND_PROPERTY_MAP.

Affected engines: Angel in the Shell, Neon Fantasies, Frostfall Sickle.

Idempotent: WHERE clause guards prevent double-application.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-30 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = 'd2e3f4a5b6c7'
down_revision: str | None = 'c1d2e3f4a5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE w_engines SET secondary_stat_type = 'anomaly_mastery_pct' "
        "WHERE secondary_stat_type = 'anomaly_mastery'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE w_engines SET secondary_stat_type = 'anomaly_mastery' "
        "WHERE secondary_stat_type = 'anomaly_mastery_pct'"
    )
