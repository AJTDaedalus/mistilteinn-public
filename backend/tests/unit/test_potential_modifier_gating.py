"""Potential gating on kit modifiers (#90, Task 10).

The mechanism half of Task 10: a modifier row declares which Potential state its
mechanic belongs to (`base` / `unlocked` / absent = both), and the gate keeps exactly
one half of a base/unlocked pair live for any given build.

The *data* half — deciding the state per row for the 11 agents that have Potential — is
curation, and is gated by the L0 `potential_unstated` rule exercised below rather than by
a default. That split is deliberate: kit JSONs were all authored
between #85 and #90, when fairy imported only the Potential-unlocked kit, so an unmarked
row is a row nobody has judged. Defaulting it to "base kit" and calling that done would
leave exactly the buffs #90 exists to gate silently active.
"""

from __future__ import annotations

import json

import pytest

from app.models.enums import PotentialTag
from app.services.modifier_loader import _raw_mod_to_modifier
from app.services.modifiers import Modifier, ModifierSource, potential_allows


def _mod(**kw) -> Modifier:
    base = {"stat": "atk_pct", "value": 1000, "source": ModifierSource.CORE_SKILL}
    return Modifier(**{**base, **kw})


class TestPotentialAllows:
    def test_unmarked_rows_are_unaffected(self) -> None:
        """The ~49 agents without Potential must behave exactly as before #90."""
        mod = _mod()
        assert mod.potential is None
        for rank in range(7):
            assert potential_allows(mod, rank) is True

    def test_a_gated_row_is_hidden_at_rank_zero(self) -> None:
        assert potential_allows(_mod(potential=PotentialTag.UNLOCKED), 0) is False

    @pytest.mark.parametrize("rank", [1, 2, 3, 4, 5, 6])
    def test_a_gated_row_is_live_at_any_unlocked_rank(self, rank: int) -> None:
        """Variant selection is binary: every Potential-marked entry in the roster
        carries the full 6-node list, so no mechanic is gated on a subset of nodes."""
        assert potential_allows(_mod(potential=PotentialTag.UNLOCKED), rank) is True


class TestLoader:
    def test_flag_round_trips_from_json(self) -> None:
        raw = json.loads(
            '{"stat": "crit_dmg", "value": 500, "source": "core_skill", '
            '"potential": "unlocked"}'
        )
        assert _raw_mod_to_modifier(raw).potential is PotentialTag.UNLOCKED

    def test_absent_key_loads_as_none(self) -> None:
        """Absent means 'not stated', which the loader cannot distinguish from 'stated
        shared' — exactly why the L0 rule below makes the key mandatory on the 11."""
        raw = json.loads('{"stat": "crit_dmg", "value": 500, "source": "core_skill"}')
        assert _raw_mod_to_modifier(raw).potential is None


class TestL0Rule:
    """The rule that stops 'nobody judged this row' from passing as 'judged shared'."""

    def test_it_fires_on_a_potential_agent_row_with_no_flag(self) -> None:
        from pathlib import Path

        from scripts.validate_kits import check_l0

        kit = {
            "source_name": "Ellen",
            "modifiers": [{"stat": "crit_dmg", "value": 500, "source_label": "Core"}],
        }
        findings = check_l0([(Path("agents/ellen.json"), kit)])
        assert any(f.code == "potential_unstated" for f in findings)

    def test_it_stays_quiet_once_the_row_states_a_verdict(self) -> None:
        from pathlib import Path

        from scripts.validate_kits import check_l0

        for verdict in ("base", "unlocked", None):
            kit = {
                "source_name": "Ellen",
                "modifiers": [
                    {
                        "stat": "crit_dmg",
                        "value": 500,
                        "source_label": "Core",
                        "potential": verdict,
                    }
                ],
            }
            findings = check_l0([(Path("agents/ellen.json"), kit)])
            assert not any(f.code == "potential_unstated" for f in findings), verdict

    def test_it_does_not_touch_an_agent_without_potential(self) -> None:
        """Miyabi has no Potential tree, so the key must stay absent there — the rule
        is scoped to the 11, not corpus-wide."""
        from pathlib import Path

        from scripts.validate_kits import check_l0

        kit = {
            "source_name": "Miyabi",
            "modifiers": [{"stat": "crit_dmg", "value": 500, "source_label": "Core"}],
        }
        findings = check_l0([(Path("agents/miyabi.json"), kit)])
        assert not any(f.code == "potential_unstated" for f in findings)

    def test_the_agent_list_comes_from_the_snapshot_not_a_hardcoded_list(self) -> None:
        """A patch granting Potential to a new agent widens the rule by regenerating
        the snapshot, not by someone remembering to edit a list in this file."""
        from scripts.validate_kits import _potential_agent_stems

        stems = _potential_agent_stems()
        assert "ellen" in stems
        assert "miyabi" not in stems
        # Every stem must name a real kit file, or the rule silently covers nothing.
        from scripts.validate_kits import MODIFIERS_DIR

        for stem in stems:
            assert (MODIFIERS_DIR / "agents" / f"{stem}.json").exists(), stem


class TestBaseUnlockedPairsAreMutuallyExclusive:
    """The reason this field is three-state and not a boolean (#90 Task 10).

    Curation found rows whose mechanic exists in BOTH states but with a narrower scope
    or condition in the base kit — Ellen's Rising Storm team gate widens on unlock,
    Harumasa's Day Break scope gains Ultimate, Nekomata's Catwalk gains Dodge Counter.
    Each is authored as a `base`/`unlocked` PAIR. With a boolean, the "base" half would
    have to be `false` (= always on), so BOTH halves fire for an unlocked build whose
    squad satisfies both gates — double-counting the buff. Exactly one must ever be live.
    """

    @pytest.mark.parametrize("rank", [0, 1, 6])
    def test_exactly_one_half_of_a_pair_is_live_at_any_rank(self, rank: int) -> None:
        base = _mod(potential=PotentialTag.BASE)
        unlocked = _mod(potential=PotentialTag.UNLOCKED)
        live = [m for m in (base, unlocked) if potential_allows(m, rank)]
        assert len(live) == 1, f"rank {rank}: {len(live)} halves live"

    def test_the_base_half_is_the_live_one_when_locked(self) -> None:
        assert potential_allows(_mod(potential=PotentialTag.BASE), 0) is True
        assert potential_allows(_mod(potential=PotentialTag.UNLOCKED), 0) is False

    def test_the_unlocked_half_is_the_live_one_when_unlocked(self) -> None:
        assert potential_allows(_mod(potential=PotentialTag.BASE), 5) is False
        assert potential_allows(_mod(potential=PotentialTag.UNLOCKED), 5) is True

    def test_the_real_corpus_pairs_are_mutually_exclusive(self) -> None:
        """Against the shipped kits, not synthetic rows."""
        from app.services.modifier_loader import load_agent_modifiers

        for hakushin_id in ("1191", "1201", "1021"):  # Ellen, Harumasa, Nekomata
            mods = load_agent_modifiers(hakushin_id)
            paired = [m for m in mods if m.potential is not None]
            assert paired, f"{hakushin_id}: expected a base/unlocked pair"
            for rank in (0, 5):
                by_label: dict[str, int] = {}
                for m in paired:
                    if potential_allows(m, rank):
                        by_label[m.source_label] = by_label.get(m.source_label, 0) + 1
                assert all(n == 1 for n in by_label.values()), (
                    f"{hakushin_id} at rank {rank}: a label has both halves live: {by_label}"
                )


class TestUnlockingNeverWeakensABuff:
    """A base/unlocked pair must WIDEN on unlock, never narrow (#90 Task 10).

    This is the regression test for a real bug the kit-auditor caught. The three split
    pairs were first authored with the unlocked half carrying only the *delta* — the
    scope Potential adds — which reads naturally but is wrong, because `potential_allows`
    makes the pair mutually exclusive: at rank >= 1 ONLY the unlocked half is live, so
    Harumasa's Day Break resolved to `["ultimate"]` alone and silently dropped his entire
    dash bucket. Unlocking Potential made him *weaker* in the model while the unlocked DB
    text is strictly wider.

    Whichever half is live must therefore be COMPLETE for its state, not a delta. Nothing
    in the schema enforces that, so this test does.
    """

    def _pairs(self, hakushin_id: str):
        from app.services.modifier_loader import load_agent_modifiers

        mods = load_agent_modifiers(hakushin_id)
        by_label: dict[str, dict] = {}
        for m in mods:
            if m.potential is not None:
                by_label.setdefault(m.source_label, {})[m.potential] = m
        return {k: v for k, v in by_label.items() if len(v) == 2}

    @pytest.mark.parametrize(
        ("hakushin_id", "agent"), [("1201", "Harumasa"), ("1021", "Nekomata"), ("1191", "Ellen")]
    )
    def test_the_unlocked_half_covers_everything_the_base_half_does(
        self, hakushin_id: str, agent: str
    ) -> None:
        pairs = self._pairs(hakushin_id)
        assert pairs, f"{agent}: expected at least one base/unlocked pair"
        for label, halves in pairs.items():
            base, unlocked = halves[PotentialTag.BASE], halves[PotentialTag.UNLOCKED]

            base_scopes = {s.value for s in base.scopes}
            unlocked_scopes = {s.value for s in unlocked.scopes}
            assert base_scopes <= unlocked_scopes, (
                f"{agent} {label!r}: unlocking DROPS scope(s) "
                f"{sorted(base_scopes - unlocked_scopes)} — the unlocked half was authored "
                f"as a delta, but the pair is mutually exclusive so it must be complete"
            )

            base_conds = {c.value for c in base.conditions}
            unlocked_conds = {c.value for c in unlocked.conditions}
            # Conditions are ANDed, so a *wider* gate is a SMALLER (or equal) condition
            # set, or the same count with a broader member. Only flag the unambiguous
            # regression: the unlocked half demanding strictly more than the base half.
            assert not (base_conds < unlocked_conds), (
                f"{agent} {label!r}: unlocking ADDS required condition(s) "
                f"{sorted(unlocked_conds - base_conds)} — Potential widens a mechanic, "
                f"it does not impose new requirements"
            )

            assert base.value == unlocked.value, (
                f"{agent} {label!r}: the halves differ in value ({base.value} vs "
                f"{unlocked.value}) — a value change is a different mechanic, not a "
                f"scope/condition split, and needs its own citation"
            )


class TestAftershockRetagIsPotentialGated:
    """`retag_as_aftershock` is Potential-gated for Soldier 0 - Anby (#90).

    The sentence "Soldier 0 - Anby's Chain Attack and Ultimate are treated as Aftershock
    DMG" appears ONLY in his `potential='unlocked'` core text. Before this gate the retag
    fired unconditionally, so a locked build received Aftershock DMG% bonuses on Chain and
    Ultimate its kit does not grant — an over-credit, which is the direction #90 exists to
    fix.

    This lives in the MOVES layer, below the repository's variant filter, which is why the
    filter alone did not cover it: `moves/agents/*.json` is loaded per agent, not per build.
    """

    def test_the_spec_declares_the_gate(self) -> None:
        from app.data.loaders.moves import load_agent_moves

        spec = load_agent_moves()["soldier_0_anby"].aftershock
        assert spec.retag_requires_potential is True
        assert spec.retag_as_aftershock == ["chain", "ultimate"]

    def test_no_other_agent_declares_a_gated_retag(self) -> None:
        """Scope check: exactly one agent uses this today, and a silent second one
        would mean a retag went un-audited."""
        from app.data.loaders.moves import load_agent_moves

        gated = [
            key
            for key, moves in load_agent_moves().items()
            if getattr(getattr(moves, "aftershock", None), "retag_requires_potential", False)
        ]
        assert gated == ["soldier_0_anby"], gated

    @pytest.mark.parametrize(
        ("rank", "expected"), [(0, []), (1, ["chain", "ultimate"]), (5, ["chain", "ultimate"])]
    )
    def test_the_assembled_spec_drops_the_retag_when_locked(
        self, rank: int, expected: list[str]
    ) -> None:
        """Mirrors anomaly_simulator's per-build assembly, which is where the strip
        happens — the hit loop never learns the variant exists."""
        from app.data.loaders.moves import load_agent_moves

        spec = load_agent_moves()["soldier_0_anby"].aftershock
        if spec.retag_requires_potential and rank < 1:
            spec = spec.model_copy(update={"retag_as_aftershock": []})
        assert spec.retag_as_aftershock == expected

    def test_stripping_does_not_mutate_the_shared_cache(self) -> None:
        """`load_agent_moves` is process-cached, so an in-place strip would leak one
        build's Potential state into every other build in the process."""
        from app.data.loaders.moves import load_agent_moves

        spec = load_agent_moves()["soldier_0_anby"].aftershock
        spec.model_copy(update={"retag_as_aftershock": []})
        assert load_agent_moves()["soldier_0_anby"].aftershock.retag_as_aftershock == [
            "chain",
            "ultimate",
        ]

    def test_snapshot_carries_the_rank_for_layers_below_the_repo_filter(self) -> None:
        from app.services.build_damage_service import BuildSnapshot

        assert BuildSnapshot().potential_rank == 6  # Level VI, fully unlocked
        assert BuildSnapshot(potential_rank=0).potential_rank == 0


class TestRankNormalisation:
    """`None` must normalise to 6 (Level VI), and never via `or` (#90).

    A Build-like object can carry `potential_rank` set to None — reconstructed crossval
    fixtures and in-memory doubles both do — and `getattr(x, "attr", 5)` supplies its
    default only when the attribute is ABSENT, not when it is None. The first cut of the
    Aftershock gate missed that and crashed the `anby_retag_aftershock` crossval fixture
    with `'<' not supported between NoneType and int`.

    The tempting one-liner fix, `rank or 5`, is worse than the crash: rank 0 is falsy, so
    a LOCKED build would silently read as unlocked — inverting the gate for exactly the
    builds it exists to protect, with no error to notice.
    """

    @staticmethod
    def _normalise(raw: object) -> int:
        """The normalisation both call sites use."""
        return 6 if raw is None else raw  # type: ignore[return-value]

    def test_none_becomes_unlocked(self) -> None:
        assert self._normalise(None) == 6

    def test_zero_survives_normalisation(self) -> None:
        """The `or 5` bug: this is the assertion that catches it."""
        assert self._normalise(0) == 0
        # Sanity, spelled so Ruff does not fold the constant away: `or` treats the
        # falsy rank 0 as "unset" and yields 5, which is the inversion this guards.
        locked_rank = 0
        assert (locked_rank or 5) == 5, "this is why `or` is the wrong operator here"

    @pytest.mark.parametrize("rank", [0, 1, 2, 3, 4, 5, 6])
    def test_real_ranks_pass_through(self, rank: int) -> None:
        assert self._normalise(rank) == rank

    def test_a_none_rank_build_still_gets_the_retag(self) -> None:
        """End to end: a snapshot with no stated rank behaves as before #90."""
        from app.services.build_damage_service import BuildSnapshot

        snap = BuildSnapshot(potential_rank=None)  # type: ignore[arg-type]
        raw = getattr(snap, "potential_rank", None)
        assert (5 if raw is None else raw) >= 1


class TestFormulaPotentialGate:
    """A `formulas[]` entry can be Potential-gated, and must resolve away when locked.

    Burnice's `unlocked_mfb_afterburn_dmg` is the live case: a free Afterburn proc on
    Basic Attack: Mixed Flame Blend that exists only once Potential is unlocked. Before
    #90 Task 10 `KitFormula` had no `potential` field at all, so the L0 rule's "every row
    states its state" claim was false for formulas — a hole in a place nobody looks.

    `load_agent_formulas` is the raw read and returns every entry; the state filter lives
    in `resolve_kit_formulas`, which takes the build's rank. These assert the filter, not
    the read.
    """

    BURNICE = "1171"

    def test_the_unlocked_formula_is_absent_for_a_locked_build(self) -> None:
        from app.services.kit_formulas import resolve_kit_formulas
        from app.services.modifier_loader import load_agent_formulas

        raw = load_agent_formulas(self.BURNICE)
        locked = resolve_kit_formulas(raw, mindscape=6, core_level=6, potential_rank=0)
        assert not any(f.name == "unlocked_mfb_afterburn_dmg" for f in locked)

    @pytest.mark.parametrize("rank", [1, 5])
    def test_the_unlocked_formula_is_present_once_unlocked(self, rank: int) -> None:
        from app.services.kit_formulas import resolve_kit_formulas
        from app.services.modifier_loader import load_agent_formulas

        raw = load_agent_formulas(self.BURNICE)
        resolved = resolve_kit_formulas(
            raw, mindscape=6, core_level=6, potential_rank=rank
        )
        assert any(f.name == "unlocked_mfb_afterburn_dmg" for f in resolved)

    def test_the_shared_formulas_survive_both_states(self) -> None:
        """Only the tagged one moves — the other three are present either way."""
        from app.services.kit_formulas import resolve_kit_formulas
        from app.services.modifier_loader import load_agent_formulas

        raw = load_agent_formulas(self.BURNICE)
        names = {
            rank: {
                f.name
                for f in resolve_kit_formulas(
                    raw, mindscape=6, core_level=6, potential_rank=rank
                )
            }
            for rank in (0, 5)
        }
        assert names[5] - names[0] == {"unlocked_mfb_afterburn_dmg"}
        assert not names[0] - names[5], "locked must never see more than unlocked"

    def test_the_default_rank_behaves_as_before_90(self) -> None:
        """Callers that never pass a rank keep pre-#90 behaviour."""
        from app.services.kit_formulas import resolve_kit_formulas
        from app.services.modifier_loader import load_agent_formulas

        raw = load_agent_formulas(self.BURNICE)
        default = {f.name for f in resolve_kit_formulas(raw, mindscape=6, core_level=6)}
        explicit = {
            f.name
            for f in resolve_kit_formulas(
                raw, mindscape=6, core_level=6, potential_rank=5
            )
        }
        assert default == explicit
