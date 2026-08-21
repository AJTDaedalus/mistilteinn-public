"""When a Refringe credit is owed, and — mostly — when it is not (#160).

`_refringe_credit_step` sits on the ownership DROP path: the teammate's anomaly
tick has already been rejected by `_owns`, and this decides whether any slice of
it belongs to the scored build anyway. Every guard is a case where crediting
would invent or double-count damage, so the negative cases matter more than the
positive one.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.optimizer_pipeline import _refringe_credit_step

_CREDIT = {
    "refringe_agent_id": "dps",
    "refringe_ap_ratio_bp": 2,
    "refringe_flat_bonus_bp": 2000,
}


def _tick(**overrides):
    detail = {"refringe_mult": 11224, "refringe_credit": dict(_CREDIT)}
    detail.update(overrides.pop("detail", {}))
    return SimpleNamespace(
        kind=overrides.pop("kind", "anomaly_tick"),
        element=overrides.pop("element", "physical"),
        t=overrides.pop("t", 1.0),
        damage=overrides.pop("damage", 5000.0),
        detail=detail,
    )


class TestCreditIsOwed:
    def test_a_refringed_teammate_tick_owned_by_the_scored_build(self) -> None:
        step = _refringe_credit_step(_tick(), "dps")
        assert step is not None
        assert step.frozen_tick_damage == 5000.0
        assert step.refringe_mult_at_stripped_ap == 11224
        assert step.refringe_ap_ratio_bp == 2
        assert step.refringe_flat_bonus_bp == 2000

    def test_label_and_id_identify_the_tick(self) -> None:
        step = _refringe_credit_step(_tick(element="fire", t=3.5), "dps")
        assert step is not None
        assert "fire" in step.label
        assert step.attack_id == "refringe_credit_fire_3.5"


class TestNoCreditIsOwed:
    def test_no_owner_means_no_ownership_filtering_at_all(self) -> None:
        """`score_owner_id=None` is the legacy map-every-event mode."""
        assert _refringe_credit_step(_tick(), None) is None

    def test_a_non_anomaly_event(self) -> None:
        """Refringe multiplies the anomaly half of the split and nothing else."""
        assert _refringe_credit_step(_tick(kind="hit"), "dps") is None

    def test_refringe_never_fired_on_this_aura(self) -> None:
        """No payload means no uplift is inside the number to attribute."""
        assert _refringe_credit_step(_tick(detail={"refringe_credit": None}), "dps") is None

    def test_a_neutral_multiplier_carries_no_uplift(self) -> None:
        assert _refringe_credit_step(_tick(detail={"refringe_mult": 10000}), "dps") is None

    def test_another_lumiflux_agents_refringe(self) -> None:
        """Crediting build A for build B's coefficient is the #112 error class."""
        detail = {"refringe_credit": {**_CREDIT, "refringe_agent_id": "support1"}}
        assert _refringe_credit_step(_tick(detail=detail), "dps") is None

    def test_a_zero_damage_tick(self) -> None:
        assert _refringe_credit_step(_tick(damage=0.0), "dps") is None

    def test_a_missing_damage_tick(self) -> None:
        assert _refringe_credit_step(_tick(damage=None), "dps") is None


class TestNoDoubleCounting:
    def test_the_scored_builds_own_tick_is_not_credited_here(self) -> None:
        """The caller only reaches this on the DROP path, and that is load-bearing.

        When the scored build's buildup share is non-zero, `_owns` KEEPS the
        tick and `_refringe_scale` folds the uplift into `procs_override`. A
        credit emitted alongside would count it twice. This pins the contract
        that makes the guard unnecessary at this level: the helper is a pure
        function of the event, so the protection lives in the call site, and
        this test documents that rather than asserting a behaviour the helper
        does not have.
        """
        from app.services.optimizer_pipeline import _anomaly_owner_share, _owns

        owned = _tick()
        owned.detail["per_agent_buildup_shares"] = {"dps": 1.0}
        assert _anomaly_owner_share(owned.detail, "dps") == 1.0
        assert _owns(owned, "dps") is True  # kept, so the drop path is never reached

        teammate = _tick()
        teammate.detail["per_agent_buildup_shares"] = {"support1": 1.0}
        assert _anomaly_owner_share(teammate.detail, "dps") == 0.0
        assert _owns(teammate, "dps") is False  # dropped -> credit path
        assert _refringe_credit_step(teammate, "dps") is not None
