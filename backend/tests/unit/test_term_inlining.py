"""Task 4 — inline `<Term:NNNNNNN>` placeholders at import time.

Before this fix, no code anywhere resolved `<Term:` (grep: zero hits across
`app/`), so every such placeholder in skill/core/mindscape text rendered
empty. This covers `_inline_term_placeholders` and `TERM_ID_MAP` in
`nanoka_importer.py`, plus the five call sites (agent skills, core skills,
mindscapes, W-Engine passives, disc-set 2pc/4pc text) that now run text
through it alongside `_strip_color_tags`.

The six known terms (docs/TASKS_remielle.md Task 4 acceptance) were verified
against the merged Dimbreath TextMap (pinned SHA 475dd0195645,
`app/data/dimbreath/cache/475dd0195645/TextMap__TextMap_EN*TemplateTb.json`)
by grepping for `Remielle_NounPrompts_0N` / `_0N_Title` keys — see the
`TERM_ID_MAP` docstring in `nanoka_importer.py` and `docs/LOG_remielle.md`
Task 4 for the full derivation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from app.data.importers.nanoka_importer import (
    TERM_ID_MAP,
    NanokaImporter,
    _inline_term_placeholders,
    _strip_color_tags,
)

if TYPE_CHECKING:
    import pytest

# The six terms confirmed via the merged TextMap's Remielle_NounPrompts_0N
# titles (docs/TASKS_remielle.md Task 4 acceptance list).
KNOWN_TERMS = {
    "1000023": "Anomaly Effect Strength",
    "1000031": "Refringe",
    "1000032": "Floating Radiance",
    "1000033": "Voidflare",
    "1000034": "Luminize",
    "1000035": "Phase Flow",
}


class TestKnownTermsRoundTrip:
    """Acceptance: the six known terms round-trip, both tag shapes."""

    def test_paired_empty_tag_resolves(self) -> None:
        for term_id, name in KNOWN_TERMS.items():
            assert _inline_term_placeholders(f"<Term:{term_id}></Term>") == name

    def test_solo_self_closing_tag_resolves(self) -> None:
        for term_id, name in KNOWN_TERMS.items():
            assert _inline_term_placeholders(f"<Term:{term_id}>") == name

    def test_term_id_map_has_exactly_the_six_known_terms(self) -> None:
        assert TERM_ID_MAP == KNOWN_TERMS

    def test_multiple_terms_in_one_string(self) -> None:
        text = (
            "Deals Attribute Anomaly DMG based on the <Term:1000023></Term> "
            "of all stored <Term:1000033></Term>."
        )

        result = _inline_term_placeholders(text)

        assert result == (
            "Deals Attribute Anomaly DMG based on the Anomaly Effect Strength "
            "of all stored Voidflare."
        )

    def test_real_remielle_noun_prompts_04_des_sample(self) -> None:
        """Verbatim sample from Remielle_NounPrompts_04_Des (merged TextMap,
        pinned SHA 475dd0195645) — Voidflare's own description references
        Refringe (1000031) and Anomaly Effect Strength (1000023)."""
        text = (
            "When a squad member triggers Remielle's <color=#FFA9DD>Lumiflux</color> "
            "<Term:1000031></Term> reaction, Remielle generates "
            "<color=#FFFFFF>Voidflare</color> based on the enhanced "
            "<Term:1000023></Term> of that Attribute Anomaly after it has been "
            "<color=#FFA9DD>Refringed</color>."
        )

        result = _strip_color_tags(_inline_term_placeholders(text))

        assert "<Term:" not in result
        assert "Refringe reaction" in result
        assert "enhanced Anomaly Effect Strength" in result

    def test_wrapped_visible_text_form_keeps_the_text(self) -> None:
        """Remielle_UniqueSkill_Desc_Simple wraps its own visible text:
        `<Term:1000031>Refringed</Term>` — content is kept verbatim, same
        treatment as `<color>`/`<IconMap>` tags, rather than replaced with
        the base term name (which would read grammatically wrong)."""
        text = (
            "she generates Voidflare based on the value after being "
            "<Term:1000031>Refringed</Term>."
        )

        result = _inline_term_placeholders(text)

        assert result == "she generates Voidflare based on the value after being Refringed."


class TestUnresolvableTermWarnsAndLeavesRaw:
    """Acceptance: an unresolvable term id warns and leaves the raw
    placeholder intact — never silently blanks it (the pre-fix bug)."""

    def test_unresolved_paired_empty_tag_left_raw(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = _inline_term_placeholders("effect: <Term:9999999></Term> triggers")

        assert result == "effect: <Term:9999999></Term> triggers"
        assert "unresolved <term:9999999>" in caplog.text.lower()

    def test_unresolved_solo_tag_left_raw(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = _inline_term_placeholders("effect: <Term:9999999> triggers")

        assert result == "effect: <Term:9999999> triggers"
        assert "unresolved <term:9999999>" in caplog.text.lower()

    def test_unresolved_id_warns_exactly_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """A single occurrence must not be double-matched (paired pass then
        solo pass) into two warnings for the same placeholder."""
        with caplog.at_level(logging.WARNING):
            _inline_term_placeholders("<Term:9999999></Term>")

        assert caplog.text.lower().count("unresolved <term:9999999>") == 1

    def test_mixed_known_and_unknown_terms(self, caplog: pytest.LogCaptureFixture) -> None:
        text = "<Term:1000031></Term> and <Term:8888888></Term> both appear"

        with caplog.at_level(logging.WARNING):
            result = _inline_term_placeholders(text)

        assert result == "Refringe and <Term:8888888></Term> both appear"
        assert "unresolved <term:8888888>" in caplog.text.lower()

    def test_no_terms_present_is_a_no_op_and_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _inline_term_placeholders("plain text, no placeholders here")

        assert result == "plain text, no placeholders here"
        assert caplog.text == ""

    def test_empty_string_is_a_no_op(self) -> None:
        assert _inline_term_placeholders("") == ""


class TestImporterCallSitesApplyTermInlining:
    """The five description-assembly call sites (agent skills, core skills,
    mindscapes, W-Engine passives, disc-set 2pc/4pc) run text through
    `_inline_term_placeholders` alongside `_strip_color_tags` — general win,
    not specific to Remielle."""

    def _importer(self) -> NanokaImporter:
        return NanokaImporter(session=MagicMock())

    def test_agent_skill_description_inlines_terms(self) -> None:
        importer = self._importer()
        agent = MagicMock(id=1)
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Test",
                            "desc": "Triggers the <Term:1000031></Term> reaction.",
                        }
                    ]
                }
            }
        }

        asyncio.run(importer._import_agent_skills(agent, data))

        added = importer.session.add.call_args[0][0]
        assert added.description == "Triggers the Refringe reaction."

    def test_core_skill_description_inlines_terms(self) -> None:
        importer = self._importer()
        agent = MagicMock(id=1)
        data = {
            "passive": {
                "level": {
                    "1": {
                        "level": 1,
                        "name": ["Test Passive"],
                        "desc": ["Grants <Term:1000034></Term> on hit."],
                    }
                }
            }
        }

        asyncio.run(importer._import_core_skills(agent, data))

        added = importer.session.add.call_args[0][0]
        assert added.description == "Grants Luminize on hit."

    def test_mindscape_description_inlines_terms(self) -> None:
        importer = self._importer()
        agent = MagicMock(id=1)
        data = {
            "talent": {
                "1": {
                    "level": 1,
                    "name": "Mindscape 1",
                    "desc": "Enters <Term:1000035></Term> state faster.",
                }
            }
        }

        asyncio.run(importer._import_mindscapes(agent, data))

        added = importer.session.add.call_args[0][0]
        assert added.description == "Enters Phase Flow state faster."

    def test_unresolvable_term_in_core_skill_desc_leaves_raw_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        importer = self._importer()
        agent = MagicMock(id=1)
        data = {
            "passive": {
                "level": {
                    "1": {
                        "level": 1,
                        "name": ["Test Passive"],
                        "desc": ["Grants <Term:7777777></Term> on hit."],
                    }
                }
            }
        }

        with caplog.at_level(logging.WARNING):
            asyncio.run(importer._import_core_skills(agent, data))

        added = importer.session.add.call_args[0][0]
        assert added.description == "Grants <Term:7777777></Term> on hit."
        assert "unresolved <term:7777777>" in caplog.text.lower()
