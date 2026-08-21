"""Deriving the Potential value ramps from nanoka descriptions (#90 Track 2).

The derivation is: strip markup from a Potential node's `desc`, take every number in
document order, divide by 100 where a `%` suffix follows. Applied to nodes `<aid>01`..`05`
(Levels II–VI) and transposed with a leading zero for Level I, it produces one six-element
ramp per param, indexed by `builds.potential_rank - 1`.

`docs/RESEARCH_potential_ramps.md` establishes that this reproduces ZO's `potentialParams`
for **27 of 28** params across all 10 agents that have them. The 28th is ZO's own defect,
pinned below.

These are pure-function tests: no DB, no network. The seeded-DB half — that every agent's
stored ramps still match ZO — lives in `tests/integration/test_potential_ramp_crossval.py`,
which is where the corpus-wide comparison belongs.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.data.importers.nanoka_importer import (
    _parse_potential_ramps,
    _parse_potential_values,
)


def _nodes(*descs: str) -> dict[str, dict[str, str]]:
    """A `potential_detail` dict: node 00 (Level I, no values) plus Levels II–VI."""
    return {f"11910{i}": {"desc": d} for i, d in enumerate(("", *descs))}


class TestParseValues:
    def test_percentages_become_decimals(self) -> None:
        """ZO's convention and the source text's: 1.6% is stored as 0.016."""
        assert _parse_potential_values("increases by <color=#2BAD00>1.6%</color>") == [0.016]

    def test_bare_numbers_stay_literal(self) -> None:
        """Not every number is a percentage — stack caps, durations and flat stats
        appear in the same sentence and must not be scaled."""
        assert _parse_potential_values("At <color=#2BAD00>10</color> stacks") == [10.0]

    def test_document_order_is_preserved(self) -> None:
        """Order is the ONLY thing binding a value to its meaning — the numbers carry no
        labels, so param *i* is 'the i-th number in the sentence' and nothing else."""
        desc = (
            "CRIT DMG +<color=#2BAD00>1.6%</color> per stack, "
            "max <color=#2BAD00>10</color>, ignoring <color=#2BAD00>3.3%</color> RES"
        )
        assert _parse_potential_values(desc) == [0.016, 10.0, 0.033]

    def test_markup_is_stripped_not_matched(self) -> None:
        """Colour codes contain digits (#2BAD00). Matching numbers before stripping tags
        would harvest them."""
        assert _parse_potential_values("<color=#2BAD00>5%</color>") == [0.05]

    def test_empty_and_missing_are_empty(self) -> None:
        assert _parse_potential_values("") == []
        assert _parse_potential_values(None) == []  # type: ignore[arg-type]


class TestParseRamps:
    def test_ellen_shape(self) -> None:
        """The worked example from RESEARCH §2, matching ZO's Ellen term for term."""
        ramps = _parse_potential_ramps(
            _nodes(
                "by 1.6% per stack. At 10 stacks, ignores 3.3% RES",
                "by 2.4% per stack. At 10 stacks, ignores 5% RES",
                "by 3.2% per stack. At 10 stacks, ignores 6.7% RES",
                "by 4% per stack. At 10 stacks, ignores 8.3% RES",
                "by 4.8% per stack. At 10 stacks, ignores 10% RES",
            )
        )
        assert ramps == [
            [0.0, 0.016, 0.024, 0.032, 0.04, 0.048],
            [0.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            [0.0, 0.033, 0.05, 0.067, 0.083, 0.1],
        ]

    def test_level_one_is_always_zero(self) -> None:
        """Index 0 is Level I, which buys the kit variant and NO value bonus. It is
        supplied as a zero rather than read, because node <aid>00's desc is empty — the
        same thing ZO's generator does by dropping that node and prepending a zero row.
        """
        ramps = _parse_potential_ramps(_nodes("5%", "10%", "15%", "20%", "25%"))
        assert ramps is not None
        assert all(param[0] == 0.0 for param in ramps)

    def test_every_ramp_has_six_entries(self) -> None:
        """Six game levels: I..VI. `potential_rank - 1` indexes this, and rank 0 (not
        unlocked) never indexes it at all."""
        ramps = _parse_potential_ramps(_nodes("5%", "10%", "15%", "20%", "25%"))
        assert ramps is not None
        assert all(len(param) == 6 for param in ramps)

    def test_a_flat_param_is_preserved_not_collapsed(self) -> None:
        """A param identical across all five levels is a CONSTANT that happens to live in
        this array — Burnice has five such, Rina four. It is kept, because dropping it
        would shift every later param's index and silently re-bind its meaning."""
        ramps = _parse_potential_ramps(_nodes(*["25 AM"] * 5))
        assert ramps == [[0.0, 25.0, 25.0, 25.0, 25.0, 25.0]]

    def test_no_potential_detail_is_none(self) -> None:
        assert _parse_potential_ramps({}) is None

    def test_nodes_without_numbers_are_none(self) -> None:
        assert _parse_potential_ramps(_nodes(*[""] * 5)) is None

    def test_a_width_disagreement_is_refused_not_padded(self) -> None:
        """If one level yields a different count, the param ORDER no longer means the same
        thing at every level. Zero-padding would bind param *i* to one mechanic at Level
        II and another at Level III — silently. Refusing is the loud option.
        """
        ramps = _parse_potential_ramps(
            _nodes("5% and 10", "10% and 10", "15%", "20% and 10", "25% and 10")
        )
        assert ramps is None


class TestZoDefectIsPinned:
    """ZO's `potentialParams` is a regex scrape of this same prose, and it is wrong once.

    Jane's sole ramp reads `[0, 0.1, 0.15, 0.2, 25, 0.3]` at ZO `8d9cdbb` — index 4 is
    `25` where `0.25` belongs, a 100x error and the only non-fraction in an otherwise clean
    arithmetic sequence. This test pins that our derivation produces the correct value, so
    a future "sync with ZO" cannot quietly import the defect.
    """

    def test_jane_ramp_is_the_arithmetic_sequence(self) -> None:
        ramps = _parse_potential_ramps(_nodes("10%", "15%", "20%", "25%", "30%"))
        assert ramps == [[0.0, 0.1, 0.15, 0.2, 0.25, 0.3]]

    def test_the_corrupt_zo_value_is_not_reproduced(self) -> None:
        ramps = _parse_potential_ramps(_nodes("10%", "15%", "20%", "25%", "30%"))
        assert ramps is not None
        assert 25.0 not in ramps[0], "ZO's 100x error must not survive the derivation"

    @pytest.mark.parametrize("step", [1, 2, 3, 4])
    def test_the_sequence_is_uniform(self, step: int) -> None:
        """0.05 apart at every rung — which is what makes ZO's 25 obviously wrong."""
        ramps = _parse_potential_ramps(_nodes("10%", "15%", "20%", "25%", "30%"))
        assert ramps is not None
        assert round(ramps[0][step + 1] - ramps[0][step], 10) == 0.05


class TestBindPotentialParam:
    """Binding a modifier's value to a ramp (#90 Track 2).

    `ramp[potential_rank - 1] * scale`. The scale is stated rather than inferred from the
    stat name, because the ramps hold what the source text says — a percentage as a
    decimal, a stack cap or flat stat literally — while modifier values are basis points
    for percentage stats. Guessing wrong is a silent 100x.
    """

    # Ellen's CRIT DMG per stack. ClassVar: read-only fixture data, never mutated.
    RAMP: ClassVar[list[list[float]]] = [[0.0, 0.016, 0.024, 0.032, 0.04, 0.048]]

    def _mod(self, **kw):
        from app.services.modifiers import Modifier, ModifierSource

        base = {"stat": "crit_dmg", "value": 0, "source": ModifierSource.CORE_SKILL}
        return Modifier(**{**base, **kw})

    def test_an_unbound_row_is_returned_untouched(self) -> None:
        from app.services.modifiers import bind_potential_param

        mod = self._mod(value=1234)
        assert bind_potential_param(mod, 5, self.RAMP) is mod

    def test_rank_zero_resolves_to_zero(self) -> None:
        """Not unlocked: the ramp is not indexed at all."""
        from app.services.modifiers import bind_potential_param

        bound = bind_potential_param(self._mod(potential_param=0), 0, self.RAMP)
        assert bound.value == 0

    def test_level_one_resolves_to_zero(self) -> None:
        """Level I buys the kit variant and no value bonus — ramp index 0 is 0."""
        from app.services.modifiers import bind_potential_param

        bound = bind_potential_param(self._mod(potential_param=0), 1, self.RAMP)
        assert bound.value == 0

    @pytest.mark.parametrize(
        ("rank", "expected"), [(2, 160), (3, 240), (4, 320), (5, 400), (6, 480)]
    )
    def test_levels_two_to_six_scale_to_basis_points(self, rank: int, expected: int) -> None:
        from app.services.modifiers import bind_potential_param

        bound = bind_potential_param(self._mod(potential_param=0), rank, self.RAMP)
        assert bound.value == expected

    def test_a_flat_stat_uses_scale_one(self) -> None:
        """Rina's 576 flat ATK cap is literal in the ramp and literal in the modifier —
        multiplying it by 10000 would be the silent 100x this field exists to prevent."""
        from app.services.modifiers import bind_potential_param

        ramp = [[0.0, 576.0, 576.0, 576.0, 576.0, 576.0]]
        bound = bind_potential_param(
            self._mod(stat="flat_atk", potential_param=0, potential_param_scale=1), 6, ramp
        )
        assert bound.value == 576

    def test_a_missing_ramp_resolves_to_zero_not_an_error(self) -> None:
        """Inert beats wrong at calc time; validate_kits Rule 8c catches it at author
        time, which is where a typo should surface."""
        from app.services.modifiers import bind_potential_param

        assert bind_potential_param(self._mod(potential_param=0), 5, None).value == 0
        assert bind_potential_param(self._mod(potential_param=9), 5, self.RAMP).value == 0

    def test_binding_does_not_mutate_the_original(self) -> None:
        """Modifiers come from a process-wide loader cache."""
        from app.services.modifiers import bind_potential_param

        mod = self._mod(potential_param=0)
        bind_potential_param(mod, 6, self.RAMP)
        assert mod.value == 0


class TestRule8cDegradesWithoutADatabase:
    """L0 must stay hermetic (#90 Track 2).

    CI runs L0/L1/L2/L6/LC with **no database** — that is the tier's whole contract, and
    the reason `attacks.param_name` lives in L5 rather than L0. Rule 8c's index check
    needs the seeded DB to know how many ramps an agent has, so it must degrade to
    "cannot check" rather than emit a finding: failing there turns an ABSENCE into a red
    build, which is what happened on the first push of this branch.

    `--require-db` is what makes the skip block, so the manually-confirmed gate still
    proves it. These tests pin both halves of that arrangement.
    """

    def _corpus(self):
        from pathlib import Path

        return [(
            Path("agents/ellen.json"),
            {
                "source_name": "Ellen",
                "modifiers": [{
                    "stat": "crit_dmg", "value": 0, "source_label": "X",
                    "potential": "unlocked", "potential_param": 0,
                }],
            },
        )]

    def _reset(self, mod) -> None:
        mod.L0_POTENTIAL_STATUS.update({"ramps_available": True, "bound_rows_seen": False})

    def test_no_finding_is_emitted_without_a_database(self) -> None:
        from unittest.mock import patch

        import scripts.validate_kits as v

        self._reset(v)
        with patch.object(v, "_potential_ramp_counts", dict):
            findings = v.check_l0(self._corpus())
        assert not [f for f in findings if f.code.startswith("potential_param")]

    def test_the_skip_is_recorded_so_require_db_can_block(self) -> None:
        from unittest.mock import patch

        import scripts.validate_kits as v

        self._reset(v)
        with patch.object(v, "_potential_ramp_counts", dict):
            v.check_l0(self._corpus())
        assert v.L0_POTENTIAL_STATUS == {"ramps_available": False, "bound_rows_seen": True}
        assert "l0" in v.unrunnable_levels(["l0"])

    def test_a_corpus_binding_nothing_reports_no_skip(self) -> None:
        """Otherwise every DB-less run over an unaffected corpus would report a skip
        nobody can act on."""
        from pathlib import Path
        from unittest.mock import patch

        import scripts.validate_kits as v

        self._reset(v)
        corpus = [(
            Path("agents/miyabi.json"),
            {"source_name": "Miyabi", "modifiers": [{"stat": "crit_dmg", "value": 500}]},
        )]
        with patch.object(v, "_potential_ramp_counts", dict):
            v.check_l0(corpus)
        assert "l0" not in v.unrunnable_levels(["l0"])

    def test_with_a_database_the_index_is_actually_checked(self) -> None:
        from unittest.mock import patch

        import scripts.validate_kits as v

        self._reset(v)
        corpus = self._corpus()
        corpus[0][1]["modifiers"][0]["potential_param"] = 9  # Ellen has 3 ramps
        with patch.object(v, "_potential_ramp_counts", lambda: {"ellen": 3}):
            findings = v.check_l0(corpus)
        assert any(f.code == "potential_param_out_of_range" for f in findings)
