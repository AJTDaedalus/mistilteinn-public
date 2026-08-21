"""build v2 columns: support build refs and w_engine_refinement

Revision ID: a1b2c3d4e5f6
Revises: 5991595532c1
Create Date: 2026-05-02

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '75017f857abe'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "builds",
        sa.Column("support1_build_id", sa.String(), nullable=True),
    )
    op.add_column(
        "builds",
        sa.Column("support2_build_id", sa.String(), nullable=True),
    )
    op.add_column(
        "builds",
        sa.Column(
            "w_engine_refinement",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    # Create FK constraints after the columns exist.
    op.create_foreign_key(
        "fk_builds_support1_build_id",
        "builds", "builds",
        ["support1_build_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_builds_support2_build_id",
        "builds", "builds",
        ["support2_build_id"], ["id"],
        ondelete="SET NULL",
    )

    # Data migration: for each build with support_agent_id set, create a
    # dedicated stub Build for that agent (one per source build row, not one
    # per unique agent) and wire the new support_build_id column to it.
    # Uses a PL/pgSQL block to guarantee a 1-to-1 mapping even when multiple
    # builds share the same support agent.
    op.execute("""
        DO $$
        DECLARE
            rec RECORD;
            stub_id TEXT;
        BEGIN
            -- support1
            FOR rec IN
                SELECT b.id AS build_id, b.support1_agent_id, a.name AS agent_name
                FROM builds b
                JOIN agents a ON a.id = b.support1_agent_id
                WHERE b.support1_agent_id IS NOT NULL
                  AND b.support1_build_id IS NULL
            LOOP
                stub_id := gen_random_uuid()::TEXT;
                INSERT INTO builds (
                    id, name, agent_id,
                    w_engine_id, w_engine_level, mindscape_level,
                    agent_level, skill_levels, core_skill_level,
                    support1_agent_id, support2_agent_id,
                    notes, disabled_buffs,
                    w_engine_refinement,
                    created_at, updated_at
                ) VALUES (
                    stub_id, rec.agent_name || ' (auto)', rec.support1_agent_id,
                    NULL, 60, 0,
                    60, '12,12,12,12,12', 5,
                    NULL, NULL,
                    '', '[]'::jsonb,
                    1,
                    now(), now()
                );
                UPDATE builds SET support1_build_id = stub_id WHERE id = rec.build_id;
            END LOOP;

            -- support2
            FOR rec IN
                SELECT b.id AS build_id, b.support2_agent_id, a.name AS agent_name
                FROM builds b
                JOIN agents a ON a.id = b.support2_agent_id
                WHERE b.support2_agent_id IS NOT NULL
                  AND b.support2_build_id IS NULL
            LOOP
                stub_id := gen_random_uuid()::TEXT;
                INSERT INTO builds (
                    id, name, agent_id,
                    w_engine_id, w_engine_level, mindscape_level,
                    agent_level, skill_levels, core_skill_level,
                    support1_agent_id, support2_agent_id,
                    notes, disabled_buffs,
                    w_engine_refinement,
                    created_at, updated_at
                ) VALUES (
                    stub_id, rec.agent_name || ' (auto)', rec.support2_agent_id,
                    NULL, 60, 0,
                    60, '12,12,12,12,12', 5,
                    NULL, NULL,
                    '', '[]'::jsonb,
                    1,
                    now(), now()
                );
                UPDATE builds SET support2_build_id = stub_id WHERE id = rec.build_id;
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    op.drop_constraint("fk_builds_support1_build_id", "builds", type_="foreignkey")
    op.drop_constraint("fk_builds_support2_build_id", "builds", type_="foreignkey")
    op.drop_column("builds", "w_engine_refinement")
    op.drop_column("builds", "support2_build_id")
    op.drop_column("builds", "support1_build_id")
