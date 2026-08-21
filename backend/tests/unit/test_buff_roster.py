"""Unit tests for the buff-roster pivot (buff_roster.py)."""

from __future__ import annotations

from collections import defaultdict

from app.services.buff_resolver import resolve_modifiers
from app.services.buff_roster import pivot_buff_roster
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _mod(
    stat: str,
    value: int,
    *,
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,),
    source: ModifierSource = ModifierSource.CORE_SKILL,
    source_label: str = "Core F",
    scaling_stat: str | None = None,
    notes: str | None = None,
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=source_label,
        target=ModifierTarget.SELF,
        conditions=conditions,
        scaling_stat=scaling_stat,
        notes=notes,
    )


def _representative_mods() -> list[Modifier]:
    return [
        _mod("atk_pct", 1000, source_label="Core F"),
        _mod("crit_rate", 2400, source_label="M1"),
        _mod("dmg_bonus", 3000, source_label="Disc 4pc"),
        _mod("res_reduction", 1500, source_label="Support debuff"),
        _mod("vulnerability", 2000, source_label="Team debuff"),
    ]


class TestPivotBuffRoster:
    def test_round_trips_stat_bonuses(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)

        by_stat: dict[str, int] = defaultdict(int)
        for entry in roster:
            by_stat[entry.stat] += entry.value_bp

        assert by_stat["atk_pct"] == resolved.stat_bonuses["atk_pct"]
        assert by_stat["crit_rate"] == resolved.stat_bonuses["crit_rate"]

    def test_round_trips_combat_bonuses(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)

        by_stat: dict[str, int] = defaultdict(int)
        for entry in roster:
            by_stat[entry.stat] += entry.value_bp

        assert by_stat["res_reduction"] == resolved.combat_bonuses["res_reduction"]
        assert by_stat["vulnerability"] == resolved.combat_bonuses["vulnerability"]

    def test_round_trips_dmg_bonus_total(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)

        dmg_bonus_total = sum(e.value_bp for e in roster if e.stat == "dmg_bonus")
        assert dmg_bonus_total == resolved.total_dmg_bonus

    def test_every_contribution_appears_exactly_once(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)

        n_contributions = (
            sum(len(v) for v in resolved.stat_attributions.values())
            + len(resolved.dmg_bonus_attributions)
            + sum(len(v) for v in resolved.combat_attributions.values())
        )
        assert len(roster) == n_contributions

    def test_zone_derived_from_stat(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)
        by_stat = {e.stat: e for e in roster}

        assert by_stat["atk_pct"].zone == "base"
        assert by_stat["crit_rate"].zone == "crit"
        assert by_stat["dmg_bonus"].zone == "boost"
        assert by_stat["res_reduction"].zone == "res"
        assert by_stat["vulnerability"].zone == "vulnerability"

    def test_unmodeled_scaling_stat_buff_shown_at_zero(self):
        """A modifier with an unbaked scaling_stat (e.g. Ben's DEF-scaled

        core passive) must never have been baked by snapshot_builder in this
        unit-test setup — resolve_modifiers should surface it at 0 with
        is_modeled=False instead of silently dropping it.
        """
        mods = [
            *_representative_mods(),
            _mod("flat_atk", 0, source_label="Core: DEF-scaled ATK", scaling_stat="def"),
        ]
        resolved = resolve_modifiers(mods, ActiveConditions())
        roster = pivot_buff_roster(resolved)

        unmodeled = [e for e in roster if e.source_label == "Core: DEF-scaled ATK"]
        assert len(unmodeled) == 1
        assert unmodeled[0].is_modeled is False
        assert unmodeled[0].value_bp == 0
        assert unmodeled[0].stat == "flat_atk"

    def test_modeled_buffs_are_is_modeled_true(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)
        assert all(e.is_modeled for e in roster)

    def test_condition_surfaced(self):
        mods = [_mod("vulnerability", 2000, conditions=(Condition.ENEMY_STUNNED,))]
        conds = ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED})
        resolved = resolve_modifiers(mods, conds)
        roster = pivot_buff_roster(resolved)

        assert roster[0].condition == "enemy_stunned"

    def test_magnitude_display_percentage_vs_flat(self):
        mods = [
            _mod("atk_pct", 1000, source_label="pct"),
            _mod("flat_atk", 500, source_label="flat"),
        ]
        resolved = resolve_modifiers(mods, ActiveConditions())
        roster = pivot_buff_roster(resolved)
        by_label = {e.source_label: e for e in roster}

        assert by_label["pct"].magnitude_display == "+10.00%"
        assert by_label["flat"].magnitude_display == "+500"

    def test_unrecognized_stat_falls_back_to_other_zone(self):
        mods = [_mod("hp_pct", 1000, source_label="HP buff")]
        resolved = resolve_modifiers(mods, ActiveConditions())
        roster = pivot_buff_roster(resolved)

        assert roster[0].zone == "other"

    def test_notes_surfaced_on_roster_entry(self):
        mods = [
            _mod(
                "atk_pct",
                1000,
                source_label="Core F",
                notes="Cross-referenced with ZO commit abc1234.",
            )
        ]
        resolved = resolve_modifiers(mods, ActiveConditions())
        roster = pivot_buff_roster(resolved)

        assert roster[0].notes == "Cross-referenced with ZO commit abc1234."

    def test_notes_absent_is_none(self):
        resolved = resolve_modifiers(_representative_mods(), ActiveConditions())
        roster = pivot_buff_roster(resolved)

        assert all(e.notes is None for e in roster)
