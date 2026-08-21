"""The simulator must derive team-composition conditions (#157).

`simulate()` never computed them. They were wired only in `team_calculator`, which
this path does not use — so every `*_IN_TEAM`-gated modifier was inert unless a caller
declared the condition by hand. 28 modifiers across 18 corpus sources.

Found by a real-team audit: Burnice's Additional Ability grants **+65% Fire Anomaly
Buildup** gated on `same_specialty_or_faction_in_team`. On Jane + Burnice + Caesar it
was dormant, which left fire at 66% of threshold — so Burn *never applied at all*, and
with no second aura the Disorder that defines the comp never fired either. Total damage
1,010,629 against 1,269,783 once the condition was supplied: **−26%**.

That is the shape that makes this worse than a missing DMG%: a missing *buildup* bonus
can drop the gauge below threshold, removing the anomaly entirely along with its aura,
its Disorder, and every downstream interaction — silently.
"""

from app.services.anomaly_simulator import _team_conditions_by_agent
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import Condition


def _snap(name: str, element: str, specialty: str, faction: int = 1) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_specialty=specialty,
        agent_faction_id=faction,
        agent_level=60,
        agent_base_atk=1000,
    )


def _jane_burnice_caesar() -> dict[str, BuildSnapshot]:
    return {
        "Jane": _snap("Jane", "physical", "anomaly", faction=10),
        "Burnice": _snap("Burnice", "fire", "anomaly", faction=20),
        "Caesar": _snap("Caesar", "physical", "defense", faction=30),
    }


def test_presence_conditions_are_team_global_and_include_the_owner():
    conds = _team_conditions_by_agent(_jane_burnice_caesar())

    # Every member sees the same presence set, owner included.
    for agent in ("Jane", "Burnice", "Caesar"):
        assert Condition.ANOMALY_IN_TEAM in conds[agent]
        assert Condition.DEFENSE_IN_TEAM in conds[agent]
    assert Condition.STUN_IN_TEAM not in conds["Jane"]


def test_burnices_fire_kindling_gate_is_satisfied_by_jane():
    """The exact condition that was dormant. Jane is Anomaly, so Burnice's
    owner-relative specialty check passes and her +65% Fire buildup applies."""
    conds = _team_conditions_by_agent(_jane_burnice_caesar())

    assert Condition.SAME_SPECIALTY_OR_FACTION_IN_TEAM in conds["Burnice"]


def test_same_family_is_owner_relative_and_excludes_self():
    """A lone Anomaly agent must not satisfy its own `same specialty` check —
    otherwise every solo-anomaly team silently gains buffs it should not have."""
    solo = {"Burnice": _snap("Burnice", "fire", "anomaly", faction=20)}

    conds = _team_conditions_by_agent(solo)

    assert Condition.ANOMALY_IN_TEAM in conds["Burnice"]  # presence includes owner
    assert Condition.SAME_SPECIALTY_OR_FACTION_IN_TEAM not in conds["Burnice"]


def test_shared_element_and_faction_resolve_independently():
    team = {
        "A": _snap("A", "ice", "anomaly", faction=7),
        "B": _snap("B", "ice", "support", faction=99),  # shares element, not faction
    }

    conds = _team_conditions_by_agent(team)

    assert Condition.SAME_ELEMENT_IN_TEAM in conds["A"]
    assert Condition.SAME_FACTION_IN_TEAM not in conds["A"]
    assert Condition.SAME_ATTRIBUTE_OR_FACTION_IN_TEAM in conds["A"]


def test_anomaly_count_thresholds():
    two = {
        "A": _snap("A", "fire", "anomaly"),
        "B": _snap("B", "ice", "anomaly"),
        "C": _snap("C", "ether", "support"),
    }
    three = {**two, "C": _snap("C", "ether", "anomaly")}

    assert Condition.ANOMALY_COUNT_2_IN_TEAM in _team_conditions_by_agent(two)["A"]
    assert Condition.ANOMALY_COUNT_3_IN_TEAM not in _team_conditions_by_agent(two)["A"]
    assert Condition.ANOMALY_COUNT_3_IN_TEAM in _team_conditions_by_agent(three)["A"]


def test_missing_faction_never_matches_rather_than_matching_everything():
    """Snapshots built before faction was threaded through default to 0. That must
    read as "unknown", not as a faction every other unknown agent shares — otherwise
    an unpopulated snapshot would hand out faction buffs indiscriminately."""
    team = {
        "A": _snap("A", "fire", "anomaly", faction=0),
        "B": _snap("B", "ice", "support", faction=0),
    }

    assert Condition.SAME_FACTION_IN_TEAM not in _team_conditions_by_agent(team)["A"]
