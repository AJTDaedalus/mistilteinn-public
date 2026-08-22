"""Drop optimization_jobs — C.6 removed the endpoints it tracked.

Revision ID: d5f1a7c3e920
Revises: c0318f0bbead

The table existed to track background `optimize` and `rank-artifacts` runs. Both endpoints
are gone (DESIGN §3.5: searching moved to the browser), so nothing writes it, nothing reads
it, and no code refers to the model.

**This drops rows.** They are job records for a feature that no longer exists — request
payloads, progress counters and result blobs for searches nobody can re-run — so there is
nothing here a user could act on. The downgrade recreates the table's *shape*, not its
contents: a job history cannot be reconstructed and pretending otherwise would be worse than
saying so.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "d5f1a7c3e920"
down_revision = "c0318f0bbead"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the table and its indexes."""
    op.drop_index("ix_optimization_jobs_job_type", table_name="optimization_jobs")
    op.drop_index("ix_optimization_jobs_created_at_desc", table_name="optimization_jobs")
    op.drop_index("ix_optimization_jobs_status", table_name="optimization_jobs")
    op.drop_table("optimization_jobs")


def downgrade() -> None:
    """Recreate the table's shape. **The rows do not come back** — see the module docstring."""
    op.create_table(
        "optimization_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("character_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("enemy_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("rotation_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("combinations_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("combinations_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_by_sets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_by_stats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("eta_seconds", sa.Float(), nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("top_damage", sa.Float(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "job_type", sa.String(32), nullable=False, server_default="optimize",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_optimization_jobs_status", "optimization_jobs", ["status"])
    op.create_index(
        "ix_optimization_jobs_created_at_desc", "optimization_jobs", ["created_at"],
    )
    op.create_index("ix_optimization_jobs_job_type", "optimization_jobs", ["job_type"])
    op.create_index("ix_optimization_jobs_owner_id", "optimization_jobs", ["owner_id"])
