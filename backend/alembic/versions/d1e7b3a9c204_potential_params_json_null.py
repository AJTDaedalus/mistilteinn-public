"""Normalise JSONB 'null' to SQL NULL in agents.potential_params (#90 Track 2)

`agents.potential_params` was declared as a bare `JSONB`, so SQLAlchemy stored Python
`None` as the JSON scalar `'null'` rather than SQL NULL. "This agent has no ramps" then
became a value that `IS NOT NULL` matches and `jsonb_array_length` errors on.

It only affects rows INSERTED with None — assigning None to a column that is already NULL
emits no UPDATE — so it was invisible until a re-seed inserted new agents. Prod hit it
first, with two unreleased agents; the local DB never did, because those agents predated
the column there.

The model now uses `JSONB(none_as_null=True)`, which fixes new writes. This normalises
what is already stored, so an existing deployment self-heals on deploy rather than
carrying a value that reads as "has ramps" to every `IS NOT NULL` query.

Revision ID: d1e7b3a9c204
Revises: c9f051a2b8e4
Create Date: 2026-08-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1e7b3a9c204"
down_revision: str | None = "c9f051a2b8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE agents SET potential_params = NULL WHERE potential_params = 'null'::jsonb"
    )


def downgrade() -> None:
    # Deliberately empty. The previous state — JSON 'null' standing in for SQL NULL — is
    # a defect, not a schema variant worth restoring, and which rows held it depended on
    # insert order rather than on anything meaningful.
    pass
