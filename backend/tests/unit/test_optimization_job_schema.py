"""Unit tests for OptimizationJob Pydantic schemas."""

import datetime

import pytest
from pydantic import ValidationError

from app.schemas.optimization_job import OptimizationJobRead, OptimizationJobSummary


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)


def _summary_data() -> dict:
    return {
        "id": "01234567-0000-7000-8000-000000000001",
        "status": "queued",
        "job_type": "optimize",
        "character_name": "Zhu Yuan",
        "enemy_name": "Metal Crab",
        "rotation_name": "DPS Combo",
        "assignments_done": 0,
        "assignments_total": 0,
        "evaluated": 0,
        "elapsed_seconds": 0.0,
        "eta_seconds": None,
        "top_damage": None,
        "error_message": None,
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
    }


class TestOptimizationJobSummary:
    def test_round_trip(self):
        data = _summary_data()
        obj = OptimizationJobSummary(**data)
        assert obj.id == data["id"]
        assert obj.status == "queued"
        assert obj.character_name == "Zhu Yuan"
        assert obj.eta_seconds is None

    def test_all_statuses_valid(self):
        for status in ("queued", "running", "succeeded", "failed", "cancelled"):
            data = {**_summary_data(), "status": status}
            obj = OptimizationJobSummary(**data)
            assert obj.status == status

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            OptimizationJobSummary(**{**_summary_data(), "status": "unknown"})

    def test_serializes_to_dict(self):
        obj = OptimizationJobSummary(**_summary_data())
        d = obj.model_dump()
        assert "id" in d
        assert "status" in d
        assert "request" not in d
        assert "result" not in d


class TestOptimizationJobRead:
    def test_includes_request_and_result(self):
        data = {
            **_summary_data(),
            "status": "succeeded",
            "request": {"combo_id": "c1"},
            "result": None,
        }
        obj = OptimizationJobRead(**data)
        assert obj.request == {"combo_id": "c1"}
        assert obj.result is None

    def test_is_subclass_of_summary(self):
        assert issubclass(OptimizationJobRead, OptimizationJobSummary)
