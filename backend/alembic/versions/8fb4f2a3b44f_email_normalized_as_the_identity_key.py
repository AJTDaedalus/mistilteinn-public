"""email_normalized as the identity key

`DESIGN_open_registration.md` §2 (D-OR6) and `TASKS_open_registration.md` 11.

Without this, `a.b@gmail.com`, `ab@gmail.com` and `ab+1@gmail.com` are three accounts on one
inbox, and every per-email rate limit is bypassed by adding a dot.

**The backfill has to run before the unique index exists**, and it has to be done in SQL that
matches `email_policy.normalize` exactly — the Python function cannot be called from here
against rows that are being rewritten in the same transaction. The two are kept honest by
`tests/integration/test_email_normalized_backfill.py`, which re-derives every row with the real
function and compares.

Scoped to Gmail deliberately: dot-insensitivity is a documented Gmail behaviour, not a
standard, and applying it to arbitrary domains would merge two genuinely distinct addresses
into one account — silently, and with no way back.

Revision ID: 8fb4f2a3b44f
Revises: 83f5d221d8f6
Create Date: 2026-09-04

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8fb4f2a3b44f"
down_revision: str | None = "83f5d221d8f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Lowercase everything; for gmail/googlemail only, drop dots in the local part and everything
#: from `+` onwards. Mirrors `app/services/email_policy.py::normalize`.
_BACKFILL = """
UPDATE users
SET email_normalized = CASE
    WHEN split_part(lower(email), '@', 2) IN ('gmail.com', 'googlemail.com')
        THEN replace(
                 split_part(split_part(lower(email), '@', 1), '+', 1), '.', ''
             ) || '@gmail.com'
    ELSE lower(email)
END
"""


def upgrade() -> None:
    # Nullable first, so existing rows are not rejected before they can be filled.
    op.add_column(
        "users",
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
    )
    op.execute(_BACKFILL)

    # **The unique index goes on last, and its failure is informative.** If two existing
    # addresses normalize to the same key, this raises rather than silently merging them —
    # which is the right outcome: a human has to decide which account survives.
    op.alter_column("users", "email_normalized", nullable=False)
    op.create_index(
        "ix_users_email_normalized", "users", ["email_normalized"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_normalized", table_name="users")
    op.drop_column("users", "email_normalized")
