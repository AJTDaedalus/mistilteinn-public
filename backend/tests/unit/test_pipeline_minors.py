"""Hardening Task 18 — pipeline minors F4, F5, F6 from the PR #104 review.

Three small correctness/observability gaps in `optimizer_pipeline` and the
optimizer request schema. None changes damage math; all three are about a
wrong value being accepted, a wrong value being scored as zero, or a latent
`NameError`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import Element
from app.schemas.optimizer import DiscOptimizeRequest
from app.services.optimizer_pipeline import (
    _DELIBERATELY_UNSCORED_EVENT_KINDS,
    _resolve_fluxed_element,
)

_REQUIRED = {"build_id": "b", "combo_id": "c", "enemy_profile_id": "e"}


class TestFluxedElementOverrideIsValidated:
    """F4, first half. The value was never checked against anything:
    `fluxed_element: "banana"` was accepted, unioned no disc stat at all, and
    was echoed back as the resolved element."""

    @pytest.mark.parametrize("value", ["fire", "physical", "ice", "electric", "ether"])
    def test_real_elements_are_accepted(self, value):
        assert DiscOptimizeRequest(**_REQUIRED, fluxed_element=value).fluxed_element == value

    def test_none_is_accepted(self):
        assert DiscOptimizeRequest(**_REQUIRED, fluxed_element=None).fluxed_element is None

    def test_nonsense_is_rejected(self):
        with pytest.raises(ValidationError, match="fluxed_element must be one of"):
            DiscOptimizeRequest(**_REQUIRED, fluxed_element="banana")

    def test_lumiflux_itself_is_rejected(self):
        """A Lumiflux build has no `lumiflux_dmg` bucket by design (DESIGN
        4.2), so fluxing *to* Lumiflux asks for something that cannot exist."""
        with pytest.raises(ValidationError, match="fluxed_element must be one of"):
            DiscOptimizeRequest(**_REQUIRED, fluxed_element=Element.LUMIFLUX.value)


class TestFluxedElementOverrideIsLumifluxOnly:
    """F4, second half. The override used to return before the Lumiflux check,
    so it really did redirect a non-Lumiflux agent's top-K union: `disc_optimizer`
    unions `fluxed_element or agent_element`, so a Fire DPS sent "ice" had
    `fire_dmg` REPLACED, not supplemented -- which in approximate mode can drop
    that agent's real damage discs from the keep-set."""

    def test_override_is_ignored_for_a_non_lumiflux_subject(self):
        assert (
            _resolve_fluxed_element(
                override="ice",
                subject_element=Element.FIRE.value,
                ordered_team_builds=[],
                subject_build_id="b",
            )
            is None
        )

    def test_override_is_honoured_for_a_lumiflux_subject(self):
        assert (
            _resolve_fluxed_element(
                override="ice",
                subject_element=Element.LUMIFLUX.value,
                ordered_team_builds=[],
                subject_build_id="b",
            )
            == "ice"
        )

    def test_no_override_and_non_lumiflux_is_still_none(self):
        assert (
            _resolve_fluxed_element(
                override=None,
                subject_element=Element.FIRE.value,
                ordered_team_builds=[],
                subject_build_id="b",
            )
            is None
        )


class TestUnscoredEventKindsAreDeclared:
    """F5. The event->step mapping had no `else`, so a damage-carrying event
    kind it did not know about was scored as ZERO, silently -- the exact
    failure mode E-8 item 4 added strict guards against on the step side."""

    def test_phase_flow_tick_is_declared_not_forgotten(self):
        assert "phase_flow_tick" in _DELIBERATELY_UNSCORED_EVENT_KINDS

    def test_the_allowlist_is_not_empty(self):
        assert _DELIBERATELY_UNSCORED_EVENT_KINDS

    def test_damage_bearing_kinds_are_not_on_the_allowlist(self):
        """The allowlist must not quietly absorb kinds that carry damage --
        that would re-create the sieve it exists to close."""
        scored = {"hit", "anomaly_tick", "disorder", "vortex", "luminize"}
        assert not (scored & _DELIBERATELY_UNSCORED_EVENT_KINDS)


class TestEveryRequestSchemaValidatesTheFlux:
    """Review follow-up to Task 18's F4 fix.

    F4 was reported against the optimizer schema, and that is where the fix
    started. But hardening Task 17 made `fluxed_element` reach the DAMAGE
    CHAIN, which widened the blast radius: on any request carrying the field,
    an unvalidated string now silently selects no DMG% bucket and a neutral 0
    enemy RES, and is then echoed back as "the element actually used".

    Asserted over every request schema that declares the field, rather than
    one at a time, so a fourth endpoint cannot be added without one.
    """

    @staticmethod
    def _request_models():
        from app.schemas.damage import (
            BuildDamageRequest,
            EvaluateDiscsRequest,
            TeamCalculateRequest,
        )

        return [
            DiscOptimizeRequest,
            BuildDamageRequest,
            TeamCalculateRequest,
            EvaluateDiscsRequest,
        ]

    def test_every_request_model_declaring_the_field_validates_it(self):
        for model in self._request_models():
            assert "fluxed_element" in model.model_fields, model.__name__
            payload = {
                name: "x" for name, f in model.model_fields.items() if f.is_required()
            }
            with pytest.raises(ValidationError, match="fluxed_element must be one of"):
                model.model_validate({**payload, "fluxed_element": "banana"})

    def test_every_request_model_rejects_lumiflux_itself(self):
        for model in self._request_models():
            payload = {
                name: "x" for name, f in model.model_fields.items() if f.is_required()
            }
            with pytest.raises(ValidationError, match="fluxed_element must be one of"):
                model.model_validate(
                    {**payload, "fluxed_element": Element.LUMIFLUX.value}
                )


class TestPhaseFlowTicksAreScoredWhenSheIsTheDPS:
    """P-F2 Piece 2 / hardening Task 15.

    E-6 ruling (c) excluded Phase Flow ticks from the optimizer's step list on
    an "invariant across the disc axis" argument. That is true while the
    Lumiflux agent is a SUPPORT -- her build is never stripped and the ticks
    are not the scored build's damage anyway. It is false when she is the
    optimized DPS: the ticks are hers and they scale with her discs, so leaving
    them out made Phase Flow contribute exactly zero to disc ranking.

    The allowlist entry now covers only the support case; the mapping branch
    catches the DPS case first.
    """

    def test_phase_flow_tick_is_still_allowlisted_for_the_support_case(self):
        assert "phase_flow_tick" in _DELIBERATELY_UNSCORED_EVENT_KINDS

    def test_the_allowlist_entry_documents_why_it_is_conditional(self):
        """Guards against someone reading the allowlist as an unconditional
        'ticks are never scored' and re-deleting the mapping branch."""
        import inspect

        from app.services import optimizer_pipeline

        src = inspect.getsource(optimizer_pipeline)
        idx = src.index('"phase_flow_tick",')
        preamble = src[max(0, idx - 700) : idx]
        assert "support case alone" in preamble
        assert "Task 15" in preamble

    def test_the_mapping_branch_precedes_the_allowlist(self):
        """Order matters: the allowlist `pass` would swallow the tick if it
        came first, silently reverting Piece 2."""
        import inspect

        from app.services import optimizer_pipeline

        src = inspect.getsource(optimizer_pipeline)
        branch = src.index('e.kind == "phase_flow_tick" and _dps_is_lumiflux')
        allowlist = src.index("elif e.kind in _DELIBERATELY_UNSCORED_EVENT_KINDS:")
        assert branch < allowlist
