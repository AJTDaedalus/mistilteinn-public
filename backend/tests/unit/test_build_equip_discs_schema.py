"""Unit tests for BuildEquipDiscsRequest schema (Page Plan A4)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.build import BuildEquipDiscsRequest

_VALID_UUID = str(uuid.uuid4())
_VALID_DISCS = {i: str(uuid.uuid4()) for i in range(1, 7)}


class TestBuildEquipDiscsRequest:
    def test_happy_path_all_six_slots(self):
        req = BuildEquipDiscsRequest(discs=_VALID_DISCS)
        assert set(req.discs.keys()) == {1, 2, 3, 4, 5, 6}

    def test_missing_slot_raises(self):
        bad = {i: str(uuid.uuid4()) for i in range(1, 6)}  # missing slot 6
        with pytest.raises(ValidationError, match="missing slots"):
            BuildEquipDiscsRequest(discs=bad)

    def test_extra_slot_raises(self):
        bad = {i: str(uuid.uuid4()) for i in range(1, 8)}  # extra slot 7
        with pytest.raises(ValidationError, match="invalid slots"):
            BuildEquipDiscsRequest(discs=bad)

    def test_non_uuid_value_raises(self):
        bad = {**_VALID_DISCS, 3: "not-a-uuid"}
        with pytest.raises(ValidationError, match="not a valid UUID"):
            BuildEquipDiscsRequest(discs=bad)

    def test_all_slots_wrong_raises_with_detail(self):
        with pytest.raises(ValidationError):
            BuildEquipDiscsRequest(discs={7: _VALID_UUID, 8: _VALID_UUID})
