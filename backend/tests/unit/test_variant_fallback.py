"""Task 4 — a `variant` move with no `variant_label` must not break a saved combo.

Re-classifying a move from `sequential` to `variant` invalidates every combo already
saved against it: those steps carry no `variant_label`, because none existed when they
were saved. Before this change the three cycle implementations disagreed about what to
do, and all three were wrong in different directions:

- `combo_step_resolver._resolve_variant` raised **HTTP 400**, failing the whole
  team-DPS request — an outage, not a corrected number;
- `optimizer_pipeline` fell through and kept **all** rows — a silent over-count;
- `api/v1/simulate._filter_attacks` did the same.

All three now call `resolve_variant_selection`: missing label → the first label in the
(sorted) available list, with a warning; unknown label → 404 in every path.

`DESIGN_sequential_variant.md` §5.8. This is *not* the de-duplication of the cycle logic
itself (Scope 3) — it is one shared decision verified in three places, plus one test that
pins the three to the same row set for the same input.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.simulate import _filter_attacks
from app.models.enums import HitMode
from app.services.build_damage_service import BuildSnapshot
from app.services.combo_step_resolver import (
    resolve_combo_sequence,
    resolve_variant_selection,
)

MOVE = "EX Special Attack: Soaring Light"


def _attack(variant_label: str, damage_base: int, hit_index: int = 0) -> MagicMock:
    a = MagicMock()
    a.id = f"att-{variant_label}-{hit_index}"
    a.hit_index = hit_index
    a.name = MOVE
    a.skill_key = "EXSpecial"
    a.hit_mode = HitMode.VARIANT
    a.variant_label = variant_label
    a.element = "ether"
    a.damage_base = damage_base
    a.damage_growth = 0
    a.stun_base = 0
    a.stun_growth = 0
    a.energy_gain = 0
    a.anomaly_buildup = 0
    return a


def _variant_rows() -> list[MagicMock]:
    """Two mutually exclusive contexts. Sorted labels: ['1-Sword', '6-Swords']."""
    return [_attack("6-Swords", 90000), _attack("1-Sword", 10000)]


def _build() -> MagicMock:
    b = MagicMock()
    b.potential_rank = 5
    b.id = "build-1"
    b.agent_id = "agent-1"
    b.skill_levels = "12,12,12,12,12"
    return b


def _repo(attacks: list[MagicMock]) -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = attacks
    return repo


# --- the shared decision ---------------------------------------------------


class TestResolveVariantSelection:
    def test_known_label_passes_through_without_warning(self) -> None:
        chosen, warning = resolve_variant_selection(MOVE, ["1-Sword", "6-Swords"], "6-Swords")
        assert chosen == "6-Swords"
        assert warning is None

    def test_missing_label_picks_first_sorted_label_and_warns(self) -> None:
        chosen, warning = resolve_variant_selection(MOVE, ["1-Sword", "6-Swords"], None)
        assert chosen == "1-Sword"
        assert warning is not None
        assert "1-Sword" in warning

    def test_missing_label_is_deterministic(self) -> None:
        """Same input, same answer — the point of the fallback is that it is stable."""
        first = resolve_variant_selection(MOVE, ["1-Sword", "6-Swords"], None)[0]
        again = resolve_variant_selection(MOVE, ["1-Sword", "6-Swords"], None)[0]
        assert first == again == "1-Sword"

    def test_unknown_label_is_a_hard_404(self) -> None:
        with pytest.raises(HTTPException) as exc:
            resolve_variant_selection(MOVE, ["1-Sword", "6-Swords"], "Nonexistent")
        assert exc.value.status_code == 404

    def test_no_labels_at_all_keeps_everything_but_warns(self) -> None:
        """Degenerate data: declared variant, no row carries a label."""
        chosen, warning = resolve_variant_selection(MOVE, [], None)
        assert chosen is None
        assert warning is not None


# --- implementation 1: combo_step_resolver ---------------------------------


class TestComboStepResolverPath:
    @pytest.mark.asyncio
    async def test_missing_label_resolves_instead_of_raising_400(self) -> None:
        warnings: list[str] = []
        steps = await resolve_combo_sequence(
            [{"move_name": MOVE, "label": "SL"}],
            build=_build(),
            attack_repo=_repo(_variant_rows()),
            warnings=warnings,
        )
        assert len(steps) == 1, "must pick one variant, not keep both rows"
        assert steps[0].attack_id == "att-1-Sword-0"
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_explicit_label_still_wins_and_warns_nothing(self) -> None:
        warnings: list[str] = []
        steps = await resolve_combo_sequence(
            [{"move_name": MOVE, "variant_label": "6-Swords", "label": "SL"}],
            build=_build(),
            attack_repo=_repo(_variant_rows()),
            warnings=warnings,
        )
        assert [s.attack_id for s in steps] == ["att-6-Swords-0"]
        assert warnings == []

    @pytest.mark.asyncio
    async def test_unknown_label_still_404s(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await resolve_combo_sequence(
                [{"move_name": MOVE, "variant_label": "Nope", "label": "SL"}],
                build=_build(),
                attack_repo=_repo(_variant_rows()),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_warnings_sink_is_optional(self) -> None:
        """Every existing caller omits it; omitting must not raise."""
        steps = await resolve_combo_sequence(
            [{"move_name": MOVE, "label": "SL"}],
            build=_build(),
            attack_repo=_repo(_variant_rows()),
        )
        assert len(steps) == 1


# --- implementation 2: api/v1/simulate -------------------------------------


class TestSimulatePath:
    def _step(self, variant_label: str | None) -> MagicMock:
        s = MagicMock()
        s.move_name = MOVE
        s.variant_label = variant_label
        s.agent_id = "dps"
        s.cycle_position = None
        return s

    def test_missing_label_no_longer_keeps_all_rows(self) -> None:
        warnings: list[str] = []
        rows, _, _ = _filter_attacks(_variant_rows(), self._step(None), {}, warnings)
        assert [a.variant_label for a in rows] == ["1-Sword"]
        assert len(warnings) == 1

    def test_explicit_label_selects_it(self) -> None:
        rows, _, _ = _filter_attacks(_variant_rows(), self._step("6-Swords"), {}, [])
        assert [a.variant_label for a in rows] == ["6-Swords"]

    def test_unknown_label_404s(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _filter_attacks(_variant_rows(), self._step("Nope"), {}, [])
        assert exc.value.status_code == 404


# --- implementation 3: optimizer_pipeline ----------------------------------


async def _optimizer_rows_for(variant_label: str | None) -> list[str]:
    """Drive the real `resolve_stateful_am_step_lists` and capture its row set.

    `simulate` is patched to capture the `SimulatedAttackStep` list, which is the
    optimizer's equivalent of "the rows this step resolved to". Everything else is the
    production code path.
    """
    from app.services import optimizer_pipeline

    captured: dict[str, list] = {}

    # **kwargs so this double survives new simulate() parameters — dev added
    # lumiflux_specs / phase_flow_windows. This test is about row selection.
    def _fake_simulate(builds, steps, enemy, moves_db, **kwargs):
        captured["steps"] = steps
        result = MagicMock()
        result.events = []
        result.totals = {}
        return result

    combo = MagicMock()
    step_raw: dict = {"move_name": MOVE, "label": "SL"}
    if variant_label:
        step_raw["variant_label"] = variant_label
    combo.sequence = [step_raw]
    snapshot = BuildSnapshot(agent_name="Ye Shunguang", agent_element="ether")

    with (
            patch("app.services.anomaly_simulator.simulate", _fake_simulate),
            patch.object(optimizer_pipeline, "enumerate_coarse_am_values", return_value=[100]),
        patch.object(
            optimizer_pipeline, "_make_am_variant", side_effect=lambda b, _extra: replace(b)
        ),
    ):
        await optimizer_pipeline.resolve_stateful_am_step_lists(
            combo=combo,
            build=_build(),
            base_build=snapshot,
            enemy=MagicMock(),
            attack_repo=_repo(_variant_rows()),
            inventory=[],
            am_2pc_sets={},
            conditions=MagicMock(active=set(), stack_counts={}),
        )
    return [a.variant_label for a in captured["steps"][0].attacks]


class TestOptimizerPipelinePath:
    @pytest.mark.asyncio
    async def test_missing_label_no_longer_keeps_all_rows(self) -> None:
        assert await _optimizer_rows_for(None) == ["1-Sword"]

    @pytest.mark.asyncio
    async def test_explicit_label_selects_it(self) -> None:
        assert await _optimizer_rows_for("6-Swords") == ["6-Swords"]

    @pytest.mark.asyncio
    async def test_unknown_label_404s(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await _optimizer_rows_for("Nope")
        assert exc.value.status_code == 404


# --- the cross-check: all three agree --------------------------------------


class TestAllThreePathsAgree:
    """The reason this task exists. Same input → same rows, in all three.

    A future edit that "fixes" one implementation without the others fails here.
    """

    @pytest.mark.asyncio
    async def test_same_row_set_for_a_label_less_step(self) -> None:
        resolver_steps = await resolve_combo_sequence(
            [{"move_name": MOVE, "label": "SL"}],
            build=_build(),
            attack_repo=_repo(_variant_rows()),
        )
        resolver_ids = [s.attack_id for s in resolver_steps]

        sim_step = MagicMock()
        sim_step.move_name = MOVE
        sim_step.variant_label = None
        sim_step.agent_id = "dps"
        sim_step.cycle_position = None
        simulate_rows, _, _ = _filter_attacks(_variant_rows(), sim_step, {}, [])
        simulate_ids = [str(a.id) for a in simulate_rows]

        optimizer_labels = await _optimizer_rows_for(None)
        optimizer_ids = [f"att-{label}-0" for label in optimizer_labels]

        assert resolver_ids == simulate_ids == optimizer_ids == ["att-1-Sword-0"]
