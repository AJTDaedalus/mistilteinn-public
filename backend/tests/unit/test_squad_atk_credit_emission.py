"""When a squad-ATK credit is owed, and mostly when it is not (#160, A4).

Sits on the ownership DROP path beside the Refringe credit. The guards matter
more than the happy path: an ATK grant reaches every instance a teammate deals,
so a mis-emission credits the target for scaling something the grant never
touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.modifiers import ActiveConditions, Condition
from app.services.optimizer_pipeline import _squad_atk_credit_step, _squad_atk_grant_rows

ROWS = ((240, 600), (1120, 2800))


def _event(**over):
    detail = {"effective_atk": 3000, "attack_name": "Hit", "is_sheer": False}
    detail.update(over.pop("detail", {}))
    return SimpleNamespace(
        kind=over.pop("kind", "hit"),
        agent_id=over.pop("agent_id", "support1"),
        t=over.pop("t", 1.0),
        damage=over.pop("damage", 5000.0),
        detail=detail,
    )


class TestCreditIsOwed:
    def test_a_teammates_atk_scaled_hit(self) -> None:
        step = _squad_atk_credit_step(_event(), "dps", ROWS)
        assert step is not None
        assert step.frozen_teammate_damage == 5000.0
        assert step.teammate_atk_at_sim == 3000
        assert step.grant_rows == ROWS

    @pytest.mark.parametrize("kind", ["aftershock", "kit_formula", "phase_flow_unlock_assist"])
    def test_every_standard_damage_kind_qualifies(self, kind: str) -> None:
        assert _squad_atk_credit_step(_event(kind=kind), "dps", ROWS) is not None


class TestNoCreditIsOwed:
    def test_the_build_grants_nothing(self) -> None:
        """Every agent but Remielle today — and the cheap short-circuit."""
        assert _squad_atk_credit_step(_event(), "dps", ()) is None

    def test_the_scored_builds_own_damage(self) -> None:
        """Her ATK is already live in the rescore; a credit would double it."""
        assert _squad_atk_credit_step(_event(agent_id="dps"), "dps", ROWS) is None

    def test_sheer_damage(self) -> None:
        """`effective_atk` holds SheerForce there — the grant never touched it."""
        assert _squad_atk_credit_step(_event(detail={"is_sheer": True}), "dps", ROWS) is None

    def test_an_anomaly_tick(self) -> None:
        """Deliberate under-credit: an anomaly's ATK belongs to its applier, which
        the buildup shares already model. Folding a second ATK term in without
        reconciling the two would double-count."""
        assert _squad_atk_credit_step(_event(kind="anomaly_tick"), "dps", ROWS) is None

    def test_zero_atk_or_zero_damage(self) -> None:
        assert _squad_atk_credit_step(_event(detail={"effective_atk": 0}), "dps", ROWS) is None
        assert _squad_atk_credit_step(_event(damage=0.0), "dps", ROWS) is None

    def test_no_owner(self) -> None:
        assert _squad_atk_credit_step(_event(), None, ROWS) is None


class TestGrantRowDerivation:
    """Reads PRE-BAKE kit data, and derives the team gates itself (#167).

    The previous version of these tests built `Modifier(atk_scale_ratio=600)` by
    hand and passed it straight in. That shape never occurs at the real call
    site: `_bake_atk_scaled_modifier` folds the ratio into a flat value and
    clears it, so selecting on `atk_scale_ratio` over a resolved snapshot matches
    nothing. The credit was inert in production while these passed. They now go
    through the same inputs the pipeline uses.
    """

    @staticmethod
    def _agent(name, specialty, hakushin_id, faction_id=17):
        return SimpleNamespace(
            name=name, specialty=specialty, element="lumiflux",
            faction_id=faction_id, hakushin_id=hakushin_id,
        )

    @classmethod
    def _build(cls, name, specialty, hakushin_id, bid="b"):
        return SimpleNamespace(id=bid, agent=cls._agent(name, specialty, hakushin_id))

    def test_remielles_rows_resolve_from_the_kit_json(self) -> None:
        """The real path: her hakushin_id, a 3-Anomaly squad, no user conditions."""
        rem = self._build("Remielle", "anomaly", 1581, "r")
        supports = [self._build("Jane", "anomaly", 1261, "j"),
                    self._build("Velina", "anomaly", 1401, "v")]
        rows = _squad_atk_grant_rows(rem, supports, ActiveConditions(active={Condition.ALWAYS}))
        # All three tiers stack in a 3-Anomaly squad; caps sum to the DB's 1600.
        assert rows == ((240, 600), (240, 600), (1120, 2800))
        assert sum(cap for cap, _ in rows) == 1600

    def test_a_non_anomaly_squad_drops_the_higher_tiers(self) -> None:
        """The count gates must actually gate — this is what proves the
        conditions are derived rather than assumed always-on."""
        rem = self._build("Remielle", "anomaly", 1581, "r")
        supports = [self._build("Lycaon", "stun", 1111, "l"),
                    self._build("Lucy", "support", 1131, "u")]
        rows = _squad_atk_grant_rows(rem, supports, ActiveConditions(active={Condition.ALWAYS}))
        assert (240, 600) not in rows[1:], "tier-2 gate did not apply"
        assert (1120, 2800) not in rows, "tier-3 gate did not apply in a 1-Anomaly squad"

    def test_an_agent_with_no_atk_grant_gets_nothing(self) -> None:
        """Every agent but her — and the cheap short-circuit."""
        jane = self._build("Jane", "anomaly", 1261, "j")
        assert _squad_atk_grant_rows(jane, [], ActiveConditions(active={Condition.ALWAYS})) == ()

    def test_a_build_with_no_agent_is_safe(self) -> None:
        assert _squad_atk_grant_rows(SimpleNamespace(id="x"), [], ActiveConditions()) == ()
