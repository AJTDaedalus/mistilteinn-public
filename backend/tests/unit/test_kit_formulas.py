"""Task 21 (C3) — the custom damage formula consumer.

A kit's `formulas[]` block holds **extra damage instances**, not buffs: Ben's M2
fire hit on Special, Miyabi's frostburn break on Basic, Alice's and Jane's M6
scaling off Anomaly Proficiency, Burnice's afterburn. Twenty-one of them across
eighteen kits, every one authored and ZO-cited — and until this task, no code path
read the key at all (D-KV8). Every affected agent's damage was understated.

These tests pin the three things that would let that regress quietly:

* **The grammar is closed and loud.** An unknown op, read target, scope, quantity,
  or scaling stat *raises*. Returning 0 for something we do not understand is the
  exact failure mode the whole validation branch exists to kill, so the tests assert
  on the exception, not on a fallback value.
* **The corpus is executable.** Every one of the 21 authored formulas resolves. This
  is the anti-drift test: it fails the moment someone authors an op the engine lacks.
* **The core-level offset is right.** ZO's `char.core` is 0–6; fairy's
  `Build.core_skill_level` is the 0–5 tier (`ezod_importer`: `clamp(core-1, 0, 5)`).
  The per-core-level tables a formula subscripts carry 7 entries indexed by *ZO's*
  number. Off by one here silently reads one row low at every tier — the kind of bug
  that produces a plausible-but-wrong number, which is worse than a crash.

Sources for the values asserted here (ZO @ 0c9bde8f, read this session):
  Ben     — `customDmg('m2_dmg', cmpGE(char.mindscape, 2,
              prod(own.final.def, percent(dm.m2.dmg=3))))` — 300% DEF, fire, Special.
  Alice   — `customDmg('m6_dmg', {attribute:'physical'}, cmpGE(char.mindscape, 6,
              prod(own.final.anomProf, percent(dm.m6.dmg=33))))` — 3300% AP.
  Miyabi  — `customDmg('core_frostburnBreak_dmg', prod(own.final.atk,
              subscript(char.core, dm.core.dmg=[7.5,8.75,10,11.25,12.5,13.75,15])))`
              — 7 entries, indexed by ZO's 0–6 core.
  Burnice — afterburn: `subscript(core, [1.75..3.5])` + `cmpGE(M1, 1, percent(1.0))`,
              plus a flat 60 anomaly-buildup instance.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.buff_resolver import ActiveConditions
from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    calculate_build_damage,
)
from app.services.kit_formulas import (
    FORMULA_DAMAGE_STATS,
    FORMULA_OPS,
    FORMULA_QUANTITIES,
    FORMULA_READ_TARGETS,
    KitFormula,
    UnknownFormulaOpError,
    evaluate_multiplier,
    resolve_kit_formula,
    resolve_kit_formulas,
    validate_kit_formula,
)
from app.services.modifier_loader import load_agent_formulas
from app.services.modifiers import AttackScope, Condition
from app.services.snapshot_builder import build_snapshot_from_db

MODIFIERS_DIR = Path(__file__).parents[2] / "app" / "data" / "modifiers"
AGENTS_DIR = MODIFIERS_DIR / "agents"

BEN = "1121"
ALICE = "1401"
JANE = "1261"
MIYABI = "1091"
BURNICE = "1171"

# Miyabi's frostburn table, ZO's `dm.core.dmg` × 10000 → basis points.
MIYABI_FROSTBURN_BP = [75000, 87500, 100000, 112500, 125000, 137500, 150000]


# ---------------------------------------------------------------------------
# Fakes — build_snapshot_from_db only reads plain attributes off Build/Agent.
# ---------------------------------------------------------------------------


def _agent(
    hakushin_id: str,
    name: str,
    *,
    specialty: str = "attack",
    element: str = "fire",
    base_atk: int = 700,
    base_def: int = 600,
    base_anomaly_proficiency: int = 93,
) -> SimpleNamespace:
    return SimpleNamespace(
        hakushin_id=hakushin_id,
        name=name,
        base_atk=base_atk,
        base_def=base_def,
        base_hp=8000,
        atk_growth=0,
        def_growth=0,
        hp_growth=0,
        promotion_stats=None,
        core_stats=None,
        base_crit_rate=500,
        base_crit_dmg=5000,
        base_anomaly_proficiency=base_anomaly_proficiency,
        base_anomaly_mastery=93,
        base_impact=95,
        base_pen_ratio=0,
        base_pen_flat=0,
        base_energy_regen=12000,
        ex_energy_cost=60,
        specialty=specialty,
        element=element,
    )


def _build(
    agent: SimpleNamespace,
    *,
    mindscape: int = 0,
    core_skill_level: int = 5,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent=agent,
        agent_level=60,
        w_engine=None,
        w_engine_level=None,
        w_engine_refinement=1,
        discs=[],
        mindscape_level=mindscape,
        core_skill_level=core_skill_level,
        skill_levels=None,
        stack_counts=None,
        disabled_buffs=None,
    )


def _formulas_of(slug: str) -> list[dict]:
    return json.loads((AGENTS_DIR / f"{slug}.json").read_text()).get("formulas", [])


def _by_name(formulas: tuple[KitFormula, ...], name: str) -> KitFormula:
    return next(f for f in formulas if f.name == name)


# ---------------------------------------------------------------------------
# The grammar is closed, and every unknown raises
# ---------------------------------------------------------------------------


class TestGrammar:
    def test_const(self) -> None:
        node = {"op": "const", "value": 5500}
        assert evaluate_multiplier(node, mindscape=0, core_level=6) == 5500

    def test_read_mindscape_and_core_level(self) -> None:
        mc = {"op": "read", "q": "mindscape"}
        core = {"op": "read", "q": "core_level"}
        assert evaluate_multiplier(mc, mindscape=4, core_level=6) == 4
        assert evaluate_multiplier(core, mindscape=0, core_level=3) == 3

    def test_cmp_ge_takes_if_ge_at_or_above_the_threshold(self) -> None:
        node = {
            "op": "cmp_ge",
            "left": {"op": "read", "q": "mindscape"},
            "right": 6,
            "if_ge": 330000,
        }
        assert evaluate_multiplier(node, mindscape=6, core_level=6) == 330000

    def test_cmp_ge_defaults_to_zero_below_the_threshold(self) -> None:
        """No authored entry carries an `if_lt`, so below-threshold must mean nothing."""
        node = {
            "op": "cmp_ge",
            "left": {"op": "read", "q": "mindscape"},
            "right": 6,
            "if_ge": 330000,
        }
        assert evaluate_multiplier(node, mindscape=5, core_level=6) == 0

    def test_subscript_indexes_by_core_level(self) -> None:
        node = {
            "op": "subscript",
            "index": {"op": "read", "q": "core_level"},
            "table": MIYABI_FROSTBURN_BP,
        }
        for core, expected in enumerate(MIYABI_FROSTBURN_BP):
            assert evaluate_multiplier(node, mindscape=0, core_level=core) == expected

    def test_subscript_out_of_range_raises(self) -> None:
        node = {"op": "subscript", "index": {"op": "read", "q": "core_level"}, "table": [1, 2, 3]}
        with pytest.raises(UnknownFormulaOpError, match="outside its 3-entry table"):
            evaluate_multiplier(node, mindscape=0, core_level=6)

    def test_sum_adds_its_args(self) -> None:
        node = {
            "op": "sum",
            "args": [
                {"op": "subscript", "index": {"op": "read", "q": "core_level"}, "table": [10, 20]},
                {"op": "cmp_ge", "left": {"op": "read", "q": "mindscape"}, "right": 1, "if_ge": 5},
            ],
        }
        assert evaluate_multiplier(node, mindscape=1, core_level=1) == 25
        assert evaluate_multiplier(node, mindscape=0, core_level=0) == 10

    def test_unknown_op_raises_rather_than_no_ops(self) -> None:
        with pytest.raises(UnknownFormulaOpError, match="unknown op 'prod'"):
            evaluate_multiplier({"op": "prod", "args": []}, mindscape=6, core_level=6)

    def test_unknown_read_target_raises(self) -> None:
        with pytest.raises(UnknownFormulaOpError, match="unknown state 'ascension'"):
            evaluate_multiplier({"op": "read", "q": "ascension"}, mindscape=6, core_level=6)

    def test_bare_int_is_a_literal(self) -> None:
        assert evaluate_multiplier(30000, mindscape=0, core_level=0) == 30000

    def test_bool_is_not_a_multiplier(self) -> None:
        """bool subclasses int; without the guard `True` would silently mean 1."""
        with pytest.raises(UnknownFormulaOpError, match="is a bool"):
            evaluate_multiplier(True, mindscape=0, core_level=0)


class TestShapeValidation:
    def test_unknown_quantity_raises(self) -> None:
        raw = {"name": "x", "quantity": "healing", "scope": "basic"}
        with pytest.raises(UnknownFormulaOpError, match="unknown quantity 'healing'"):
            resolve_kit_formula(raw, mindscape=6, core_level=6)

    def test_unknown_scope_raises(self) -> None:
        raw = {"name": "x", "quantity": "standard_dmg", "scope": "parry", "multiplier": 1}
        with pytest.raises(UnknownFormulaOpError, match="unknown scope 'parry'"):
            resolve_kit_formula(raw, mindscape=6, core_level=6)

    def test_unknown_scaling_stat_raises(self) -> None:
        raw = {
            "name": "x",
            "quantity": "standard_dmg",
            "scope": "basic",
            "scaling_stat": "impact",
            "multiplier": 1,
        }
        with pytest.raises(UnknownFormulaOpError, match="unknown stat 'impact'"):
            resolve_kit_formula(raw, mindscape=6, core_level=6)

    def test_standard_dmg_without_a_multiplier_raises(self) -> None:
        raw = {"name": "x", "quantity": "standard_dmg", "scope": "basic"}
        with pytest.raises(UnknownFormulaOpError, match="no multiplier"):
            resolve_kit_formula(raw, mindscape=6, core_level=6)

    def test_absent_scaling_stat_means_atk(self) -> None:
        raw = {"name": "x", "quantity": "standard_dmg", "scope": "basic", "multiplier": 100}
        assert resolve_kit_formula(raw, mindscape=6, core_level=6).damage_stat == "atk"

    def test_validate_walks_the_untaken_branch(self) -> None:
        """`_eval` only visits the branch it takes — L0 must still see the other one.

        A bad op hiding in an `if_lt` evaluates fine at M6 and then explodes for the
        one user whose build reaches it. The structural walk is what catches it.
        """
        raw = {
            "name": "x",
            "quantity": "standard_dmg",
            "scope": "basic",
            "multiplier": {
                "op": "cmp_ge",
                "left": {"op": "read", "q": "mindscape"},
                "right": 6,
                "if_ge": 100,
                "if_lt": {"op": "prod", "args": []},
            },
        }
        # Resolving at M6 takes if_ge and never sees the bad op.
        assert resolve_kit_formula(raw, mindscape=6, core_level=6).multiplier == 100
        # The validator does.
        with pytest.raises(UnknownFormulaOpError, match="unknown op 'prod'"):
            validate_kit_formula(raw)

    def test_subscript_valid_at_max_but_out_of_range_at_min_is_caught(self) -> None:
        """A table authored for M1-M6 and indexed by `mindscape - 1` breaks on an M0 build.

        The realistic version of this bug: the author sizes the table to the mindscapes
        that grant the effect and forgets that an M0 build still evaluates the tree.
        `_walk` cannot see it (the structure is fine; only the resolved index is wrong)
        and resolving at max cannot either — index 5 is in range for a 6-entry table.
        Only executing the low end of the domain catches it.
        """
        raw = {
            "name": "x",
            "quantity": "standard_dmg",
            "scope": "basic",
            "multiplier": {
                "op": "subscript",
                "table": [10, 20, 30, 40, 50, 60],
                "index": {"op": "sum", "args": [{"op": "read", "q": "mindscape"}, -1]},
            },
        }
        # Fine at the top of the domain — this is why a single max-only sample passed it.
        assert resolve_kit_formula(raw, mindscape=6, core_level=6).multiplier == 60
        with pytest.raises(UnknownFormulaOpError, match="subscript index -1"):
            validate_kit_formula(raw)


# ---------------------------------------------------------------------------
# The authored corpus must be executable — the anti-drift test
# ---------------------------------------------------------------------------


class TestCorpusIsExecutable:
    def test_every_authored_formula_validates(self) -> None:
        """No kit may author a formula the engine cannot execute (the D-KV8 defect)."""
        for path in sorted(AGENTS_DIR.glob("*.json")):
            kit = json.loads(path.read_text())
            for formula in kit.get("formulas", []):
                validate_kit_formula(formula)  # raises on anything unexecutable

    def test_the_corpus_uses_only_the_documented_grammar(self) -> None:
        """Pins the enumerated grammar (5 ops, 2 read targets) to the actual corpus.

        If this fails, the corpus grew an op — which is fine, but the module docstring,
        the LOG, and this test must all learn about it deliberately.
        """
        ops: set[str] = set()
        reads: set[str] = set()
        quantities: set[str] = set()
        stats: set[str] = set()

        def walk(node: object) -> None:
            if not isinstance(node, dict):
                return
            op = node.get("op")
            if op is not None:
                ops.add(str(op))
            if op == "read":
                reads.add(str(node.get("q")))
            for value in node.values():
                if isinstance(value, dict):
                    walk(value)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)

        total = 0
        for path in sorted(AGENTS_DIR.glob("*.json")):
            for formula in json.loads(path.read_text()).get("formulas", []):
                total += 1
                quantities.add(formula["quantity"])
                if formula.get("scaling_stat"):
                    stats.add(formula["scaling_stat"])
                walk(formula.get("multiplier"))

        # Re-derived 2026-07-25 (Task 17 Batch 7 + accumulated uncommitted
        # curation work): 21 -> 29 -> 28 formulas. koleda.json split its single
        # M6 proc into 3 scope-specific entries (ex_special/chain/ultimate,
        # matching the DB text naming all three triggers) and orphie_magus.json's
        # single entry was re-scoped (still 1) -> 29. soldier_0_anby.json's
        # formulas[] block (m6_additional_dmg) was then found, on independent
        # re-audit, to carry the wrong trigger grain: ZO's cmpGE(mindscape, 6, ...)
        # doesn't model a per-hit proc cadence (it's a static formula graph), but
        # the DB text describes a real 6-instance White-Thunder proc counter that
        # a formulas[]-shaped scope:ex_special entry cannot express without
        # over-crediting 0%-24% of rotation damage depending on the EX:Special
        # ratio. Moved to a second, independent tally on the existing WT-cascade
        # engine (moves/agents/soldier_0_anby.json's aftershock block,
        # wt_vortex_mv_bp/wt_vortex_tally_cap/wt_vortex_requires_mindscape) instead
        # -> 29 - 1 = 28. See docs/LOG_kit_curation.md Task 17 Batch 7 re-audit.
        # Task 17 Batch 8 (2026-07-26): zhu_yuan.json's M6 formula round-tripped
        # (removed for an under-counted bullet total, then re-authored correctly as
        # a sum-of-three-cmp_ge node once the auditor proved the full total is
        # representable) -> net 0. seed.json's M6 formula was found unrepresentable
        # on independent re-audit — even at its corrected 3-beam total, scope='basic'
        # over-credits Seed's other Basic-category moves (Chrysanthemum Wheel Dance,
        # Falling Petals - Downfall) by ~3.6-4.5x, well over the D-KV17 ceiling, with
        # no schema field to scope a formula to one specific move within a category
        # -- removed entirely and escalated -> 28 - 1 = 27. See
        # docs/LOG_kit_curation.md Task 17 Batch 8 entries (Zhu Yuan curator fix
        # round 2; Seed curator fix + re-audit round 3).
        # Task 17 Batch 9 (2026-07-26/27): ben.json's single m2_dmg (fire,
        # scoped [special, ex_special]) failed its Gate-2 audit — Fiscal
        # Fist's Block Counter (Special) is Physical, only Cashflow
        # Counter's (EX Special) is Fire — and was split into two
        # scope-specific rows, m2_dmg_special/physical and
        # m2_dmg_ex_special/fire -> 27 + 1 = 28. See
        # docs/LOG_kit_curation.md "Task 17 Batch 9 — Ben (kit-auditor)".
        # #90 Task 10 (2026-08-09): burnice.json gained a fourth entry,
        # `unlocked_mfb_afterburn_dmg` — the Potential-unlocked-only free Afterburn proc
        # on Basic Attack: Mixed Flame Blend, tagged `potential: "unlocked"` so it is
        # inert for a locked build -> 28 + 1 = 29. Grammar RE-DERIVED, not just
        # recounted: its multiplier is sum(subscript(read core_level, table),
        # cmp_ge(read mindscape, 1)) — every op and read target already in the sets
        # asserted below, so the grammar is unchanged and only the count moved.
        assert total == 29, "the corpus changed size — re-derive the grammar"
        assert ops == {"cmp_ge", "read", "subscript", "sum", "const"}
        assert reads == {"mindscape", "core_level"}
        assert quantities == {"standard_dmg", "anom_buildup"}
        assert stats == {"def", "anomaly_proficiency", "atk"}

        assert ops <= set(FORMULA_OPS)
        assert reads <= FORMULA_READ_TARGETS
        assert quantities <= FORMULA_QUANTITIES
        assert stats <= FORMULA_DAMAGE_STATS

    def test_loader_reads_the_formulas_key(self) -> None:
        # Ben's single m2_dmg (Task 17 Batch 9 Gate-2 audit) split into two
        # scope-specific rows: Fiscal Fist's Block Counter (Special) is
        # physical, Cashflow Counter's (EX Special) is fire.
        assert len(load_agent_formulas(BEN)) == 2
        # 3 -> 4 (#90): the fourth is the Potential-unlocked-only Afterburn proc.
        # `load_agent_formulas` is the RAW read, so it returns all four regardless
        # of Potential state — the state filter lives in `resolve_kit_formulas`,
        # which takes the build's rank.
        assert len(load_agent_formulas(BURNICE)) == 4
        assert load_agent_formulas("nonexistent") == []


# ---------------------------------------------------------------------------
# Mindscape and core-level resolution
# ---------------------------------------------------------------------------


class TestResolution:
    def test_mindscape_gated_formula_is_inert_below_its_gate(self) -> None:
        """Ben's M2 is a 300% DEF hit gated on M2. An M1 build must emit nothing."""
        assert resolve_kit_formulas(_formulas_of("ben"), mindscape=1, core_level=6) == ()

    def test_mindscape_gated_formula_resolves_at_its_gate(self) -> None:
        resolved = resolve_kit_formulas(_formulas_of("ben"), mindscape=2, core_level=6)
        # Two scope-specific rows (Task 17 Batch 9): Special (Fiscal Fist's
        # Block Counter, physical) and EX Special (Cashflow Counter's, fire).
        assert len(resolved) == 2
        by_scope = {r.scope: r for r in resolved}
        assert by_scope[AttackScope.SPECIAL].multiplier == 30000  # 300% DEF
        assert by_scope[AttackScope.SPECIAL].damage_stat == "def"
        assert by_scope[AttackScope.SPECIAL].element == "physical"
        assert by_scope[AttackScope.EX_SPECIAL].multiplier == 30000  # 300% DEF
        assert by_scope[AttackScope.EX_SPECIAL].damage_stat == "def"
        assert by_scope[AttackScope.EX_SPECIAL].element == "fire"

    def test_alice_m6_scales_off_anomaly_proficiency(self) -> None:
        resolved = resolve_kit_formulas(_formulas_of("alice"), mindscape=6, core_level=6)
        assert resolved[0].damage_stat == "anomaly_proficiency"
        assert resolved[0].multiplier == 330000  # 3300% AP

    @pytest.mark.parametrize(("core_level", "expected"), list(enumerate(MIYABI_FROSTBURN_BP)))
    def test_miyabi_frostburn_scales_across_every_core_level(
        self, core_level: int, expected: int
    ) -> None:
        resolved = resolve_kit_formulas(_formulas_of("miyabi"), mindscape=0, core_level=core_level)
        assert resolved[0].multiplier == expected

    def test_burnice_afterburn_sums_core_table_and_m1_bonus(self) -> None:
        at_m0 = _by_name(
            resolve_kit_formulas(_formulas_of("burnice"), mindscape=0, core_level=6),
            "core_afterburn_dmg",
        )
        at_m1 = _by_name(
            resolve_kit_formulas(_formulas_of("burnice"), mindscape=1, core_level=6),
            "core_afterburn_dmg",
        )
        assert at_m0.multiplier == 35000  # 350% ATK at max core
        assert at_m1.multiplier == 45000  # +100% ATK from M1

    def test_burnice_carries_an_anomaly_buildup_instance(self) -> None:
        buildup = _by_name(
            resolve_kit_formulas(_formulas_of("burnice"), mindscape=0, core_level=6),
            "core_afterburn_anomBuildup",
        )
        assert buildup.quantity == "anom_buildup"
        # ZO's literal is 60 in raw AttributeInfliction; fairy's gauge runs x100.
        assert buildup.buildup == 6_000
        assert buildup.multiplier == 0


# ---------------------------------------------------------------------------
# The snapshot carries them, with the right core-level offset
# ---------------------------------------------------------------------------


class TestSnapshotWiring:
    def test_snapshot_carries_resolved_formulas(self) -> None:
        agent = _agent(BEN, "Ben", specialty="defense", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=2), agent)
        assert [f.name for f in snap.kit_formulas] == ["m2_dmg_special", "m2_dmg_ex_special"]
        assert snap.kit_formulas[0].multiplier == 30000
        assert snap.kit_formulas[1].multiplier == 30000

    def test_snapshot_drops_formulas_gated_above_the_build(self) -> None:
        agent = _agent(BEN, "Ben", specialty="defense", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=1), agent)
        assert snap.kit_formulas == ()

    def test_core_skill_level_is_offset_by_one_into_zo_core(self) -> None:
        """fairy's tier 0–5 is ZO's core 1–6 — the tables are indexed by ZO's number.

        `ezod_importer` stores `core_skill_level = clamp(talent.core - 1, 0, 5)`, so the
        snapshot must add the 1 back. Reading the table at the raw tier would understate
        every core level by one row (max core → 137500 instead of 150000).
        """
        agent = _agent(MIYABI, "Miyabi", specialty="anomaly", element="ice")

        at_max = build_snapshot_from_db(_build(agent, core_skill_level=5), agent)
        assert at_max.kit_formulas[0].multiplier == MIYABI_FROSTBURN_BP[6] == 150000

        at_min = build_snapshot_from_db(_build(agent, core_skill_level=0), agent)
        assert at_min.kit_formulas[0].multiplier == MIYABI_FROSTBURN_BP[1] == 87500

    def test_agent_without_formulas_gets_an_empty_tuple(self) -> None:
        agent = _agent("1151", "Lucy", specialty="support", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=0), agent)
        assert snap.kit_formulas == ()


# ---------------------------------------------------------------------------
# The damage calc honours the scaling stat
# ---------------------------------------------------------------------------

_ENEMY = EnemySnapshot(level=60, base_def=953, element_res=0, stun_dmg_mult=10000)
_ALWAYS = ActiveConditions(active={Condition.ALWAYS})


def _snap(**kwargs: object) -> BuildSnapshot:
    base = {
        "agent_base_atk": 800,
        "agent_base_def": 600,
        "agent_anomaly_proficiency": 200,
        "agent_element": "fire",
        "agent_specialty": "attack",
        "agent_level": 60,
    }
    base.update(kwargs)
    return BuildSnapshot(**base)  # type: ignore[arg-type]


class TestDamageStatDispatch:
    def test_def_scaled_instance_uses_def_not_atk(self) -> None:
        snap = _snap(agent_base_atk=800, agent_base_def=600)
        atk_dmg = calculate_build_damage(
            build=snap,
            enemy=_ENEMY,
            multiplier=30000,
            conditions=_ALWAYS,
            attack_scope=AttackScope.SPECIAL,
        )
        def_dmg = calculate_build_damage(
            build=snap,
            enemy=_ENEMY,
            multiplier=30000,
            conditions=_ALWAYS,
            attack_scope=AttackScope.SPECIAL,
            damage_stat="def",
        )
        assert def_dmg.damage.total > 0
        # DEF (600) < ATK (800), so the DEF-scaled instance is strictly smaller —
        # and in the same ratio, since only the scaling stat differs.
        assert def_dmg.damage.effective_atk == def_dmg.stats.defense
        assert atk_dmg.damage.effective_atk == atk_dmg.stats.atk
        assert def_dmg.damage.total < atk_dmg.damage.total

    def test_ap_scaled_instance_uses_anomaly_proficiency(self) -> None:
        snap = _snap(agent_anomaly_proficiency=200)
        res = calculate_build_damage(
            build=snap,
            enemy=_ENEMY,
            multiplier=330000,
            conditions=_ALWAYS,
            attack_scope=AttackScope.ASSIST_FOLLOWUP,
            damage_stat="anomaly_proficiency",
        )
        assert res.damage.total > 0
        assert res.damage.effective_atk == res.stats.anomaly_proficiency == 200

    def test_default_damage_stat_is_atk_and_changes_nothing(self) -> None:
        """The regression guard: every non-formula caller must be untouched."""
        snap = _snap()
        without = calculate_build_damage(
            build=snap,
            enemy=_ENEMY,
            multiplier=10000,
            conditions=_ALWAYS,
            attack_scope=AttackScope.BASIC,
        )
        with_default = calculate_build_damage(
            build=snap,
            enemy=_ENEMY,
            multiplier=10000,
            conditions=_ALWAYS,
            attack_scope=AttackScope.BASIC,
            damage_stat="atk",
            element=None,
        )
        assert without.damage.total == with_default.damage.total
        assert without.damage.effective_atk == with_default.damage.effective_atk


# ---------------------------------------------------------------------------
# End to end: the simulator emits them
#
# This is the acceptance criterion. Everything above can pass while the formula
# still never reaches a damage number — which is precisely how 21 of these shipped
# dead in the first place.
# ---------------------------------------------------------------------------


class _MockAttack:
    def __init__(self, *, element: str = "fire", damage_base: int = 10000) -> None:
        self.name = "hit"
        self.element = element
        self.damage_base = damage_base
        self.damage_growth = 0
        self.energy_gain = 0
        self.anomaly_buildup = 0
        self.skill_key = "Special"


class _MoveSpec:
    def __init__(self, *, scope: str, element: str = "fire", buildup: int = 0) -> None:
        self.duration_s = 1.0
        self.hits = 1
        self.element = element
        self.scope = scope
        self.buildup = buildup


class _AgentMovesSpec:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


def _enemy(**kwargs: int) -> EnemyProfile:
    return EnemyProfile(name="Training Dummy", level=60, defense=953, **kwargs)


def _run(
    snap: BuildSnapshot,
    *,
    scope: str,
    element: str = "fire",
    buildup: int = 0,
    enemy: EnemyProfile | None = None,
):
    agent_key = snap.agent_name.lower()
    return simulate(
        builds={"a": snap},
        steps=[SimulatedAttackStep(agent_id="a", move_name="m", attacks=[_MockAttack()])],
        enemy=enemy if enemy is not None else _enemy(),
        moves_db={
            agent_key: _AgentMovesSpec(
                {"m": _MoveSpec(scope=scope, element=element, buildup=buildup)}
            )
        },
    )


class TestSimulatorEmission:
    def test_ben_m2_produces_damage_on_a_special(self) -> None:
        agent = _agent(BEN, "Ben", specialty="defense", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=2), agent)

        result = _run(snap, scope="special")
        emitted = [e for e in result.events if e.kind == "kit_formula"]

        assert len(emitted) == 1
        assert emitted[0].detail["formula_name"] == "m2_dmg_special"
        assert emitted[0].detail["damage_stat"] == "def"
        assert emitted[0].damage > 0
        assert result.totals["kit_formula"] == emitted[0].damage
        assert result.totals["total"] == result.totals["standard"] + emitted[0].damage

    def test_ben_m2_stays_silent_below_m2(self) -> None:
        agent = _agent(BEN, "Ben", specialty="defense", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=1), agent)

        result = _run(snap, scope="special")

        assert [e for e in result.events if e.kind == "kit_formula"] == []
        assert result.totals["kit_formula"] == 0

    def test_a_formula_only_fires_on_its_own_scope(self) -> None:
        """Ben's M2 is a Special instance. A Basic must not trigger it."""
        agent = _agent(BEN, "Ben", specialty="defense", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=2), agent)

        result = _run(snap, scope="basic")

        assert [e for e in result.events if e.kind == "kit_formula"] == []

    def test_alice_m6_scales_off_ap_end_to_end(self) -> None:
        agent = _agent(ALICE, "Alice", specialty="anomaly", element="physical")
        snap = build_snapshot_from_db(_build(agent, mindscape=6), agent)

        result = _run(snap, scope="assist_followup", element="physical")
        emitted = [e for e in result.events if e.kind == "kit_formula"]

        assert len(emitted) == 1
        assert emitted[0].detail["damage_stat"] == "anomaly_proficiency"
        assert emitted[0].detail["effective_atk"] == snap.agent_anomaly_proficiency
        assert emitted[0].damage > 0

    def test_a_kit_with_no_formulas_emits_nothing(self) -> None:
        """The regression guard: 36 of the 54 kits have no formulas and must not change."""
        agent = _agent(JANE, "Jane", specialty="anomaly", element="physical")
        snap = build_snapshot_from_db(_build(agent, mindscape=0), agent)

        result = _run(snap, scope="assist_followup", element="physical")

        assert [e for e in result.events if e.kind == "kit_formula"] == []

    def test_burnice_buildup_formula_adds_gauge_to_the_step(self) -> None:
        """The `anom_buildup` instance folds into the move's gauge before the loop runs.

        Folding it into the move's buildup total (rather than emitting a second gauge
        path) is what makes it flow through `calculate_buildup`'s bonuses, the per-agent
        gauge contributions, and the anomaly-trigger check for free. So the observable
        is the trigger.

        The capacity is chosen to pin the formula's **magnitude**, not just its presence.
        A fire capacity of 50 puts the threshold at 5 000 gauge; this build's Anomaly
        Mastery is 93, so the step applies (50 + 6 000) x 93/100 = 5 626 and crosses.
        The move's own 50 alone applies 46, and ZO's bare literal would apply
        (50 + 60) x 93/100 = 102 — both two orders of magnitude short, so a regression
        to ZO's scale fails here rather than passing quietly.
        """
        agent = _agent(BURNICE, "Burnice", specialty="anomaly", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=0), agent)
        enemy = _enemy(anomaly_capacity_fire=50)

        assert any(f.quantity == "anom_buildup" for f in snap.kit_formulas)

        with_formula = _run(snap, scope="assist_followup", buildup=50, enemy=enemy)
        without_formula = _run(
            replace(snap, kit_formulas=()), scope="assist_followup", buildup=50, enemy=enemy
        )

        assert _anomalies(without_formula) == 0
        assert _anomalies(with_formula) == 1

    def test_burnice_buildup_formula_is_on_the_db_gauge_scale(self) -> None:
        """Guards the ZO->fairy x100 conversion the kit JSON documents.

        `attacks.anomaly_buildup` and `anomaly_capacity_* * 100` are the same scale, and
        a kit formula's gauge value must join them there. ZO's own literal (60) is two
        orders of magnitude off, and nothing else in the harness checks it today —
        L1 does not reach `formulas[]` (docs/DESIGN_kit_accuracy_gate.md Finding 3).
        """
        agent = _agent(BURNICE, "Burnice", specialty="anomaly", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=0), agent)

        gauge = next(f for f in snap.kit_formulas if f.quantity == "anom_buildup")

        assert gauge.buildup == 6_000, (
            "afterburn gauge must be ZO's 60 x100; a bare 60 is 0.017% of a boss "
            "gauge instead of 1.7%"
        )

    def test_cross_element_buildup_formula_is_skipped_and_warned(self) -> None:
        """A gauge instance of a different element than its move would need its own aura.

        Nothing in the corpus does this today; the guard exists so that when a kit
        author writes one, it surfaces as a warning rather than silently landing in the
        wrong element's gauge.
        """
        agent = _agent(BURNICE, "Burnice", specialty="anomaly", element="fire")
        snap = build_snapshot_from_db(_build(agent, mindscape=0), agent)
        cross = tuple(
            replace(f, element="ice") if f.quantity == "anom_buildup" else f
            for f in snap.kit_formulas
        )

        result = _run(replace(snap, kit_formulas=cross), scope="assist_followup", buildup=50)

        assert any("cross-element kit buildup is not modelled" in w for w in result.warnings)


def _anomalies(result) -> int:
    return sum(1 for e in result.events if e.kind == "anomaly")
