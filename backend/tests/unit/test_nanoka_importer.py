"""Unit tests for nanoka importer skill-key classification and stat-key mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from app.data.importers.nanoka_importer import (
    RAND_PROPERTY_MAP,
    NanokaImporter,
    _skill_key_from_name,
)
from app.models.enums import PotentialTag

if TYPE_CHECKING:
    from app.models.agent import AgentSkill


class TestSkillKeyFromName:
    """_skill_key_from_name overrides the mapped key based on move name."""

    def test_ex_special_overrides_special(self) -> None:
        # Yanagi: "EX Special Attack: Gekka Ruten" must become EXSpecial
        assert _skill_key_from_name("Special", "EX Special Attack: Gekka Ruten") == "EXSpecial"

    def test_ex_special_generic(self) -> None:
        assert _skill_key_from_name("Special", "EX Special Attack: X") == "EXSpecial"

    def test_ultimate_overrides_chain(self) -> None:
        # Yanagi: "Ultimate: Raiei Tenge" must become Ultimate
        assert _skill_key_from_name("Chain", "Ultimate: Raiei Tenge") == "Ultimate"

    def test_ultimate_generic(self) -> None:
        assert _skill_key_from_name("Chain", "Ultimate: Y") == "Ultimate"

    def test_regular_special_unchanged(self) -> None:
        assert _skill_key_from_name("Special", "Special Attack: Some Move") == "Special"

    def test_chain_attack_unchanged(self) -> None:
        assert _skill_key_from_name("Chain", "Chain Attack: Some Move") == "Chain"

    def test_basic_unchanged(self) -> None:
        assert _skill_key_from_name("Basic", "Basic Attack: Sunderlight") == "Basic"

    def test_empty_name_returns_mapped(self) -> None:
        # No name → fall through to the mapped key unchanged
        assert _skill_key_from_name("Special", "") == "Special"

    def test_case_sensitive_no_false_positive(self) -> None:
        # Must not match lowercase "ex special"
        assert _skill_key_from_name("Special", "ex special attack: x") == "Special"


class TestImportAgentSkillsAllVariants:
    """_import_agent_skills must emit one row per unique description name, not just [0]."""

    def _make_importer(self) -> tuple[NanokaImporter, MagicMock]:
        session = MagicMock()
        session.add = MagicMock()
        importer = NanokaImporter.__new__(NanokaImporter)
        importer.session = session
        return importer, session

    def _make_agent(self, agent_id: str = "agent-001") -> MagicMock:
        agent = MagicMock()
        agent.id = agent_id
        return agent

    @pytest.mark.asyncio
    async def test_all_description_entries_imported(self) -> None:
        """Three description entries → three AgentSkill rows."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "special": {
                    "description": [
                        {"name": "Special Attack: Alpha", "desc": "desc alpha"},
                        {"name": "Special Attack: Beta", "desc": "desc beta"},
                        {"name": "Pulse", "desc": "desc pulse"},
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 3
        added: list[AgentSkill] = [c.args[0] for c in session.add.call_args_list]
        names = [s.name for s in added]
        assert "Special Attack: Alpha" in names
        assert "Special Attack: Beta" in names
        assert "Pulse" in names

    @pytest.mark.asyncio
    async def test_duplicate_name_collapsed(self) -> None:
        """Duplicate trimmed name still collapses to one row (neither entry
        carries a `potential` tag, so first-wins is unaffected by #85)."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {"name": "Basic Attack", "desc": "first desc"},
                        {"name": "Basic Attack", "desc": "second desc"},
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 1
        skill: AgentSkill = session.add.call_args.args[0]
        assert skill.name == "Basic Attack"
        assert "first desc" in skill.description

    @pytest.mark.asyncio
    async def test_base_potential_pair_becomes_two_tagged_rows(self) -> None:
        """A base (`potential: [0]`) entry and a Potential-unlocked entry of the
        same name are both imported, tagged.

        Under #85 this pair collapsed onto the Potential entry's text, because
        fairy modelled only the unlocked kit. Since #90 both states are stored and
        the build's rank selects between them — so a locked build reads the base
        text, which for several of these 25 moves omits the whole mechanic, and an
        unlocked build reads the Potential text. The #85 defect this replaces was
        keeping the *base* text for everyone (nanoka lists base first, so plain
        first-wins picked it)."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Dancing Blades",
                            "desc": "base text",
                            "potential": [0],
                        },
                        {
                            "name": "Basic Attack: Dancing Blades",
                            "desc": "potential text",
                            "potential": [1261100, 1261101, 1261102, 1261103, 1261104, 1261105],
                        },
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 2
        added: list[AgentSkill] = [c.args[0] for c in session.add.call_args_list]
        assert {s.name for s in added} == {"Basic Attack: Dancing Blades"}
        by_tag = {s.potential: s.description for s in added}
        assert by_tag[PotentialTag.BASE] == "base text"
        assert by_tag[PotentialTag.UNLOCKED] == "potential text"

    @pytest.mark.asyncio
    async def test_potential_only_new_move_imported(self) -> None:
        """A `potential: [ids]`-only entry introducing a name with no base
        twin is imported — the real case is Jane's EX Special Attack: Aerial
        Sweep - Onslaught, which does not exist in the base kit at all."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "special": {
                    "description": [
                        {
                            "name": "EX Special Attack: Aerial Sweep - Onslaught",
                            "desc": "onslaught text",
                            "potential": [1261100, 1261101, 1261102, 1261103, 1261104, 1261105],
                        },
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 1
        skill: AgentSkill = session.add.call_args.args[0]
        assert skill.name == "EX Special Attack: Aerial Sweep - Onslaught"
        assert skill.description == "onslaught text"

    @pytest.mark.asyncio
    async def test_empty_name_entry_skipped(self) -> None:
        """Entry with empty name is skipped entirely."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "dodge": {
                    "description": [
                        {"name": "", "desc": "some desc"},
                        {"name": "Dodge: Evasion", "desc": "good desc"},
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 1
        skill: AgentSkill = session.add.call_args.args[0]
        assert skill.name == "Dodge: Evasion"

    @pytest.mark.asyncio
    async def test_ex_special_reclassified_per_entry(self) -> None:
        """Each entry in 'special' is independently reclassified: EX → EXSpecial."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "special": {
                    "description": [
                        {"name": "Special Attack: Normal", "desc": ""},
                        {"name": "EX Special Attack: Powered", "desc": ""},
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 2
        added: list[AgentSkill] = [c.args[0] for c in session.add.call_args_list]
        key_map = {s.name: s.skill_key for s in added}
        assert key_map["Special Attack: Normal"] == "Special"
        assert key_map["EX Special Attack: Powered"] == "EXSpecial"

    @pytest.mark.asyncio
    async def test_empty_descriptions_list_produces_no_rows(self) -> None:
        """skill key with no descriptions → no rows added."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {"skill": {"chain": {"description": []}}}
        await importer._import_agent_skills(agent, data)
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_skill_key_ignored(self) -> None:
        """skill_key not in SKILL_TYPE_MAP is skipped."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {"skill": {"unknown_key": {"description": [{"name": "X", "desc": ""}]}}}
        await importer._import_agent_skills(agent, data)
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_name_truncated_at_200(self) -> None:
        """Names longer than 200 chars are truncated."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        long_name = "A" * 300
        data = {"skill": {"basic": {"description": [{"name": long_name, "desc": ""}]}}}
        await importer._import_agent_skills(agent, data)
        skill: AgentSkill = session.add.call_args.args[0]
        assert len(skill.name) == 200

    @pytest.mark.asyncio
    async def test_desc_not_truncated(self) -> None:
        """Descriptions are stored in full (column is TEXT, not String(2000)).

        Long agent kits (Velina, Promeia) exceed 2000 chars and previously lost
        the tail — including Abloom MV clauses. See DECISIONS.md D-C8.6.
        """
        importer, session = self._make_importer()
        agent = self._make_agent()
        long_desc = "B" * 3000
        data = {"skill": {"basic": {"description": [{"name": "Basic Attack", "desc": long_desc}]}}}
        await importer._import_agent_skills(agent, data)
        skill: AgentSkill = session.add.call_args.args[0]
        assert len(skill.description) == 3000

    @pytest.mark.asyncio
    async def test_whitespace_only_name_skipped(self) -> None:
        """Entry with whitespace-only name is treated as empty and skipped."""
        importer, session = self._make_importer()
        agent = self._make_agent()
        data = {
            "skill": {
                "assist": {
                    "description": [
                        {"name": "   ", "desc": "some desc"},
                        {"name": "Assist Follow-Up", "desc": "real desc"},
                    ]
                }
            }
        }
        await importer._import_agent_skills(agent, data)
        assert session.add.call_count == 1
        skill: AgentSkill = session.add.call_args.args[0]
        assert skill.name == "Assist Follow-Up"


class TestRandPropertyMap:
    """Task 1.6b — W-Engine secondary 'Anomaly Mastery' is AM%, not flat."""

    def test_anomaly_mastery_maps_to_pct_key(self) -> None:
        # Angel in the Shell / Neon Fantasies / Frostfall Sickle secondary stat
        # is AM% (value 1200 bp = 12%), not flat AM. Must route to am_pct.
        assert RAND_PROPERTY_MAP["Anomaly Mastery"] == "anomaly_mastery_pct"
