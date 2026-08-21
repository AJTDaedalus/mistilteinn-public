"""add buff_presets (issue #64, DESIGN_buff_context.md §2.4)

Saved, reusable sets of user-authored stage buffs. Deadly Assault / Shiyu buffs rotate
with the patch cycle and get re-applied across many builds, so they need storage that is
neither a build column nor a request field.

``owner_id`` cascades rather than nulling out (unlike builds/teams/combos): every read
path for a preset is owner-scoped, so an ownerless row is one nobody could ever list,
apply or delete.

Revision ID: a7c31b9e5d40
Revises: d1e7b3a9c204
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a7c31b9e5d40"
down_revision = "d1e7b3a9c204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buff_presets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "buffs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_buff_presets_owner_id"), "buff_presets", ["owner_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_buff_presets_owner_id"), table_name="buff_presets")
    op.drop_table("buff_presets")
