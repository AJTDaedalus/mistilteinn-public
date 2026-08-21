"""Task 20 — moves/agents/remielle.json + skill_overrides/remielle.json
(DESIGN_remielle.md; MODIFIER_AUTHORING.md §3/§4).
"""

import json
from pathlib import Path

from app.data.loaders.moves import load_agent_moves

SKILL_OVERRIDE_PATH = (
    Path(__file__).parents[2] / "app" / "data" / "skill_overrides" / "remielle.json"
)


def _remielle_moves():
    return load_agent_moves()["remielle"]


class TestMovesLoad:
    def test_all_fourteen_named_moves_present(self):
        moves = _remielle_moves().moves
        assert len(moves) == 14

    def test_every_move_has_explicit_zero_buildup(self):
        """Genuine explicit 0s, not omissions -- she applies no conventional
        Anomaly Buildup (Task 5 DB confirmation)."""
        moves = _remielle_moves().moves
        for name, spec in moves.items():
            assert spec.buildup == 0, f"{name} should have explicit buildup=0"

    def test_basic_attack_leap_has_four_hits(self):
        spec = _remielle_moves().moves["Basic Attack: Leap"]
        assert spec.hits == 4
        assert spec.scope == "basic"

    def test_dash_and_dodge_counter_scopes_disambiguated(self):
        moves = _remielle_moves().moves
        assert moves["Dash Attack: Keen Light"].scope == "dash"
        assert moves["Dodge Counter: Mirrored Shadow"].scope == "dodge_counter"


class TestLuminizeTriggerFlags:
    """Exactly the guide's 4 Luminize-triggering moves carry the flag, with
    the DESIGN §9.2-derived multipliers (DB CAL expressions at skill level 12,
    confirmed matching the guide's stated lv-12 values)."""

    def test_exactly_four_moves_trigger_luminize(self):
        moves = _remielle_moves().moves
        triggering = {name for name, spec in moves.items() if spec.triggers_luminize}
        assert triggering == {
            "Basic Attack: Rainbow's End",
            "Basic Attack: Fleeting Grace",
            "Ultimate: Dazzling Curtain Call",
            "Assist: Flower & Feather Dance",
        }

    def test_luminize_multipliers_match_design_9_2(self):
        moves = _remielle_moves().moves
        assert moves["Basic Attack: Rainbow's End"].luminize_mult_bp == 16000
        assert moves["Basic Attack: Fleeting Grace"].luminize_mult_bp == 32000
        assert moves["Ultimate: Dazzling Curtain Call"].luminize_mult_bp == 33600
        assert moves["Assist: Flower & Feather Dance"].luminize_mult_bp == 32000

    def test_non_triggering_moves_default_false_and_zero(self):
        moves = _remielle_moves().moves
        solo_dance = moves["Basic Attack: Solo Dance"]
        assert solo_dance.triggers_luminize is False
        assert solo_dance.luminize_mult_bp == 0


class TestLumifluxPointCounts:
    def test_ex_special_applies_two_points(self):
        spec = _remielle_moves().moves["EX Special Attack: Ode to Dawn"]
        assert spec.lumiflux_points == 2

    def test_moves_without_point_data_default_to_zero(self):
        spec = _remielle_moves().moves["Basic Attack: Solo Dance"]
        assert spec.lumiflux_points == 0


class TestSkillOverride:
    def test_basic_attack_leap_is_sequential(self):
        data = json.loads(SKILL_OVERRIDE_PATH.read_text())
        assert data["agent_name"] == "Remielle"
        assert data["moves"]["Basic Attack: Leap"]["hit_mode"] == "sequential"
