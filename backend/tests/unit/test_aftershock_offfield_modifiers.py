"""Unit tests for _resolve_offfield_modifiers (Task 2)."""

from app.services.anomaly_simulator import _resolve_offfield_modifiers
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget


def _mod(stat: str, target: ModifierTarget, value: int = 100) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label=f"{stat}_{target}",
        target=target,
        conditions=(Condition.ALWAYS,),
    )


def _build(name: str, modifiers: list[Modifier]) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=modifiers,
    )


def test_offfield_merge_drops_active():
    """ACTIVE modifiers from both emitter and teammates are excluded."""
    emitter_self = _mod("dmg_bonus", ModifierTarget.SELF)
    emitter_team = _mod("atk_pct", ModifierTarget.TEAM)
    emitter_active = _mod("crit_rate", ModifierTarget.ACTIVE)  # must be dropped

    teammate_team = _mod("pen_ratio", ModifierTarget.TEAM)
    teammate_active = _mod("crit_dmg", ModifierTarget.ACTIVE)  # must be dropped

    builds = {
        "emitter": _build("Emitter", [emitter_self, emitter_team, emitter_active]),
        "teammate": _build("Teammate", [teammate_team, teammate_active]),
    }

    result = _resolve_offfield_modifiers("emitter", builds)

    labels = {m.source_label for m in result}
    assert "crit_rate_active" not in labels, "Emitter ACTIVE modifier must be dropped"
    assert "crit_dmg_active" not in labels, "Teammate ACTIVE modifier must be dropped"


def test_offfield_merge_keeps_team_and_self():
    """Emitter SELF + emitter TEAM + teammate TEAM are all present."""
    emitter_self = _mod("dmg_bonus", ModifierTarget.SELF)
    emitter_team = _mod("atk_pct", ModifierTarget.TEAM)
    emitter_active = _mod("crit_rate", ModifierTarget.ACTIVE)

    teammate_team = _mod("pen_ratio", ModifierTarget.TEAM)
    teammate_active = _mod("crit_dmg", ModifierTarget.ACTIVE)

    builds = {
        "emitter": _build("Emitter", [emitter_self, emitter_team, emitter_active]),
        "teammate": _build("Teammate", [teammate_team, teammate_active]),
    }

    result = _resolve_offfield_modifiers("emitter", builds)

    labels = {m.source_label for m in result}
    assert "dmg_bonus_self" in labels, "Emitter SELF modifier must be kept"
    assert "atk_pct_team" in labels, "Emitter TEAM modifier must be kept"
    assert "pen_ratio_team" in labels, "Teammate TEAM modifier must be kept"


def test_offfield_merge_multiple_teammates():
    """TEAM modifiers from all teammates are included; their ACTIVE and SELF are dropped."""
    emitter_self = _mod("dmg_bonus", ModifierTarget.SELF)

    t1_team = _mod("atk_pct", ModifierTarget.TEAM)
    t1_self = _mod("flat_atk", ModifierTarget.SELF)  # teammate SELF — must be dropped

    t2_team = _mod("pen_ratio", ModifierTarget.TEAM)

    builds = {
        "emitter": _build("Emitter", [emitter_self]),
        "t1": _build("T1", [t1_team, t1_self]),
        "t2": _build("T2", [t2_team]),
    }

    result = _resolve_offfield_modifiers("emitter", builds)

    labels = {m.source_label for m in result}
    assert "dmg_bonus_self" in labels
    assert "atk_pct_team" in labels
    assert "pen_ratio_team" in labels
    assert "flat_atk_self" not in labels, "Teammate SELF modifier must not be included"


def test_offfield_merge_emitter_only():
    """With no teammates, only emitter SELF + TEAM modifiers are returned."""
    emitter_self = _mod("dmg_bonus", ModifierTarget.SELF)
    emitter_team = _mod("atk_pct", ModifierTarget.TEAM)
    emitter_active = _mod("crit_rate", ModifierTarget.ACTIVE)

    builds = {"emitter": _build("Emitter", [emitter_self, emitter_team, emitter_active])}

    result = _resolve_offfield_modifiers("emitter", builds)

    labels = {m.source_label for m in result}
    assert "dmg_bonus_self" in labels
    assert "atk_pct_team" in labels
    assert "crit_rate_active" not in labels
    assert len(result) == 2
