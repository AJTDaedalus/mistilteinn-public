"""Move-spec fallback must attribute buildup to the element that carries it.

When an agent has no authored JSON move spec, the simulator collapses a move's
DB attack rows into a single buildup total and tags it with one element. That
element used to be ``attacks[0].element``, but many multi-element Basic strings
open on a Physical hit carrying *zero* buildup (Miyabi, Lycaon, Zhu Yuan,
Yanagi ...), so every point of Ice/Ether/Electric buildup was applied to
Physical — producing Assault instead of the agent's real anomaly.
"""

from app.services.anomaly_simulator import _dominant_buildup_element


class _Attack:
    def __init__(self, element: str, anomaly_buildup: int) -> None:
        self.element = element
        self.anomaly_buildup = anomaly_buildup


class TestDominantBuildupElement:
    def test_zero_buildup_physical_opener_does_not_win(self):
        """Miyabi/Lycaon/Yanagi shape: physical hit 0 has no buildup, ice/electric does."""
        attacks = [_Attack("physical", 0), _Attack("ice", 20000), _Attack("ice", 8338)]
        assert _dominant_buildup_element(attacks, "ice") == "ice"

    def test_picks_majority_element_when_both_carry_buildup(self):
        """Trigger 'Silenced Shot': electric 22022 vs physical 11926 → electric."""
        attacks = [_Attack("electric", 22022), _Attack("physical", 11926)]
        assert _dominant_buildup_element(attacks, "electric") == "electric"

    def test_single_element_move_is_unchanged(self):
        attacks = [_Attack("fire", 5000), _Attack("fire", 3000)]
        assert _dominant_buildup_element(attacks, "fire") == "fire"

    def test_all_zero_buildup_falls_back_to_first_hit(self):
        """Preserves prior behaviour when no row carries buildup."""
        attacks = [_Attack("physical", 0), _Attack("ice", 0)]
        assert _dominant_buildup_element(attacks, "ice") == "physical"

    def test_no_attacks_falls_back_to_agent_element(self):
        assert _dominant_buildup_element([], "ether") == "ether"

    def test_missing_element_falls_back_to_agent_element(self):
        attacks = [_Attack(None, 0)]
        assert _dominant_buildup_element(attacks, "ether") == "ether"
