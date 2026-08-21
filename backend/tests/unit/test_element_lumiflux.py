"""Task 2 — `Element.LUMIFLUX` consumer audit + loud importer fallback.

Turns DESIGN_remielle.md §4.2's audit table into assertions: a synthetic
`lumiflux` build traverses every named consumer without raising and without
picking up a phantom `lumiflux_dmg` bucket. Per §4.2, Lumiflux deliberately
does NOT join `app.formula.zzz.tags.ELEMENTS` or `StatType` — see
`test_elements_canonical.py::TestCanonicalElementsConstant` for the
"ELEMENTS is unchanged" side of that guarantee; this file covers "every
consumer of ELEMENTS/ELEMENT_TO_ANOMALY still works when handed an element
outside it."

Some consumer sites live inside heavy async pipeline functions
(`resolve_stateful_am_step_lists`) that this repo's existing tests avoid
invoking directly (see test_optimizer_pipeline_support_builds.py's
"Mirror the routing logic" pattern) — where that applies, this file exercises
the exact underlying primitive (e.g. `ELEMENT_TO_ANOMALY.get(...)`) the fixed
code path uses, rather than standing up the full async simulation.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from app.data.importers.nanoka_importer import ELEMENT_ID_MAP, NanokaImporter, _extract_element
from app.models.enums import Element
from app.services import damage_dag_service, disc_optimizer
from app.services.anomaly_simulator import ELEMENT_TO_ANOMALY, _dominant_buildup_element
from app.services.stat_calculator import TotalStats

if TYPE_CHECKING:
    import pytest

LUMIFLUX = Element.LUMIFLUX.value


class TestElementEnumHasLumiflux:
    def test_lumiflux_is_a_valid_element_member(self) -> None:
        assert Element.LUMIFLUX == "lumiflux"

    def test_element_id_map_has_confirmed_lumiflux_id(self) -> None:
        # Task 2 deliberately did NOT guess the numeric id. Task 5 re-seeded
        # against the isolated remielle-kit-db (port 5433), read the raw id
        # off _extract_element's unmapped-element warning ("Unmapped element
        # id(s) ['300'] in element_type"), and filled it in here — see
        # docs/LOG_remielle.md Task 5 (Worker).
        assert ELEMENT_ID_MAP[300] == Element.LUMIFLUX
        assert list(ELEMENT_ID_MAP.values()).count(Element.LUMIFLUX) == 1


class TestTotalStatsElementalDmg:
    """Audit row: stat_calculator.TotalStats.elemental_dmg (`:40`)."""

    def test_lumiflux_elemental_dmg_is_zero_no_bucket(self) -> None:
        stats = TotalStats()

        assert stats.elemental_dmg(LUMIFLUX) == 0
        # No lumiflux_dmg field was ever materialised on the dataclass.
        assert not hasattr(stats, "lumiflux_dmg")


class TestDiscOptimizerUnionFieldSelection:
    """Audit row: disc_optimizer `:553-555` union-field selection.

    Membership-guarded against `_ELEMENT_DMG_FIELDS`; a Lumiflux agent_element
    must not add a phantom `lumiflux_dmg` to the union fields.
    """

    def test_lumiflux_dmg_field_not_eligible_for_union(self) -> None:
        element_dmg_field = f"{LUMIFLUX}_dmg"

        assert element_dmg_field not in disc_optimizer._ELEMENT_DMG_FIELDS

    def test_union_field_selection_skips_lumiflux(self) -> None:
        """Mirror of the exact guard at disc_optimizer.py:554."""
        union_fields: list[str] = ["crit_rate", "crit_dmg"]
        agent_element = LUMIFLUX
        element_dmg_field = f"{agent_element}_dmg"
        if agent_element and element_dmg_field in disc_optimizer._ELEMENT_DMG_FIELDS:
            union_fields.append(element_dmg_field)

        assert union_fields == ["crit_rate", "crit_dmg"]
        assert f"{LUMIFLUX}_dmg" not in union_fields


class TestOptimizerPipelineAnomalyMapping:
    """Audit row: optimizer_pipeline.py:334 `ELEMENT_TO_ANOMALY[e.element]`.

    Was a bare subscript that would KeyError on a Lumiflux agent; now a
    guarded `.get()` that skips (see the fix at optimizer_pipeline.py's
    "anomaly_tick" branch). ELEMENT_TO_ANOMALY here is the exact dict object
    optimizer_pipeline imports at runtime (`from app.services.anomaly_simulator
    import ELEMENT_TO_ANOMALY`), so this directly exercises the primitive the
    fixed guarded lookup relies on.
    """

    def test_element_to_anomaly_has_no_lumiflux_entry(self) -> None:
        assert LUMIFLUX not in ELEMENT_TO_ANOMALY

    def test_guarded_lookup_skips_instead_of_raising(self) -> None:
        # Mirrors optimizer_pipeline.py's "anomaly_tick" branch: .get() + skip.
        anom_type = ELEMENT_TO_ANOMALY.get(LUMIFLUX)
        assert anom_type is None  # -> caller `continue`s, never raises KeyError


class TestDamageDagServiceDiscElementLoops:
    """Audit row: damage_dag_service `_DISC_ELEMENTS` loops.

    Iterates the canonical 6-tuple, never indexes by agent element — a disc
    with a stray `lumiflux_dmg` attribute is simply never visited.
    """

    def test_lumiflux_not_in_disc_elements(self) -> None:
        assert LUMIFLUX not in damage_dag_service._DISC_ELEMENTS

    def test_disc_element_loop_ignores_lumiflux_field(self) -> None:
        disc = SimpleNamespace(lumiflux_dmg=999, physical_dmg=0)
        registered = []
        for element in damage_dag_service._DISC_ELEMENTS:
            value = getattr(disc, f"{element}_dmg", 0)
            if value:
                registered.append(element)

        assert registered == []
        assert LUMIFLUX not in registered


class TestDominantBuildupElement:
    """Audit row: anomaly_simulator._dominant_buildup_element.

    Returns the agent element when no buildup rows carry weight (Remielle
    applies no conventional buildup) and never reaches an anomaly lookup.
    """

    def test_no_attacks_returns_agent_element(self) -> None:
        result = _dominant_buildup_element([], LUMIFLUX)

        assert result == LUMIFLUX

    def test_zero_buildup_attacks_return_agent_element_no_anomaly_lookup(self) -> None:
        attacks = [
            SimpleNamespace(element=LUMIFLUX, anomaly_buildup=0),
            SimpleNamespace(element=LUMIFLUX, anomaly_buildup=0),
        ]

        result = _dominant_buildup_element(attacks, LUMIFLUX)

        assert result == LUMIFLUX
        # The function never touches ELEMENT_TO_ANOMALY at all; confirm by
        # checking lumiflux still has no entry (would only matter if the
        # function looked it up, which it structurally cannot — no such call
        # exists in its body).
        assert LUMIFLUX not in ELEMENT_TO_ANOMALY


class TestEnemyResLookup:
    """Audit row: enemy_profiles.<element>_res lookup — correct by
    construction (no Lumiflux RES exists), covered here for completeness."""

    def test_lumiflux_res_defaults_to_zero(self) -> None:
        enemy = SimpleNamespace(physical_res=1000)

        assert getattr(enemy, f"{LUMIFLUX}_res", 0) == 0


class TestExtractElementWarnsOnUnmapped:
    """`_extract_element` (nanoka_importer.py:82) must warn — not silently
    fall back — when the element dict carries id(s) with no ELEMENT_ID_MAP
    entry (e.g. Remielle's real Lumiflux id, not yet mapped)."""

    def test_unmapped_id_logs_warning_and_falls_back_to_physical(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _extract_element({"999": "Lumiflux"})

        assert result == Element.PHYSICAL
        assert "unmapped element id" in caplog.text.lower()

    def test_unmapped_id_invokes_on_unmapped_callback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        callback = MagicMock()
        with caplog.at_level(logging.WARNING):
            result = _extract_element({"999": "Lumiflux"}, on_unmapped=callback)

        assert result == Element.PHYSICAL
        callback.assert_called_once_with()

    def test_mapped_id_does_not_warn_or_invoke_callback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        callback = MagicMock()
        with caplog.at_level(logging.WARNING):
            result = _extract_element({"201": "Fire"}, on_unmapped=callback)

        assert result == Element.FIRE
        callback.assert_not_called()
        assert "unmapped element id" not in caplog.text.lower()

    def test_empty_dict_falls_back_silently(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An empty element_type dict (no id at all) is not the same as an
        unmapped id — there is nothing to name in the warning, so no warning
        is emitted."""
        callback = MagicMock()
        with caplog.at_level(logging.WARNING):
            result = _extract_element({}, on_unmapped=callback)

        assert result == Element.PHYSICAL
        callback.assert_not_called()


class TestImporterUnmappedElementCounter:
    """The counter Task 2 wires up: `_extract_element`'s `on_unmapped` callback
    and the per-hit path both bump `NanokaImporter._unmapped_element_count`,
    which `import_all()` surfaces in the seed summary dict."""

    def _importer(self) -> NanokaImporter:
        return NanokaImporter(session=MagicMock())

    def test_counter_starts_at_zero(self) -> None:
        importer = self._importer()

        assert importer._unmapped_element_count == 0

    def test_note_unmapped_element_increments(self) -> None:
        importer = self._importer()

        importer._note_unmapped_element()
        importer._note_unmapped_element()

        assert importer._unmapped_element_count == 2

    async def test_import_all_surfaces_counter_in_summary(self) -> None:
        importer = self._importer()
        importer.import_agents = MagicMock(return_value=_async_result(1))
        importer.import_w_engines = MagicMock(return_value=_async_result(0))
        importer.import_disc_sets = MagicMock(return_value=_async_result(0))
        importer.import_enemies = MagicMock(return_value=_async_result(0))
        importer._unmapped_element_count = 3

        counts = await importer.import_all()

        assert counts["unmapped_elements"] == 3

    def test_extract_element_on_unmapped_wired_to_importer_counter(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """End-to-end: the callback passed at the real call site is the bound
        importer method, so an unmapped agent-level element id increments the
        real counter, not just a test double."""
        importer = self._importer()
        with caplog.at_level(logging.WARNING):
            result = _extract_element(
                {"999": "Lumiflux"}, on_unmapped=importer._note_unmapped_element
            )

        assert result == Element.PHYSICAL
        assert importer._unmapped_element_count == 1

    def test_per_hit_unmapped_nonzero_element_warns_and_increments(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The per-hit path (nanoka_importer.py ~:454) must warn — not
        silently inherit the agent's element — on an unmapped non-zero
        element_type, mirroring _extract_element's treatment."""
        importer = self._importer()
        agent = SimpleNamespace(id=1, hakushin_id=42, element=Element.PHYSICAL)
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Test",
                            "param": [
                                {
                                    "name": "1 Test DMG",
                                    "param": {
                                        "9001": {
                                            "damage_percentage": 100,
                                            "damage_percentage_growth": 10,
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            },
            "skill_list": {
                # 999 is a deliberately unmapped, non-zero element_type id.
                "9001": {"element_type": 999},
            },
        }

        with caplog.at_level(logging.WARNING):
            asyncio.run(importer._import_attacks(agent, data))

        assert "unmapped per-hit element id" in caplog.text.lower()
        assert importer._unmapped_element_count == 1
        added_attack = importer.session.add.call_args[0][0]
        # No mapping exists for 999, so the row falls back to the agent's
        # element — but loudly, per the assertions above.
        assert added_attack.element == Element.PHYSICAL

    def test_per_hit_zero_element_type_inherits_silently(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """element_type 0 means 'inherit the agent's element' — a legitimate,
        silent case that must NOT warn or increment the counter."""
        importer = self._importer()
        agent = SimpleNamespace(id=1, hakushin_id=42, element=Element.FIRE)
        data = {
            "skill": {
                "basic": {
                    "description": [
                        {
                            "name": "Basic Attack: Test",
                            "param": [
                                {
                                    "name": "1 Test DMG",
                                    "param": {
                                        "9002": {
                                            "damage_percentage": 100,
                                            "damage_percentage_growth": 10,
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            },
            "skill_list": {
                "9002": {"element_type": 0},
            },
        }

        with caplog.at_level(logging.WARNING):
            asyncio.run(importer._import_attacks(agent, data))

        assert "unmapped per-hit element id" not in caplog.text.lower()
        assert importer._unmapped_element_count == 0
        added_attack = importer.session.add.call_args[0][0]
        assert added_attack.element == Element.FIRE


def _async_result(value: int):
    async def _coro() -> int:
        return value

    return _coro()
