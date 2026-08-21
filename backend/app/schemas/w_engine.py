"""Pydantic schemas for W-Engine."""

from typing import Any

from pydantic import BaseModel

from app.models.enums import Rarity, Specialty


class WEngineSummary(BaseModel):
    """Lightweight W-Engine for `GET /w-engines` list responses."""

    id: str
    hakushin_id: int
    name: str
    rarity: Rarity
    specialty: Specialty
    base_atk: int
    secondary_stat_type: str
    secondary_stat_value: int
    icon_path: str = ""

    model_config = {"from_attributes": True}


class WEngineRead(BaseModel):
    """Full W-Engine detail, including passive text and per-level stat scaling."""

    id: str
    hakushin_id: int
    name: str
    rarity: Rarity
    specialty: Specialty
    base_atk: int
    secondary_stat_type: str
    secondary_stat_value: int
    level_scaling: dict[str, Any] | None
    passive_name: str
    passive_descriptions: dict[str, Any] | None
    description: str
    icon_path: str = ""

    model_config = {"from_attributes": True}
