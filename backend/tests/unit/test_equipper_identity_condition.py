"""The agent-identity equipper condition family (EQUIPPER_IS_PYROIS).

Sol Exuvia (14155) reads "When the equipper is Pyrois" — the first engine passive
gated on agent *identity* rather than specialty/element. EQUIPPER_IS_LUMIFLUX looks
like precedent but is not: it rides Remielle's element string through the generic
``equipper_is_<element>`` injection. Identity rides ``agents.name``, so it needs its
own derivation in every place the specialty/element pair is derived — and each of
those places is pinned here, because the failure mode is a row that is silently
never active (the Astra-core shape, one layer down).
"""

from __future__ import annotations

from app.services.modifiers import ActiveConditions, Condition, Modifier, ModifierSource
from app.services.snapshot_builder import (
    inject_derived_conditions,
    resolve_equipper_conditions,
)


class _Agent:
    def __init__(self, name: str, specialty: str = "attack", element: str = "fire") -> None:
        self.name = name
        self.specialty = specialty
        self.element = element


def _identity_row() -> Modifier:
    return Modifier(
        stat="res_ignore",
        value=1600,
        source=ModifierSource.WENGINE_PASSIVE,
        source_label="Sol Exuvia: Eclipse",
        conditions=(Condition.EQUIPPER_IS_PYROIS,),
    )


def test_the_condition_exists_and_carries_the_name_slug() -> None:
    assert Condition("equipper_is_pyrois") is Condition.EQUIPPER_IS_PYROIS


class TestResolveEquipperConditions:
    def test_matching_name_resolves_the_gate(self) -> None:
        resolved = resolve_equipper_conditions(_identity_row(), "attack", "fire", "Pyrois")
        assert resolved is not None
        assert Condition.EQUIPPER_IS_PYROIS not in resolved.conditions

    def test_wrong_name_drops_the_row(self) -> None:
        """The gate is the whole point: Sol Exuvia on anyone else grants no Eclipse."""
        assert resolve_equipper_conditions(_identity_row(), "attack", "fire", "Ellen") is None

    def test_no_name_context_drops_the_row(self) -> None:
        """Same conservative default as the specialty/element pair."""
        assert resolve_equipper_conditions(_identity_row(), "attack", "fire") is None

    def test_name_is_slugified_before_matching(self) -> None:
        """A future 'Zhu Yuan'-style identity condition must match its DB name."""
        resolved = resolve_equipper_conditions(_identity_row(), "attack", "fire", "PYROIS")
        assert resolved is not None


class TestInjectDerivedConditions:
    def test_pyrois_gets_his_identity_condition(self) -> None:
        active = ActiveConditions(active=set())
        inject_derived_conditions(active, _Agent("Pyrois"))
        assert Condition.EQUIPPER_IS_PYROIS in active.active

    def test_other_agents_do_not(self) -> None:
        active = ActiveConditions(active=set())
        inject_derived_conditions(active, _Agent("Ellen", specialty="attack", element="ice"))
        assert Condition.EQUIPPER_IS_PYROIS not in active.active
        # ...and the generic pair still injects, unchanged.
        assert Condition.EQUIPPER_IS_ATTACK in active.active
        assert Condition.EQUIPPER_IS_ICE in active.active


class TestCollectionTimeResolution:
    """The engine defect the Boisterous Echoes audit found (2026-08-08): nothing on
    the static path injected derived equipper conditions, so an ``equipper_is_*``
    row on the DPS's OWN W-Engine or kit was silently dead. Collection-time
    resolution (the treatment disc sets always had) is the fix; this pins it with
    the live Sol Exuvia kit, whose Eclipse row gates on EQUIPPER_IS_PYROIS."""

    @staticmethod
    def _snap(agent_name: str):
        from types import SimpleNamespace

        from app.services.snapshot_builder import build_snapshot_from_db

        agent = SimpleNamespace(
            hakushin_id="1551" if agent_name == "Pyrois" else "9999",
            name=agent_name,
            base_atk=700,
            base_def=600,
            base_hp=8000,
            atk_growth=0,
            def_growth=0,
            hp_growth=0,
            promotion_stats=None,
            core_stats=None,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=93,
            base_anomaly_mastery=93,
            base_impact=95,
            base_pen_ratio=0,
            base_pen_flat=0,
            base_energy_regen=12000,
            ex_energy_cost=60,
            specialty="attack",
            element="ether",
        )
        build = SimpleNamespace(
            agent=agent,
            agent_level=60,
            w_engine=SimpleNamespace(
                hakushin_id="14155",
                base_atk=48,
                secondary_stat_type="atk_pct",
                secondary_stat_value=1200,
            ),
            w_engine_level=60,
            w_engine_refinement=5,
            discs=[],
            mindscape_level=0,
            core_skill_level=0,
            skill_levels=None,
            stack_counts=None,
            disabled_buffs=None,
        )
        return build_snapshot_from_db(build, agent)

    def test_pyrois_keeps_his_signature_engines_eclipse_row(self) -> None:
        rows = [m for m in self._snap("Pyrois").modifiers if m.stat == "res_ignore"]
        assert rows, "Sol Exuvia's Eclipse row must survive collection for Pyrois"
        assert all(Condition.EQUIPPER_IS_PYROIS not in m.conditions for m in rows)

    def test_anyone_else_drops_it_at_collection(self) -> None:
        """Before the fix this row survived with an unsatisfiable condition —
        indistinguishable in the buff roster from a row that could ever fire."""
        assert not [m for m in self._snap("Ellen").modifiers if m.stat == "res_ignore"]


class TestSimulatorRederivation:
    def test_identity_follows_the_build_being_resolved(self) -> None:
        """The E-F5(a) rule extended to identity: re-deriving equipper conditions
        for a different build must swap the identity condition too."""
        from app.services.anomaly_simulator import _with_equipper_conditions_for
        from app.services.build_damage_service import BuildSnapshot

        pyrois = BuildSnapshot(
            agent_name="Pyrois", agent_specialty="attack", agent_element="fire"
        )
        other = BuildSnapshot(agent_name="Ellen", agent_specialty="attack", agent_element="ice")
        start = ActiveConditions(active={Condition.ALWAYS})

        as_pyrois = _with_equipper_conditions_for(start, pyrois)
        assert Condition.EQUIPPER_IS_PYROIS in as_pyrois.active

        as_other = _with_equipper_conditions_for(as_pyrois, other)
        assert Condition.EQUIPPER_IS_PYROIS not in as_other.active


class TestResolutionPreservesEveryOtherField:
    """`resolve_equipper_conditions` rewrites a row's conditions — and must change
    *nothing else about it*.

    It used to rebuild the Modifier from a hand-listed subset of fields, so every
    field added after that list was written was silently dropped on any row whose
    gate actually resolved: `element_scope`, `scaling_stat`/`scaling_ratio`/
    `excess_threshold`, `atk_scale_ratio`, `flat_addend`, and both mindscape bounds.

    A hand-listed field set is a bug that re-arms itself every time the dataclass
    grows, so the test is written against `dataclasses.fields` rather than against
    today's list — adding a field to `Modifier` with no thought for this function
    fails here instead of silently zeroing a buff two releases later.
    """

    def test_no_field_is_dropped_when_the_gate_resolves(self) -> None:
        from dataclasses import fields

        row = Modifier(
            stat="res_ignore",
            value=2200,
            source=ModifierSource.WENGINE_PASSIVE,
            source_label="Eclipse Effect: Ether RES ignore",
            conditions=(Condition.EQUIPPER_IS_PYROIS, Condition.ENEMY_STUNNED),
            element_scope=("ether",),
            scaling_stat="base_atk",
            scaling_ratio=0.5,
            excess_threshold=100,
            atk_scale_ratio=0.25,
            flat_addend=7,
            min_mindscape=2,
            max_mindscape=6,
            notes={"provenance": "kept"},
        )
        resolved = resolve_equipper_conditions(row, "attack", "ether", "Pyrois")
        assert resolved is not None

        changed = {
            f.name
            for f in fields(Modifier)
            if getattr(resolved, f.name) != getattr(row, f.name)
        }
        assert changed == {"conditions"}, (
            f"resolution altered {sorted(changed - {'conditions'})} as well as the "
            "conditions it was asked to resolve"
        )
        assert resolved.conditions == (Condition.ENEMY_STUNNED,)

    def test_the_live_corpus_row_keeps_its_element_scope(self) -> None:
        """`sol_exuvia[1]` is the one shipped row that both carries an
        `equipper_is_*` gate and sets a dropped field. `res_ignore` is in
        `ELEMENT_SCOPE_HONORED_STATS`, so losing the scope widens an Ether-only
        RES-ignore to every element."""
        from app.services.modifier_loader import load_wengine_modifiers

        scoped = [
            m
            for m in load_wengine_modifiers("14155", refinement=5)
            if m.stat == "res_ignore"
        ]
        assert scoped, "Sol Exuvia must still ship an Ether-scoped RES-ignore row"
        for row in scoped:
            resolved = resolve_equipper_conditions(row, "attack", "ether", "Pyrois")
            assert resolved is not None
            assert resolved.element_scope == row.element_scope == ("ether",)
