"""Unit tests for the skill_overrides loader."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.data.loaders.skill_overrides import AgentOverride, load_skill_overrides


def _write_override(directory: Path, stem: str, data: dict) -> None:
    (directory / f"{stem}.json").write_text(json.dumps(data))


def test_empty_directory_returns_empty_dict(tmp_path: Path) -> None:
    result = load_skill_overrides(tmp_path)
    assert result == {}


def test_valid_sequential_override_parsed(tmp_path: Path) -> None:
    _write_override(
        tmp_path,
        "test_agent",
        {
            "agent_name": "Test Agent",
            "moves": {
                "Quick Slash": {"hit_mode": "sequential"},
            },
        },
    )
    result = load_skill_overrides(tmp_path)
    assert "test_agent" in result
    override = result["test_agent"]
    assert isinstance(override, AgentOverride)
    assert override.agent_name == "Test Agent"
    assert override.moves["Quick Slash"].hit_mode.value == "sequential"


def test_valid_variant_override_parsed(tmp_path: Path) -> None:
    _write_override(
        tmp_path,
        "variant_agent",
        {
            "agent_name": "Variant Agent",
            "moves": {
                "Dual Mode": {
                    "hit_mode": "variant",
                    "variants": [
                        {"label": "Mode A", "hit_indices": [0]},
                        {"label": "Mode B", "hit_indices": [1, 2]},
                    ],
                },
            },
        },
    )
    result = load_skill_overrides(tmp_path)
    override = result["variant_agent"]
    move = override.moves["Dual Mode"]
    assert move.hit_mode.value == "variant"
    assert len(move.variants) == 2
    assert move.variants[0].label == "Mode A"
    assert move.variants[1].hit_indices == [1, 2]


def test_invalid_hit_mode_raises_validation_error(tmp_path: Path) -> None:
    _write_override(
        tmp_path,
        "bad_agent",
        {
            "agent_name": "Bad Agent",
            "moves": {
                "Bad Move": {"hit_mode": "unknown_mode"},
            },
        },
    )
    with pytest.raises(ValidationError):
        load_skill_overrides(tmp_path)


def test_overlapping_hit_indices_raises_validation_error(tmp_path: Path) -> None:
    _write_override(
        tmp_path,
        "overlap_agent",
        {
            "agent_name": "Overlap Agent",
            "moves": {
                "Overlap Move": {
                    "hit_mode": "variant",
                    "variants": [
                        {"label": "V1", "hit_indices": [0, 1]},
                        {"label": "V2", "hit_indices": [1, 2]},  # overlaps index 1
                    ],
                },
            },
        },
    )
    with pytest.raises(ValidationError):
        load_skill_overrides(tmp_path)


def test_variant_mode_requires_non_empty_variants(tmp_path: Path) -> None:
    _write_override(
        tmp_path,
        "empty_variants",
        {
            "agent_name": "Empty Variants",
            "moves": {
                "Empty": {
                    "hit_mode": "variant",
                    "variants": [],
                },
            },
        },
    )
    with pytest.raises(ValidationError):
        load_skill_overrides(tmp_path)
