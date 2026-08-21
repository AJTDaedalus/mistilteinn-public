"""Unit tests for Task 5 team-decoupling route schema changes.

Tests that DiscOptimizeRequest and RankContextSchema accept team_id + active_index,
and that the active_index validator rejects out-of-range values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.optimizer import DiscOptimizeRequest
from app.schemas.scorer import RankContextSchema


class TestDiscOptimizeRequestTeamFields:
    """DiscOptimizeRequest accepts optional team_id + active_index."""

    def _base_body(self) -> dict:
        return {
            "combo_id": "some-combo-id",
            "enemy_profile_id": "some-enemy-id",
        }

    def test_team_id_optional_defaults_to_none(self) -> None:
        body = DiscOptimizeRequest(**self._base_body())
        assert body.team_id is None

    def test_active_index_defaults_to_zero(self) -> None:
        body = DiscOptimizeRequest(**self._base_body())
        assert body.active_index == 0

    def test_team_id_and_active_index_accepted(self) -> None:
        body = DiscOptimizeRequest(
            **self._base_body(),
            team_id="team-uuid-123",
            active_index=1,
        )
        assert body.team_id == "team-uuid-123"
        assert body.active_index == 1

    def test_active_index_0_1_2_valid(self) -> None:
        for idx in (0, 1, 2):
            body = DiscOptimizeRequest(**self._base_body(), active_index=idx)
            assert body.active_index == idx

    def test_active_index_above_2_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            DiscOptimizeRequest(**self._base_body(), active_index=3)
        assert "active_index" in str(exc_info.value)

    def test_active_index_negative_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            DiscOptimizeRequest(**self._base_body(), active_index=-1)
        assert "active_index" in str(exc_info.value)


class TestRankContextSchemaTeamFields:
    """RankContextSchema accepts optional team_id + active_index."""

    def _base_ctx(self) -> dict:
        return {
            "build_id": "build-uuid",
            "combo_id": "combo-uuid",
            "enemy_profile_id": "enemy-uuid",
        }

    def test_team_id_optional_defaults_to_none(self) -> None:
        ctx = RankContextSchema(**self._base_ctx())
        assert ctx.team_id is None

    def test_active_index_defaults_to_zero(self) -> None:
        ctx = RankContextSchema(**self._base_ctx())
        assert ctx.active_index == 0

    def test_team_id_and_active_index_accepted(self) -> None:
        ctx = RankContextSchema(
            **self._base_ctx(),
            team_id="team-uuid-456",
            active_index=2,
        )
        assert ctx.team_id == "team-uuid-456"
        assert ctx.active_index == 2

    def test_active_index_0_1_2_valid(self) -> None:
        for idx in (0, 1, 2):
            ctx = RankContextSchema(**self._base_ctx(), active_index=idx)
            assert ctx.active_index == idx

    def test_active_index_above_2_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            RankContextSchema(**self._base_ctx(), active_index=3)
        assert "active_index" in str(exc_info.value)

    def test_active_index_negative_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            RankContextSchema(**self._base_ctx(), active_index=-1)
        assert "active_index" in str(exc_info.value)
