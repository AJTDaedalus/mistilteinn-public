"""Schemas for user-authored rotations.

The validation here is the whole product claim. `DESIGN_rotation.md` §1: gcsim's syntax is
not hard because it is unfamiliar, it is hard because two of its behaviours are silent —
a bare action list runs **once**, and `while 1` **deadlocks** on an ungated action — and both
produce a plausible config with exactly one burst in it.

A model that cannot express those mistakes is worth more than documentation that warns about
them. So a step names an action from gcsim's own vocabulary and a character that is actually
on the team, and nothing here accepts a shape the compiler would have to guess about.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.gcsim_keys import authorable_actions

#: How many steps one rotation may hold.
#:
#: Generous rather than tight: a real Genshin rotation is a handful of actions, and 200 leaves
#: room for a long multi-character cycle written out longhand — which §2 requires, since the
#: model has no way to say "repeat this section". The cap exists so a single row cannot be
#: used as storage, not to express an opinion about rotations.
MAX_STEPS = 200

#: Largest `repeat` on one step. `attack:20` is already beyond anything a rotation does; the
#: bound is here so a typo cannot compile to a config that runs for an hour.
MAX_REPEAT = 20


class RotationStep(BaseModel):
    """One action by one character."""

    #: The character's nanoka id — stable across build edits and team reordering, and what
    #: the compiler needs to reach a gcsim key. See `app/models/rotation.py` on why not a
    #: slot and not a build.
    character: str = Field(..., min_length=1, max_length=32)
    #: Published to OpenAPI as an enum from the **same** call the validator below checks
    #: against, so a generated client cannot offer an action this would then refuse.
    action: str = Field(..., json_schema_extra={"enum": list(authorable_actions())})
    #: `attack ×3` compiles to gcsim's own `attack:3`.
    repeat: int = Field(default=1, ge=1, le=MAX_REPEAT)
    #: The user's own label for this step. Never interpreted.
    note: str = Field(default="", max_length=200)

    @field_validator("action")
    @classmethod
    def _is_authorable(cls, value: str) -> str:
        """Refuse an action gcsim would not accept, or one the model deliberately hides.

        Checked against `authorable_actions()`, which is derived from gcsim's own `astr` at
        the pin minus the three the model excludes — **not** a list restated here. A restated
        list drifts in the direction that matters most: offering something gcsim rejects, so
        the config fails at simulation time with a parser error rather than at authoring time
        with a sentence.
        """
        allowed = authorable_actions()
        if value not in allowed:
            msg = (
                f"{value!r} is not an action a rotation step can name. The ten are "
                f"{list(allowed)}. `swap` is implicit — gcsim inserts one when the next "
                f"character is not active — and `wait`/`delay` are timing controls this "
                f"model deliberately does not expose."
            )
            raise ValueError(msg)
        return value


class RosterCharacter(BaseModel):
    """One character an editor may name in a step."""

    nanoka_id: str
    name: str
    element: str


class TeamRoster(BaseModel):
    """A team, and who is on it."""

    id: str
    name: str
    characters: list[RosterCharacter]


class RotationOptions(BaseModel):
    """Everything an editor needs to offer a step that will be accepted.

    Both halves come from the same place the write path reads: `actions` from
    `authorable_actions()`, `teams` from the roster extraction `_check_steps_against_team`
    validates against. The guarantee is **the picker offers exactly what the validator
    accepts** — the alternative is a UI list that drifts, and a user told their own
    selection is invalid.
    """

    actions: list[str]
    teams: list[TeamRoster]


class ContextKeyRequest(BaseModel):
    """Body for `POST /rotations/{id}/context-key`."""

    #: Which build on the rotation's team the key is for. `context_key` is per-character:
    #: it hashes one character's own levels and weapon alongside the team it sits in.
    build_id: str
    #: The enemy to point gcsim at. Omitted means the default target, which is defined once
    #: in `gcsim_config.target_fields` rather than restated here.
    enemy_nanoka_id: str | None = None


class ContextKeyRead(BaseModel):
    """The cache key for a rotation, and the parts it was computed from.

    The parts are returned because a key is a hash: opaque by design, and impossible to
    check by eye. A caller that gets an unexpected cache miss can see *what was hashed*
    rather than guess, which is the difference between a debuggable key and a magic one.
    """

    context_key: str
    rotation: list[str]
    team: list[str]
    target: dict[str, object]
    gcsim_pin: str


class RotationCreate(BaseModel):
    """Body for `POST /rotations`."""

    name: str = Field(..., min_length=1, max_length=200)
    team_id: str
    steps: list[RotationStep] = Field(default_factory=list, max_length=MAX_STEPS)
    description: str = Field(default="", max_length=2000)


class RotationUpdate(BaseModel):
    """Body for `PATCH /rotations/{id}` — every field optional, partial update.

    `team_id` is **not** here. Moving a rotation to another team would silently reinterpret
    every step against a different party, and the steps that no longer resolve would be
    discovered later, at compile time, far from the edit that caused it. Build a new rotation
    for the other team.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    steps: list[RotationStep] | None = Field(default=None, max_length=MAX_STEPS)
    description: str | None = Field(default=None, max_length=2000)


class RotationRead(BaseModel):
    """One saved rotation."""

    id: str
    name: str
    team_id: str
    description: str
    steps: list[RotationStep]

    model_config = {"from_attributes": True}
