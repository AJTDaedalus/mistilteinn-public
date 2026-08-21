"""Task 3 — the `agent_resource_costs` child table.

`Agent.ex_energy_cost` is one scalar for one mode, and several agents have more than one
EX mode plus per-second drains (Burnice: 40 activation / 12.5 per sec / 5 blast, and a
second mode again). This table is where those live; the move spec carries only the binding
(`entry_cost_key` etc.) so the values stay in the DB per the source-of-truth rule.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.models.agent import Agent, AgentResourceCost


def test_table_name_and_columns() -> None:
    cols = {c.name for c in AgentResourceCost.__table__.columns}
    assert AgentResourceCost.__tablename__ == "agent_resource_costs"
    assert {"id", "agent_id", "cost_key", "value", "per_sec", "resource"} <= cols


def test_cost_key_is_unique_per_agent() -> None:
    """The key is how a move spec binds to a row; two rows for one key make the bind ambiguous."""
    uniques = [
        tuple(sorted(c.columns.keys()))
        for c in AgentResourceCost.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    indexes = [
        tuple(sorted(i.columns.keys())) for i in AgentResourceCost.__table__.indexes if i.unique
    ]
    assert ("agent_id", "cost_key") in uniques + indexes


def test_value_is_float_not_int() -> None:
    """12.5 energy/sec is real upstream data; an Integer column silently floors it."""
    assert AgentResourceCost.__table__.c.value.type.python_type is float


def test_per_sec_defaults_to_false_and_is_not_nullable() -> None:
    """A NULL per_sec would read as 'not a drain', which is a wrong answer wearing a default."""
    col = AgentResourceCost.__table__.c.per_sec
    assert col.nullable is False


def test_resource_is_not_nullable() -> None:
    """Windbloom/Heat/Rp share this table with Energy; an unnamed bank cannot be credited."""
    assert AgentResourceCost.__table__.c.resource.nullable is False


def test_agent_relationship_cascades() -> None:
    rel = inspect(Agent).relationships["resource_costs"]
    assert rel.mapper.class_ is AgentResourceCost
    assert "delete-orphan" in rel.cascade


def test_fk_is_ondelete_cascade() -> None:
    fk = next(iter(AgentResourceCost.__table__.c.agent_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


@pytest.mark.parametrize("field", ["cost_key", "resource"])
def test_string_fields_are_bounded(field: str) -> None:
    """Unbounded text invites the 2000-char truncation class of bug this repo already hit."""
    assert AgentResourceCost.__table__.c[field].type.length
