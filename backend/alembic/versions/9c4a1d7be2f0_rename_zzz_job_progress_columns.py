"""Rename the ZZZ progress columns on optimization_jobs (G.10).

"Assignments" were ZZZ **set-assignment frames** — fairy's optimizer enumerated declared
set-count distributions over six disc slots and searched within each. The Genshin search has
no such structure: it is a plain Cartesian product over five slots, so the unit it counts is
a combination.

`pruned_sets` / `pruned_stats` become `rejected_by_sets` / `rejected_by_stats`, which is what
`artifact_optimizer.OptimizerResult` already calls them — the table was the only place still
using the other words.

C.9 renamed `agent_name` / `combo_name` in this same table and deferred these because nothing
wrote them yet. G.10 is what starts writing them, so this is the moment.

**No data migration.** The table is empty in every environment: `submit_optimizer_job` was
deleted in B.2 and its replacement lands with this change, so no row has ever been written.

Revision ID: 9c4a1d7be2f0
Revises: 55afb8679231
"""

from alembic import op

revision = "9c4a1d7be2f0"
down_revision = "55afb8679231"
branch_labels = None
depends_on = None

_RENAMES = (
    ("assignments_done", "combinations_done"),
    ("assignments_total", "combinations_total"),
    ("pruned_sets", "rejected_by_sets"),
    ("pruned_stats", "rejected_by_stats"),
)


def upgrade() -> None:
    """Rename each column in place."""
    for old, new in _RENAMES:
        op.alter_column("optimization_jobs", old, new_column_name=new)


def downgrade() -> None:
    """Put the ZZZ names back."""
    for old, new in _RENAMES:
        op.alter_column("optimization_jobs", new, new_column_name=old)
