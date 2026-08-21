"""Unit tests for RankContextSchema, RankRequest, DiscRankSchema (R2.4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.scorer import (
    DiscRankSchema,
    RankContextSchema,
    RankRequest,
    RankResponse,
)


def _ctx(**kw) -> dict:
    return {
        "build_id": "b-1",
        "combo_id": "c-1",
        "enemy_profile_id": "e-1",
        **kw,
    }


class TestRankContextSchema:
    def test_minimal_valid(self):
        ctx = RankContextSchema(**_ctx())
        assert ctx.build_id == "b-1"
        assert ctx.weight == 1.0
        assert ctx.allowed_set_ids is None

    def test_weight_defaults_one(self):
        ctx = RankContextSchema(**_ctx())
        assert ctx.weight == 1.0

    def test_weight_must_be_positive(self):
        with pytest.raises(ValidationError):
            RankContextSchema(**_ctx(weight=0))
        with pytest.raises(ValidationError):
            RankContextSchema(**_ctx(weight=-1))

    def test_allowed_set_ids_accepted(self):
        ctx = RankContextSchema(**_ctx(allowed_set_ids=[1, 2, 3]))
        assert ctx.allowed_set_ids == [1, 2, 3]

    def test_inherits_scorer_context_fields(self):
        ctx = RankContextSchema(**_ctx(crit_mode="crit", is_stunned=True, refinement=3))
        assert ctx.crit_mode == "crit"
        assert ctx.is_stunned is True
        assert ctx.refinement == 3

    def test_support_slot_defaults_none(self):
        ctx = RankContextSchema(**_ctx())
        assert ctx.support_slot is None

    def test_support_slot_valid_values(self):
        assert RankContextSchema(**_ctx(support_slot=1)).support_slot == 1
        assert RankContextSchema(**_ctx(support_slot=2)).support_slot == 2

    def test_support_slot_invalid_rejects(self):
        with pytest.raises(ValidationError):
            RankContextSchema(**_ctx(support_slot=0))
        with pytest.raises(ValidationError):
            RankContextSchema(**_ctx(support_slot=3))


class TestRankRequest:
    def test_single_context(self):
        req = RankRequest(contexts=[_ctx()])
        assert len(req.contexts) == 1

    def test_multiple_contexts(self):
        req = RankRequest(contexts=[_ctx(build_id="b1"), _ctx(build_id="b2")])
        assert len(req.contexts) == 2

    def test_empty_contexts_rejected(self):
        with pytest.raises(ValidationError):
            RankRequest(contexts=[])

    def test_scope_default(self):
        req = RankRequest(contexts=[_ctx()])
        assert req.scope == "default"

    def test_disc_ids_optional(self):
        req = RankRequest(contexts=[_ctx()], disc_ids=["d1", "d2"])
        assert req.disc_ids == ["d1", "d2"]


class TestDiscRankSchema:
    def _rank_schema(self) -> dict:
        return {
            "disc_id": "d-1",
            "per_build": [
                {"build_id": "b1", "avg_pct": 5.0, "max_pct": 10.0},
                {"build_id": "b2", "avg_pct": None, "max_pct": None},
            ],
            "best_build_avg": 5.0,
            "best_build_avg_build_id": "b1",
            "best_build_max": 10.0,
            "portfolio_avg": 2.5,
        }

    def test_valid(self):
        s = DiscRankSchema(**self._rank_schema())
        assert s.disc_id == "d-1"
        assert len(s.per_build) == 2

    def test_nullable_per_build_fields(self):
        s = DiscRankSchema(**self._rank_schema())
        b2 = next(p for p in s.per_build if p.build_id == "b2")
        assert b2.avg_pct is None
        assert b2.max_pct is None


class TestRankResponse:
    def test_contains_job_id(self):
        r = RankResponse(job_id="some-uuid")
        assert r.job_id == "some-uuid"
