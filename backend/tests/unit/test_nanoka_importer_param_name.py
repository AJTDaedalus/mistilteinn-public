"""Unit tests for Task 2: ``_import_attacks`` persists nanoka's per-hit param label.

``attacks.param_name`` is the single datum that distinguishes a press-chain row from a
variant row — it is what turns Soldier 11's "7 rows" into "5 presses + `Enhanced Basic
Attack 5th-Hit` + its `Additional`" (``docs/DESIGN_sequential_variant.md`` §5.4).

The load-bearing property here is that **rows sharing a ``param_name`` is legal**: one
nanoka ``param`` entry expands to several Attack rows via
``_unique_sorted_param_variants``, so duplicate labels are a *signal* for the §5.5 lint,
never a constraint violation and never a reason to deduplicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from app.data.importers.nanoka_importer import NanokaImporter

if TYPE_CHECKING:
    from app.models.agent import Attack


def _make_importer() -> tuple[NanokaImporter, MagicMock]:
    session = MagicMock()
    session.add = MagicMock()
    importer = NanokaImporter.__new__(NanokaImporter)
    importer.session = session
    return importer, session


def _make_agent(agent_id: str = "agent-001") -> MagicMock:
    agent = MagicMock()
    agent.id = agent_id
    agent.element = "physical"
    return agent


def _dmg_param(name: str, variants: dict[str, dict]) -> dict:
    """One nanoka ``param`` entry on the DMG side, with N skill_id variants."""
    return {"name": name, "param": variants}


def _added_attacks(session: MagicMock) -> list[Attack]:
    return [c.args[0] for c in session.add.call_args_list]


class TestParamNamePersisted:
    @pytest.mark.asyncio
    async def test_param_name_carried_onto_each_row(self) -> None:
        """The label reaches the Attack row; hit_index still sequences across params."""
        importer, session = _make_importer()
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Fire Suppression",
                            "param": [
                                _dmg_param(
                                    "Basic Attack 1st-Hit DMG Multiplier",
                                    {"1001": {"damage_percentage": 100}},
                                ),
                                _dmg_param(
                                    "Enhanced Basic Attack 5th-Hit DMG Multiplier",
                                    {"1005": {"damage_percentage": 500}},
                                ),
                            ],
                        }
                    ]
                }
            }
        }
        await importer._import_attacks(_make_agent(), data)

        rows = _added_attacks(session)
        assert [r.param_name for r in rows] == [
            "Basic Attack 1st-Hit DMG Multiplier",
            "Enhanced Basic Attack 5th-Hit DMG Multiplier",
        ]
        assert [r.hit_index for r in rows] == [0, 1]

    @pytest.mark.asyncio
    async def test_one_param_expanding_to_several_rows_shares_the_label(self) -> None:
        """DESIGN §5.4: duplicate ``param_name`` within a move is legal, not deduped.

        A single param carrying three distinct (damage%, growth) pairs expands to three
        Attack rows, all labelled with the *same* outer param name.
        """
        importer, session = _make_importer()
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Starshine Waltz",
                            "param": [
                                _dmg_param(
                                    "Charged Attack DMG Multiplier",
                                    {
                                        "2003": {"damage_percentage": 300},
                                        "2001": {"damage_percentage": 100},
                                        "2002": {"damage_percentage": 200},
                                    },
                                )
                            ],
                        }
                    ]
                }
            }
        }
        await importer._import_attacks(_make_agent(), data)

        rows = _added_attacks(session)
        assert len(rows) == 3, "one param with three distinct multipliers → three rows"
        assert {r.param_name for r in rows} == {"Charged Attack DMG Multiplier"}
        # Ascending by multiplier, per _unique_sorted_param_variants.
        assert [r.damage_base for r in rows] == [100, 200, 300]
        assert [r.hit_index for r in rows] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_truncated_at_200(self) -> None:
        importer, session = _make_importer()
        long_name = "X" * 250 + " DMG"
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Long",
                            "param": [_dmg_param(long_name, {"3001": {"damage_percentage": 10}})],
                        }
                    ]
                }
            }
        }
        await importer._import_attacks(_make_agent(), data)

        row = _added_attacks(session)[0]
        assert row.param_name == long_name[:200]
        assert len(row.param_name) == 200

    @pytest.mark.asyncio
    async def test_daze_params_still_skipped(self) -> None:
        """Persisting the label must not change which params produce rows."""
        importer, session = _make_importer()
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Mixed",
                            "param": [
                                _dmg_param(
                                    "Basic Attack 1st-Hit DMG Multiplier",
                                    {"4001": {"damage_percentage": 100}},
                                ),
                                _dmg_param(
                                    "Basic Attack 1st-Hit Daze Multiplier",
                                    {"4001": {"stun_ratio": 50}},
                                ),
                            ],
                        }
                    ]
                }
            }
        }
        await importer._import_attacks(_make_agent(), data)

        rows = _added_attacks(session)
        assert len(rows) == 1
        assert rows[0].param_name == "Basic Attack 1st-Hit DMG Multiplier"
