"""Pydantic schemas for Team."""

from __future__ import annotations

from pydantic import BaseModel, model_validator

DUPLICATE_SLOT_DETAIL = "A build cannot occupy more than one slot on the same team."

#: The team's slot columns, in party order. **One definition.**
#:
#: This list was previously written out by hand in the model, the schemas, the repository's
#: eager loads and the API's merge check — four places, and when the fork carried ZZZ's
#: three-agent squad into a game with four-character parties, every one of them had to be
#: found. Deriving them from here means a future change is one edit, and a missed call site
#: is impossible rather than merely unlikely.
TEAM_SLOTS: tuple[str, ...] = ("build1_id", "build2_id", "build3_id", "build4_id")


def assert_slots_distinct(**slots: str | None) -> None:
    """Raise ValueError when the same build id fills more than one team slot.

    A Genshin party is up to **four** *different* characters. The same build in two slots has no
    defined meaning, and the eval path is internally inconsistent about it
    inside a single request:

    * `teams.py::_load_team_context` builds `slot_build_ids` as a **list**, so
      the duplicate survives into `all_members` and therefore into the
      `support_members` derived from it — the primary ends up in its own
      support list, contributing its team buffs twice. Its `builds` and
      `member_snapshots` dicts are keyed by build id and *do* collapse to one
      entry. So the same request reads the team as two members and one build.
    * Every index-based support selection (`scorer.py`, `optimizer_pipeline.py`,
      `rank_pipeline.py`, `builds.py`) reaches the same place from the other
      side: `i != active_index` hands the primary back to itself.

    No reading of this input is correct, so it is rejected rather than
    reconciled or normalized (issue #120 review).
    """
    unknown = sorted(set(slots) - set(TEAM_SLOTS))
    if unknown:
        msg = f"{unknown} are not team slots; the four are {list(TEAM_SLOTS)}"
        raise ValueError(msg)
    filled = [slots.get(name) for name in TEAM_SLOTS]
    filled = [b for b in filled if b is not None]
    if len(set(filled)) != len(filled):
        raise ValueError(DUPLICATE_SLOT_DETAIL)


class TeamCreate(BaseModel):
    """Body for `POST /teams`."""

    name: str = ""
    build1_id: str
    build2_id: str | None = None
    build3_id: str | None = None
    build4_id: str | None = None

    @model_validator(mode="after")
    def _slots_are_distinct(self) -> TeamCreate:
        assert_slots_distinct(**{name: getattr(self, name) for name in TEAM_SLOTS})
        return self


class TeamUpdate(BaseModel):
    """Body for `PATCH /teams/{id}` — all fields optional, partial update."""

    name: str | None = None
    build1_id: str | None = None
    build2_id: str | None = None
    build3_id: str | None = None
    build4_id: str | None = None

    @model_validator(mode="after")
    def _slots_are_distinct(self) -> TeamUpdate:
        # Catches a duplicate *within the patch body*. A patch that duplicates an
        # id the row already holds in another slot is only visible once merged
        # with the persisted team, so `update_team` re-checks the merged result.
        assert_slots_distinct(**{name: getattr(self, name) for name in TEAM_SLOTS})
        return self


class TeamRead(BaseModel):
    """Response for team read endpoints."""

    id: str
    name: str
    build1_id: str | None
    build2_id: str | None
    build3_id: str | None
    build4_id: str | None

    model_config = {"from_attributes": True}
