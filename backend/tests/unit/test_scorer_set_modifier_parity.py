"""One home for set-modifier resolution, and it must stay that way (#171).

`disc_optimizer` and `scorer_support` each used to carry a byte-identical private
copy of `_applicable_set_modifiers`. They drifted: #172 taught the optimizer's to
resolve `equipper_is_*` and the scorer's silently kept dropping every gated row,
so the disc ranker under-scored Lumiflux builds by the same 2.3% the optimizer
had. #173 fixed the second copy; the copies are now consolidated into
`snapshot_builder.applicable_set_modifiers`.

The earlier version of this file pinned the two copies against each other. With
one implementation that comparison is meaningless, so it is replaced by the
stronger guard: assert no module grows a third copy.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.services.modifier_loader import load_disc_set_modifiers
from app.services.snapshot_builder import applicable_set_modifiers

FEATHERED_FATE = 34100  # carries a Lumiflux-gated 4pc row
FREEDOM_BLUES = 31300   # ungated control
_APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def _mods(*set_ids):
    return {sid: load_disc_set_modifiers(str(sid)) for sid in set_ids}


class TestThereIsExactlyOneImplementation:
    """The consolidation guard — replaces the old two-copy parity check."""

    def test_no_module_defines_its_own_copy(self) -> None:
        offenders = []
        for path in _APP.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover - defensive
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.endswith(
                    "applicable_set_modifiers"
                ):
                    rel = path.relative_to(_APP.parent)
                    if rel.as_posix() != "app/services/snapshot_builder.py":
                        offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            "a second `applicable_set_modifiers` has reappeared at "
            f"{offenders}. Two copies of this helper drifted once already and "
            "under-scored every Lumiflux build through the ranker (#171) — "
            "import `snapshot_builder.applicable_set_modifiers` instead."
        )

    def test_both_former_owners_import_the_shared_one(self) -> None:
        from app.services import disc_optimizer, scorer_support

        for mod in (disc_optimizer, scorer_support):
            assert mod.applicable_set_modifiers is applicable_set_modifiers, mod.__name__


class TestTheGateActuallyGates:
    @pytest.mark.parametrize("counts", [{FEATHERED_FATE: 4},
                                        {FEATHERED_FATE: 4, FREEDOM_BLUES: 2}])
    def test_lumiflux_equipper_keeps_the_gated_4pc(self, counts) -> None:
        out = applicable_set_modifiers(counts, _mods(*counts), "anomaly", "lumiflux")
        assert any(m.stat == "anomaly_dmg_bonus" for m in out)

    def test_non_lumiflux_equipper_does_not(self) -> None:
        out = applicable_set_modifiers(
            {FEATHERED_FATE: 4}, _mods(FEATHERED_FATE), "anomaly", "fire")
        assert not any(m.stat == "anomaly_dmg_bonus" for m in out)

    def test_ungated_rows_always_survive(self) -> None:
        out = applicable_set_modifiers(
            {FEATHERED_FATE: 4}, _mods(FEATHERED_FATE), "anomaly", "fire")
        assert any(m.stat == "anomaly_proficiency_flat" for m in out)

    def test_a_2pc_count_does_not_grant_the_4pc(self) -> None:
        out = applicable_set_modifiers(
            {FEATHERED_FATE: 2}, _mods(FEATHERED_FATE), "anomaly", "lumiflux")
        assert not any(m.source.value == "disc_set_4pc" for m in out)


class TestTheRealCallSitePassesAnEquipper:
    """`_build_base_for_target` must thread the equipper, not just accept one.

    The parity cases above exercise the helper directly. That is precisely the
    shape that let two earlier bugs through this session: a helper that is
    correct in isolation while its production call site never supplies the input
    that makes it work. So this drives the real entry point and asserts the
    gated bonus actually lands in the returned snapshot.
    """

    FEATHERED_FATE = 34100

    @staticmethod
    def _snapshot(element: str):
        from app.services.build_damage_service import BuildSnapshot

        return BuildSnapshot(
            agent_element=element,
            agent_specialty="anomaly",
            agent_level=60,
            agent_base_atk=1000,
            disc_stats=[],
            modifiers=[],
        )

    @staticmethod
    def _disc(slot: int, set_id: int):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=f"d{slot}", slot=slot, rarity="S",
            main_stat_type="atk_pct", main_stat_value=3000, substats=[],
            disc_set=SimpleNamespace(hakushin_id=set_id),
        )

    def _run(self, element: str):
        from app.services.disc_optimizer import DiscCandidate
        from app.services.modifier_loader import load_disc_set_modifiers
        from app.services.scorer_support import _build_base_for_target

        discs = [self._disc(i, self.FEATHERED_FATE) for i in range(1, 7)]
        target = DiscCandidate(
            disc_id="d1", slot=1, set_id=self.FEATHERED_FATE,
            main_stat_type="atk_pct", main_stat_value=3000,
        )
        return _build_base_for_target(
            stripped=self._snapshot(element),
            build_discs=discs,
            target=target,
            disc_set_modifiers={self.FEATHERED_FATE: load_disc_set_modifiers(
                str(self.FEATHERED_FATE))},
        )

    def test_a_lumiflux_build_receives_the_gated_4pc(self) -> None:
        snap = self._run("lumiflux")
        assert any(m.stat == "anomaly_dmg_bonus" for m in snap.modifiers), (
            "the Lumiflux-gated 4pc did not reach the scorer's base snapshot — "
            "`_build_base_for_target` is not threading the equipper (#171)"
        )

    def test_a_non_lumiflux_build_does_not(self) -> None:
        snap = self._run("fire")
        assert not any(m.stat == "anomaly_dmg_bonus" for m in snap.modifiers)

    def test_ungated_set_rows_reach_both(self) -> None:
        for element in ("lumiflux", "fire"):
            snap = self._run(element)
            assert any(m.stat == "anomaly_proficiency_flat" for m in snap.modifiers), element
