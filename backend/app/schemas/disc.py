"""Pydantic schemas for DiscSet and Disc."""

from typing import Any

from pydantic import BaseModel

from app.models.enums import DiscSlot, Rarity, StatType

# --- DiscSet (read-only, seeded) ---


class DiscSetSummary(BaseModel):
    """Lightweight disc set for `GET /disc-sets` list responses."""

    id: str
    hakushin_id: int
    name: str
    two_piece_text: str
    four_piece_text: str
    icon_path: str = ""

    model_config = {"from_attributes": True}


class DiscSetRead(BaseModel):
    """Full disc set detail, including the 2pc/4pc effect breakdowns used by set-bonus calc."""

    id: str
    hakushin_id: int
    name: str
    two_piece_text: str
    four_piece_text: str
    two_piece_effects: list[dict[str, Any]] | None
    four_piece_effects: list[dict[str, Any]] | None
    icon_path: str

    model_config = {"from_attributes": True}


# --- Disc (user inventory, full CRUD) ---


class SubstatInput(BaseModel):
    """One substat roll supplied when creating or updating a disc."""

    stat: str
    value: int
    rolls: int = 1


class DiscCreate(BaseModel):
    """Body for `POST /discs` — adds a disc to the user's inventory."""

    disc_set_id: str
    slot: DiscSlot
    rarity: Rarity
    level: int = 0
    main_stat_type: StatType
    main_stat_value: int
    substats: list[SubstatInput] | None = None


class DiscUpdate(BaseModel):
    """Body for `PATCH /discs/{id}` — partial update, including (un)equipping to a build slot."""

    level: int | None = None
    main_stat_value: int | None = None
    substats: list[SubstatInput] | None = None
    build_id: str | None = None
    build_slot: int | None = None


class DiscRead(BaseModel):
    """Response for disc read endpoints."""

    id: str
    disc_set_id: str
    slot: DiscSlot
    rarity: Rarity
    level: int
    main_stat_type: StatType
    main_stat_value: int
    substats: list[dict[str, Any]] | None
    build_id: str | None
    build_slot: int | None

    model_config = {"from_attributes": True}
