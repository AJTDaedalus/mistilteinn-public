"""Pydantic schemas for saved stage-buff presets (issue #64, DESIGN_buff_context.md §2.4)."""

from __future__ import annotations

import datetime  # noqa: TC003 — needed at runtime for Pydantic field resolution

from pydantic import BaseModel, Field, model_validator

from app.schemas.damage import MAX_CUSTOM_BUFFS, CustomBuff, StoredCustomBuff
from app.services.modifiers import (
    DuplicateCustomBuffError,
    UnslugifiableCustomBuffError,
    assert_addressable_custom_buffs,
)

#: Imported rather than restated: a preset that saves must be a preset that can be
#: applied, and applying one copies its buffs into a request's `custom_buffs`.
_MAX_BUFFS_PER_PRESET = MAX_CUSTOM_BUFFS


def _reject_unaddressable_labels(buffs: list[CustomBuff]) -> None:
    """Same addressability rule the request-side ``CustomBuffCarrier`` enforces.

    A preset is applied by *copying* its buffs into a request's ``custom_buffs``
    (DESIGN §2.4), so a preset that could not be sent is a preset that fails at apply
    time instead of at save time — with the user's authoring context long gone. Reject
    it at the point of authorship, where the error names something the user is looking
    at. Same function, not a second copy of the rule.
    """
    try:
        assert_addressable_custom_buffs(buffs)
    except (UnslugifiableCustomBuffError, DuplicateCustomBuffError) as exc:
        raise ValueError(str(exc)) from exc


class BuffPresetCreate(BaseModel):
    """Body for ``POST /buff-presets``."""

    name: str = Field(min_length=1, max_length=200, description='e.g. "DA 2.1 Stage 3"')
    buffs: list[CustomBuff] = Field(
        default_factory=list,
        max_length=_MAX_BUFFS_PER_PRESET,
        description="The stage buffs this preset applies, in `custom_buffs` shape.",
    )

    @model_validator(mode="after")
    def _addressable_labels(self) -> BuffPresetCreate:
        _reject_unaddressable_labels(self.buffs)
        return self


class BuffPresetUpdate(BaseModel):
    """Body for ``PATCH /buff-presets/{id}`` — all fields optional, partial update.

    ``None`` here means "field absent", never "set this column to null": both columns are
    ``NOT NULL``. The route patches with ``exclude_unset=True``, so an omitted field is
    already dropped — but an **explicit** ``{"name": null}`` survives that filter and
    reached the DB as an IntegrityError, i.e. a 500 for what is plainly a bad request. The
    validator below turns it into the 422 it always should have been.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    buffs: list[CustomBuff] | None = Field(default=None, max_length=_MAX_BUFFS_PER_PRESET)

    @model_validator(mode="after")
    def _addressable_labels(self) -> BuffPresetUpdate:
        if self.buffs is not None:
            _reject_unaddressable_labels(self.buffs)
        return self

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> BuffPresetUpdate:
        explicit_nulls = [
            field for field in self.model_fields_set if getattr(self, field) is None
        ]
        if explicit_nulls:
            raise ValueError(
                f"{', '.join(sorted(explicit_nulls))} cannot be null; omit the field to "
                "leave it unchanged, or send a value"
            )
        return self


class BuffPresetRead(BaseModel):
    """Response for buff-preset read endpoints.

    ``buffs`` is read back as :class:`StoredCustomBuff` — same shape, no vocabulary
    checks. Writes go through :class:`CustomBuff` and are strict; reads must not be, or a
    preset saved before a stat key was renamed would 500 the list endpoint and take the
    whole panel down with it, including the user's ability to see and delete the preset
    that did it. Applying a stale preset still fails loudly, at the calc request.
    """

    id: str
    name: str
    buffs: list[StoredCustomBuff]
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
