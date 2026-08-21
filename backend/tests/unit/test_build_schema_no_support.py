"""Unit tests for Task 6 — support fields removed from Build schemas.

Verifies that BuildCreate, BuildUpdate, and BuildRead no longer carry
support1/support2 FK or embedded-summary fields.
"""

from __future__ import annotations

import app.schemas.build as build_mod
from app.schemas.build import BuildCreate, BuildRead, BuildUpdate


class TestBuildCreateNoSupportFields:
    """BuildCreate no longer has support1/2 FK fields."""

    def test_no_support1_build_id(self) -> None:
        assert "support1_build_id" not in BuildCreate.model_fields

    def test_no_support2_build_id(self) -> None:
        assert "support2_build_id" not in BuildCreate.model_fields

    def test_no_support1_agent_id(self) -> None:
        assert "support1_agent_id" not in BuildCreate.model_fields

    def test_no_support2_agent_id(self) -> None:
        assert "support2_agent_id" not in BuildCreate.model_fields

    def test_create_with_required_fields_only(self) -> None:
        body = BuildCreate(agent_id="agent-uuid-1")
        assert body.agent_id == "agent-uuid-1"


class TestBuildUpdateNoSupportFields:
    """BuildUpdate no longer has support1/2 FK fields."""

    def test_no_support1_build_id(self) -> None:
        assert "support1_build_id" not in BuildUpdate.model_fields

    def test_no_support2_build_id(self) -> None:
        assert "support2_build_id" not in BuildUpdate.model_fields

    def test_no_support1_agent_id(self) -> None:
        assert "support1_agent_id" not in BuildUpdate.model_fields

    def test_no_support2_agent_id(self) -> None:
        assert "support2_agent_id" not in BuildUpdate.model_fields

    def test_update_empty_is_valid(self) -> None:
        BuildUpdate()
        assert "name" not in BuildUpdate.model_fields


class TestBuildReadNoSupportFields:
    """BuildRead no longer has support1/2 FK or embedded-summary fields."""

    def test_no_support1_build_id(self) -> None:
        assert "support1_build_id" not in BuildRead.model_fields

    def test_no_support2_build_id(self) -> None:
        assert "support2_build_id" not in BuildRead.model_fields

    def test_no_support1_agent_id(self) -> None:
        assert "support1_agent_id" not in BuildRead.model_fields

    def test_no_support2_agent_id(self) -> None:
        assert "support2_agent_id" not in BuildRead.model_fields

    def test_no_embedded_support1(self) -> None:
        assert "support1" not in BuildRead.model_fields

    def test_no_embedded_support2(self) -> None:
        assert "support2" not in BuildRead.model_fields


class TestBuildSupportSummaryRemoved:
    """BuildSupportSummary is no longer exported from schemas.build."""

    def test_build_support_summary_not_in_module(self) -> None:
        assert not hasattr(build_mod, "BuildSupportSummary")
