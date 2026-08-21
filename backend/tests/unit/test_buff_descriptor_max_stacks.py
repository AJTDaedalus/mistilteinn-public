"""Task 5 (kit-validation hotfix): BuffDescriptor must expose max_stacks.

The frontend ×N chip (buff-toggles.ts) needs the modifier's stack cap to
render "+6.00% ×3" for stackable buffs like Astra Yao's M1. Without this
field the API silently drops max_stacks and the chip can never appear.
"""

from unittest.mock import patch

from app.api.v1.builds import _agent_buff_groups
from app.models.agent import Agent
from app.models.enums import Element, Rarity, Specialty
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget


def _agent() -> Agent:
    return Agent(
        hakushin_id=1311,
        name="Astra Yao",
        element=Element.ETHER,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
    )


def test_stackable_modifier_reports_max_stacks() -> None:
    stackable = Modifier(
        stat="res_reduction",
        value=600,
        source=ModifierSource.MINDSCAPE,
        source_label="M1: RES Reduction stacks",
        target=ModifierTarget.TEAM,
        conditions=(Condition.ALWAYS,),
        max_stacks=3,
    )
    with patch(
        "app.api.v1.builds.load_agent_modifiers", return_value=[stackable]
    ):
        groups = _agent_buff_groups(
            "dps", _agent(), core_tier=5, mc_level=6, disabled=set()
        )

    buffs = [b for g in groups for b in g.buffs]
    assert len(buffs) == 1
    assert buffs[0].max_stacks == 3


def test_non_stackable_modifier_defaults_to_one() -> None:
    single = Modifier(
        stat="crit_rate",
        value=8000,
        source=ModifierSource.MINDSCAPE,
        source_label="M6: CRIT Rate",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
    )
    with patch(
        "app.api.v1.builds.load_agent_modifiers", return_value=[single]
    ):
        groups = _agent_buff_groups(
            "dps", _agent(), core_tier=5, mc_level=6, disabled=set()
        )

    buffs = [b for g in groups for b in g.buffs]
    assert len(buffs) == 1
    assert buffs[0].max_stacks == 1
