"""Unit tests for `validate_kits` L5 — sequential plausibility (Task 25).

L5 flags a move declared `sequential` whose DB rows do not look like a press chain. It
**flags; it never classifies** — telling a rider from a variant from a real press needs
the skill text and nanoka's input notation, i.e. a human with sources. A tool that decided
for itself would be `generate_additional_overrides.py`, which this branch just retired for
exactly that.

Two skip contracts matter as much as the signals, and both are the `ex_energy_cost`
lesson (`DESIGN_sequential_variant.md` §5.4):

1. **no DB** — CI has no Postgres and runs `--gate`, so L5 must return no findings and set
   its status flag false, exactly as L4 does;
2. **all-NULL `param_name`** — a DB migrated but never re-seeded. Reading that as "no
   variant labels found, therefore clean" is the failure mode. All-NULL is *cannot check*.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.audit_agent_data_binding import DatabaseNotSeededError
from scripts.validate_kits import (
    L0_POTENTIAL_STATUS,
    L4_STATUS,
    L5_CODES,
    L5_STATUS,
    LEVELS,
    LR_STATUS,
    _agent_stem,
    _l5_signals,
    _SeqRow,
    _unrunnable_waiver_codes,
    check_l5,
    main,
    unrunnable_levels,
)


def _row(
    hit_index: int,
    param_name: str | None = None,
    *,
    damage_base: int = 1000,
    damage_growth: int = 100,
    stun_base: int = 500,
    anomaly_buildup: int = 400,
) -> _SeqRow:
    return _SeqRow(
        hit_index=hit_index,
        param_name=param_name,
        damage_base=damage_base,
        damage_growth=damage_growth,
        stun_base=stun_base,
        anomaly_buildup=anomaly_buildup,
    )


def _codes(rows: list[_SeqRow]) -> set[str]:
    return {code for code, _ in _l5_signals(rows)}


class TestCleanChainIsSilent:
    def test_anby_turbo_volt_shape(self) -> None:
        """A real 4-press chain. The live case this is modelled on is Anby's Turbo Volt."""
        rows = [
            _row(0, "1st-Hit DMG Multiplier", stun_base=1560, anomaly_buildup=0),
            _row(1, "2nd-Hit DMG Multiplier", stun_base=2870, anomaly_buildup=0),
            _row(2, "3rd-Hit DMG Multiplier", stun_base=8960, anomaly_buildup=0),
            _row(3, "4th-Hit DMG Multiplier", stun_base=18740, anomaly_buildup=17247),
        ]
        assert _l5_signals(rows) == []

    def test_zero_gauge_alone_is_not_a_rider(self) -> None:
        """Rows 0-2 above carry no gauge but real daze — a normal opening chain.

        The rider signature deliberately requires **both** to be zero. Flagging on gauge
        alone would fire on a large fraction of the roster and teach people to ignore L5.
        """
        rows = [
            _row(0, "1st-Hit", anomaly_buildup=0),
            _row(1, "2nd-Hit", anomaly_buildup=0),
        ]
        assert "seq_rider_row" not in _codes(rows)


class TestSignals:
    def test_rider_row(self) -> None:
        """Promeia's `Cloak Slash DMG Per Second` / Soldier 11's `5th-Hit Additional`."""
        rows = [
            _row(0, "1st-Hit DMG Multiplier"),
            _row(1, "2nd-Hit DMG Multiplier"),
            _row(2, "Cloak Slash DMG Per Second Multiplier", stun_base=0, anomaly_buildup=0),
        ]
        assert "seq_rider_row" in _codes(rows)

    def test_first_row_never_counts_as_a_rider(self) -> None:
        """A move whose *opening* row lands nothing is a different problem, not this one."""
        rows = [
            _row(0, "1st-Hit DMG Multiplier", stun_base=0, anomaly_buildup=0),
            _row(1, "2nd-Hit DMG Multiplier"),
        ]
        assert "seq_rider_row" not in _codes(rows)

    def test_duplicate_param_name(self) -> None:
        """Miyabi's Hisetsu: one nanoka param expanded into two multipliers."""
        rows = [
            _row(0, "Slash DMG Multiplier", damage_base=15740),
            _row(1, "Slash DMG Multiplier", damage_base=23600),
        ]
        assert "seq_duplicate_param_name" in _codes(rows)

    @pytest.mark.parametrize(
        "label",
        [
            "Enhanced Basic Attack 5th-Hit DMG Multiplier",
            "3rd-Hit (ALT) DMG Multiplier",
            "3rd-Hit Min DMG Multiplier",
            "3rd-Hit DMG Multiplier (Coordinated)",
            "Charge Level Three Attack DMG Multiplier",
            "Level-2 Charged Attack DMG Multiplier",
            "Two-Staged Charged Attack DMG Multiplier",
        ],
    )
    def test_variant_pattern_labels(self, label: str) -> None:
        rows = [_row(0, "1st-Hit DMG Multiplier"), _row(1, label)]
        assert "seq_variant_label" in _codes(rows)

    def test_qualified_duplicate(self) -> None:
        """Lighter's `(Morale Burst)` — the general form, needing no named state.

        A parenthesised qualifier whose stem is itself another row's label is one press in
        two states. This is what catches states nobody enumerated in advance.
        """
        rows = [
            _row(0, "5th-Hit Startup DMG Multiplier"),
            _row(1, "5th-Hit Startup DMG Multiplier (Morale Burst)"),
        ]
        assert "seq_qualified_duplicate" in _codes(rows)

    def test_qualifier_without_a_matching_stem_is_not_flagged_as_such(self) -> None:
        """`X (Y)` with no plain `X` row is not a state pair, so this signal stays quiet."""
        rows = [
            _row(0, "1st-Hit DMG Multiplier"),
            _row(1, "Something Else DMG Multiplier (Some State)"),
        ]
        assert "seq_qualified_duplicate" not in _codes(rows)

    def test_leading_qualifier_suffix_form(self) -> None:
        """Hugo's Quartet: `Shot` sits inside `Charged Shot`, no parentheses anywhere.

        Signal 5's shape without the punctuation. This is why both of Hugo's shot-form
        moves were invisible to L5 while being exactly the one-press-in-two-forms case it
        exists to find.
        """
        rows = [
            _row(0, "1st-Hit DMG Multiplier"),
            _row(1, "Shot DMG Multiplier"),
            _row(2, "Charged Shot DMG Multiplier"),
        ]
        assert "seq_leading_qualifier" in _codes(rows)

    def test_leading_qualifier_shared_tail_form(self) -> None:
        """Billy's stance axis: neither label contains the other, but the tail is shared."""
        rows = [
            _row(0, "Standing Fire DMG Multiplier"),
            _row(1, "Crouching Fire DMG Multiplier"),
        ]
        assert "seq_leading_qualifier" in _codes(rows)

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("1st-Hit Charged Attack DMG Multiplier", "2nd-Hit Charged Attack DMG Multiplier"),
            ("First Slash DMG Multiplier", "Second Slash DMG Multiplier"),
        ],
    )
    def test_ordinal_heads_are_a_chain_not_a_qualifier(self, a: str, b: str) -> None:
        """The guard that keeps this signal from firing on every genuine press chain.

        Lycaon's Moon Hunter is five rows of `Nth-Hit Charged Attack DMG Multiplier`; the
        words that *differ* are ordinals, which is what a chain looks like. Testing the
        shared tail instead of the differing head flags Lycaon and Manato — verified
        against the live corpus before this guard was written.
        """
        assert "seq_leading_qualifier" not in _codes([_row(0, a), _row(1, b)])

    def test_ordinal_guard_does_not_swallow_a_qualified_ordinal_row(self) -> None:
        """Soldier 11 — #89's original specimen — must still fire.

        Here the ordinal is in the *shared* part (`5th-Hit DMG Multiplier`) and the
        differing head is `Enhanced Basic Attack`. The guard is about the head only.
        """
        rows = [
            _row(0, "5th-Hit DMG Multiplier"),
            _row(1, "Enhanced Basic Attack 5th-Hit DMG Multiplier"),
        ]
        assert "seq_leading_qualifier" in _codes(rows)

    def test_generic_tail_is_not_a_shared_stem(self) -> None:
        """Yixuan's bare `DMG Multiplier` row would otherwise pair with every other row."""
        rows = [
            _row(0, "DMG Multiplier"),
            _row(1, "EX Special Attack: Qingming Eruption - Break Total DMG Multiplier"),
        ]
        assert "seq_leading_qualifier" not in _codes(rows)

    def test_identical_rows(self) -> None:
        """Soldier 11: hit_index 4 and 5 are the same four numbers — a re-statement."""
        rows = [
            _row(0, "5th-Hit DMG Multiplier", damage_base=44170, stun_base=14530),
            _row(1, "Enhanced 5th-Hit DMG Multiplier", damage_base=44170, stun_base=14530),
        ]
        assert "seq_identical_rows" in _codes(rows)

    def test_one_move_can_raise_several_signals(self) -> None:
        """Soldier 11's Fire Suppression raises three at once, and should."""
        rows = [
            _row(0, "1st-Hit DMG Multiplier"),
            _row(1, "5th-Hit DMG Multiplier", damage_base=44170, stun_base=14530),
            _row(
                2,
                "Enhanced Basic Attack 5th-Hit DMG Multiplier",
                damage_base=44170,
                stun_base=14530,
            ),
            _row(
                3,
                "Enhanced Basic Attack 5th-Hit Additional DMG Multiplier",
                stun_base=0,
                anomaly_buildup=0,
            ),
        ]
        assert _codes(rows) >= {"seq_rider_row", "seq_variant_label", "seq_identical_rows"}


class TestNullParamNameIsCannotCheck:
    def test_unlabelled_rows_raise_no_label_signals(self) -> None:
        """With no labels there is nothing to read; the numeric signals still work."""
        rows = [_row(0, None), _row(1, None)]
        codes = _codes(rows)
        assert "seq_duplicate_param_name" not in codes
        assert "seq_variant_label" not in codes
        assert "seq_qualified_duplicate" not in codes

    def test_check_l5_skips_when_param_name_is_null_everywhere(self) -> None:
        """A migrated-but-not-re-seeded DB must read as *cannot check*, not as clean."""
        rows = {("Anby", "Basic Attack: Turbo Volt"): [_row(0, None), _row(1, None)]}
        with patch("scripts.validate_kits._load_sequential_rows") as loader:
            loader.return_value = rows
            with patch("scripts.validate_kits.asyncio.run", return_value=rows):
                findings = check_l5([])
        assert findings == []
        assert L5_STATUS["param_name_populated"] is False

    def test_check_l5_runs_when_some_rows_are_labelled(self) -> None:
        """Isolated NULLs are legitimate — a synthetic variant row has no nanoka param."""
        rows = {
            ("Promeia", "Basic Attack: Sweeping Edge"): [
                _row(0, "1st-Hit DMG Multiplier"),
                _row(1, None, stun_base=0, anomaly_buildup=0),
            ]
        }
        with patch("scripts.validate_kits.asyncio.run", return_value=rows):
            findings = check_l5([])
        assert L5_STATUS["param_name_populated"] is True
        assert [f.code for f in findings] == ["seq_rider_row"]


class TestNoDbSkipsCleanly:
    def test_skips_and_flags_status(self) -> None:
        """CI has no Postgres and runs `--gate`; L5 must not fail it."""
        with patch(
            "scripts.validate_kits.asyncio.run",
            side_effect=DatabaseNotSeededError("DB has no agents"),
        ):
            findings = check_l5([])
        assert findings == []
        assert L5_STATUS["db_reachable"] is False

    def test_unexpected_db_error_also_skips(self) -> None:
        """Connection refused is the same situation as an empty DB, from CI's point of view."""
        with patch("scripts.validate_kits.asyncio.run", side_effect=OSError("connection refused")):
            findings = check_l5([])
        assert findings == []
        assert L5_STATUS["db_reachable"] is False


class TestFindingShape:
    def test_finding_is_addressed_to_the_agent_file(self) -> None:
        rows = {
            ("Soldier 0 - Anby", "Basic Attack: Penetrating Shock"): [
                _row(0, "1st-Hit DMG Multiplier", damage_base=3270),
                _row(1, "3rd-Hit (ALT) DMG Multiplier", damage_base=10010),
            ]
        }
        with patch("scripts.validate_kits.asyncio.run", return_value=rows):
            findings = check_l5([])
        assert len(findings) == 1
        f = findings[0]
        assert f.level == "L5"
        assert f.source_file == "soldier_0_anby.json"
        assert f.source_name == "Soldier 0 - Anby"
        assert f.label == "Basic Attack: Penetrating Shock"
        assert f.key == "seq_variant_label|soldier_0_anby.json|0"

    @pytest.mark.parametrize(
        ("agent", "stem"),
        [
            ("Soldier 0 - Anby", "soldier_0_anby"),
            ("Astra Yao", "astra_yao"),
            ("Ye Shunguang", "ye_shunguang"),
            ("Anby", "anby"),
        ],
    )
    def test_agent_stem(self, agent: str, stem: str) -> None:
        assert _agent_stem(agent) == stem


class TestMainDoesNotCallUnrunnableWaiversStale:
    """`main()` must apply the same skip contract the level itself does.

    This is the gap that shipped: `L5_CODES` existed, and
    `test_validate_kits_l0.py::test_no_stale_waivers` computed the exclusion — but
    `main()` did not, so it only ever asked whether **L4** could run. The two levels
    fail independently: L4 needs the DB, L5 needs the DB *and* a re-seed. A DB that
    was migrated but never re-seeded therefore left L4 reachable, `all_levels_ran`
    true and L5 empty, so every L5 waiver reported ``STALE WAIVER (no longer fires,
    remove it)`` — telling the operator to delete the ledger issue #89 depends on,
    when the real remedy was `python -m scripts.seed_db`.

    Asserting on `main()` rather than on a re-implementation of its rule is the whole
    point of these two tests.
    """

    @staticmethod
    def _stale_from_main() -> list[str]:
        """Run `main() --json` with L4/L5 stubbed out, and return its stale-waiver list.

        The stubs go into ``LEVELS``, not onto the module attributes: ``LEVELS`` binds
        the function objects at import, so ``patch("scripts.validate_kits.check_l5")``
        leaves the dispatch table pointing at the real function — which then reaches the
        developer's seeded DB, fires every L5 waiver, and makes this test pass whether or
        not the fix is present. Patching the table keeps the unit lane DB-free too.
        """
        import io
        import json as _json
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with (
            patch.dict(
                "scripts.validate_kits.LEVELS",
                {
                    "l4": lambda _kits: [],
                    "l5": lambda _kits: [],
                    "lr": lambda _kits: [],
                    # LU and LC join the same list for the same reason LR is on it: both
                    # are legitimately red on a seeded box while #180's triage is open
                    # (untriaged upstream rows, and the kits LU's `undetermined` entries
                    # cap), and neither has anything to do with the DB-skip semantics under
                    # test here. Stubbing them isolates `--require-db`'s contribution
                    # instead of coupling this test to the corpus being globally clean.
                    "lu": lambda _kits: [],
                    "lc": lambda _kits: [],
                },
            ),
            patch("sys.argv", ["validate_kits", "--json"]),
            redirect_stdout(buf),
        ):
            main()
        return _json.loads(buf.getvalue())["stale_waivers"]

    def test_migrated_but_not_reseeded_does_not_orphan_l5_waivers(self) -> None:
        """L4 reachable + `param_name` all-NULL: the state a migration-only deploy leaves."""
        with (
            patch.dict(L4_STATUS, {"db_reachable": True}),
            patch.dict(L5_STATUS, {"db_reachable": True, "param_name_populated": False}),
        ):
            stale = self._stale_from_main()
        assert not [k for k in stale if k.split("|", 1)[0] in L5_CODES], (
            "L5 could not check, so its waivers must not be called stale"
        )

    def test_l0_l1_l2_staleness_still_enforced_without_a_db(self) -> None:
        """The narrowing must not become a blanket amnesty.

        Previously a DB-less run switched the stale check off entirely, so a stale
        L0/L1/L2 waiver was invisible in precisely the CI lane meant to catch it.
        """
        bogus = "sequential_hits_mismatch|__nonexistent__.json|0"
        with (
            patch.dict(L4_STATUS, {"db_reachable": False}),
            patch.dict(L5_STATUS, {"db_reachable": False, "param_name_populated": False}),
            patch(
                "scripts.validate_kits.load_waivers",
                return_value={bogus: {"class": "branch_debt", "retire_when": "never"}},
            ),
        ):
            stale = self._stale_from_main()
        assert bogus in stale


class TestRequireDbTurnsASkipIntoAFailure:
    """`--require-db` is the condition that made moving L4/L5 out of CI safe (#114).

    CI no longer dispatches L4/L5 — on a runner with no Postgres they could only skip,
    and a skip is indistinguishable from a pass. The agent review pass owns them
    instead. But relocating a gate does not fix it: if the reviewer's DB is unseeded or
    stale, the levels skip there too and the run still exits 0, reproducing the exact
    hole one machine to the left. `--require-db` closes it by making "could not check"
    a hard failure.
    """

    @staticmethod
    def _run(argv: list[str]) -> int:
        """Run `main()` with L4/L5 stubbed out of the dispatch table, return its exit code.

        Stubs go into ``LEVELS`` rather than onto module attributes, for the reason
        ``TestMainDoesNotCallUnrunnableWaiversStale._stale_from_main`` documents: the
        table binds the function objects at import, so patching the names would leave
        the real functions running against a developer's seeded DB.
        """
        import io
        from contextlib import redirect_stderr, redirect_stdout

        with (
            patch.dict(
                "scripts.validate_kits.LEVELS",
                {
                    "l4": lambda _kits: [],
                    "l5": lambda _kits: [],
                    "lr": lambda _kits: [],
                    # LU and LC join for LR's reason: both are legitimately red on a
                    # seeded box while #180's triage is open, and neither bears on the
                    # DB-skip semantics under test.
                    "lu": lambda _kits: [],
                    "lc": lambda _kits: [],
                    # LCH for the same reason again: an era exemption awaiting owner
                    # authorization is legitimately red on a seeded box (Task 19b), and
                    # like LR it is invisible on a DB-less runner because the level
                    # skips there. Without this stub the test passes or fails according
                    # to whether the developer's Postgres happens to be up, which is
                    # precisely the environment-dependence it exists to remove.
                    "lch": lambda _kits: [],
                },
            ),
            patch("sys.argv", ["validate_kits", *argv]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            return main()

    def test_unreachable_db_fails_the_run_under_require_db(self) -> None:
        with (
            patch.dict(L4_STATUS, {"db_reachable": False}),
            patch.dict(L5_STATUS, {"db_reachable": False, "param_name_populated": False}),
            patch.dict(LR_STATUS, {"db_reachable": False}),
        ):
            assert self._run(["--gate", "--require-db"]) == 1

    def test_migrated_but_not_reseeded_also_fails_under_require_db(self) -> None:
        """L4 reachable, `param_name` all-NULL — L5 alone cannot check, and that is enough."""
        with (
            patch.dict(L4_STATUS, {"db_reachable": True}),
            patch.dict(L5_STATUS, {"db_reachable": True, "param_name_populated": False}),
            patch.dict(LR_STATUS, {"db_reachable": True}),
        ):
            assert self._run(["--gate", "--require-db"]) == 1

    def test_without_the_flag_a_skip_still_passes(self) -> None:
        """The advisory behaviour CI relies on is unchanged — this is opt-in."""
        with (
            patch.dict(L4_STATUS, {"db_reachable": False}),
            patch.dict(L5_STATUS, {"db_reachable": False, "param_name_populated": False}),
            patch.dict(LR_STATUS, {"db_reachable": False}),
        ):
            assert self._run(["--gate"]) == 0

    def test_the_flag_changes_nothing_when_both_levels_ran(self) -> None:
        """The flag must only ever add the "could not check" failure, never another.

        Asserting the exit code is *unchanged by the flag* rather than asserting it is
        0: the stubs report no L4/L5 findings while the status dicts claim both levels
        ran, so their real waivers are legitimately stale and the run fails on that —
        correctly, and for a reason that has nothing to do with `--require-db`. Pinning
        equality isolates the flag's contribution without having to construct a
        globally clean run.
        """
        with (
            patch.dict(L4_STATUS, {"db_reachable": True}),
            patch.dict(L5_STATUS, {"db_reachable": True, "param_name_populated": True}),
        ):
            assert self._run(["--gate", "--require-db"]) == self._run(["--gate"])

    def test_the_failure_names_the_levels_and_the_remedy(self) -> None:
        """A gate that fails without saying how to satisfy it gets bypassed."""
        import io
        from contextlib import redirect_stderr, redirect_stdout

        err = io.StringIO()
        with (
            patch.dict(L4_STATUS, {"db_reachable": False}),
            patch.dict(L5_STATUS, {"db_reachable": False, "param_name_populated": False}),
            patch.dict(
                "scripts.validate_kits.LEVELS",
                {
                    "l4": lambda _kits: [],
                    "l5": lambda _kits: [],
                    "lr": lambda _kits: [],
                    # LU and LC join for LR's reason: both are legitimately red on a
                    # seeded box while #180's triage is open, and neither bears on the
                    # DB-skip semantics under test.
                    "lu": lambda _kits: [],
                    "lc": lambda _kits: [],
                },
            ),
            patch("sys.argv", ["validate_kits", "--gate", "--require-db"]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
        ):
            main()

        message = err.getvalue()
        assert "L4" in message
        assert "L5" in message
        assert "seed_db" in message

    def test_unrunnable_waivers_are_still_not_called_stale(self) -> None:
        """`--require-db` must not resurrect the misleading advice 96d8f3a removed.

        A failing run tells the operator to seed the DB. It must not *also* tell them
        to delete the #89 ledger, which is what reporting L5's waivers as stale would
        say — and that ledger is precisely what a re-seed makes checkable again.
        """
        import io
        import json as _json
        from contextlib import redirect_stderr, redirect_stdout

        buf = io.StringIO()
        with (
            patch.dict(L4_STATUS, {"db_reachable": False}),
            patch.dict(L5_STATUS, {"db_reachable": False, "param_name_populated": False}),
            patch.dict(
                "scripts.validate_kits.LEVELS",
                {
                    "l4": lambda _kits: [],
                    "l5": lambda _kits: [],
                    "lr": lambda _kits: [],
                    # LU and LC join for LR's reason: both are legitimately red on a
                    # seeded box while #180's triage is open, and neither bears on the
                    # DB-skip semantics under test.
                    "lu": lambda _kits: [],
                    "lc": lambda _kits: [],
                },
            ),
            patch("sys.argv", ["validate_kits", "--json", "--require-db"]),
            redirect_stdout(buf),
            redirect_stderr(io.StringIO()),
        ):
            main()

        stale = _json.loads(buf.getvalue())["stale_waivers"]
        assert not [k for k in stale if k.split("|", 1)[0] in L5_CODES]

    @pytest.mark.parametrize(
        ("l4_ok", "l5_reachable", "l5_seeded"),
        [
            (True, True, True),
            (False, True, True),
            (True, False, False),
            (True, True, False),
            (False, False, False),
        ],
    )
    def test_the_exemption_is_empty_exactly_when_require_db_would_pass(
        self, l4_ok: bool, l5_reachable: bool, l5_seeded: bool
    ) -> None:
        """The equivalence `--require-db` leans on, pinned so it cannot drift.

        The PR that added the flag argued that the `_unrunnable_waiver_codes`
        exemption need not be switched off under it, because a *passing*
        `--require-db` run is by definition one where every requested level ran, so
        the exemption is empty in it and staleness is fully enforced anyway. That
        argument is only true while the two functions agree on what "could not
        check" means. Assert the biconditional directly rather than trusting two
        copies of the same two conditions to stay in step.
        """
        levels = sorted(LEVELS)
        with (
            patch.dict(L4_STATUS, {"db_reachable": l4_ok}),
            patch.dict(
                L5_STATUS,
                {"db_reachable": l5_reachable, "param_name_populated": l5_seeded},
            ),
        ):
            would_pass = not unrunnable_levels(levels)
            exemption_empty = not _unrunnable_waiver_codes(levels)

        assert would_pass == exemption_empty

    def test_a_narrowed_level_set_exempts_nothing_it_did_not_request(self) -> None:
        """`--level l0` must not exempt L4/L5 codes it never asked to run.

        Same biconditional at the other end: neither function may key off the
        status dicts alone, or a DB-less `--level l0` run would silently carry an
        exemption for levels that were not part of the request.
        """
        with (
            patch.dict(L4_STATUS, {"db_reachable": False}),
            patch.dict(L5_STATUS, {"db_reachable": False, "param_name_populated": False}),
            # L0 gained a conditionally-DB-backed sub-check (#90 Track 2, Rule 8c's ramp
            # index), so it is pinned to its "nothing bound, nothing skipped" default
            # here for the same reason L4/L5 are pinned: this test is about the LEVEL SET
            # not leaking, and any status left set by an earlier check_l0 run in the same
            # process would otherwise decide the assertion.
            patch.dict(
                L0_POTENTIAL_STATUS, {"ramps_available": True, "bound_rows_seen": False}
            ),
        ):
            assert unrunnable_levels(["l0"]) == []
            assert _unrunnable_waiver_codes(["l0"]) == set()
