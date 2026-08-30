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

from app.models.enums import Visibility
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
    #: The catalogue art's basename, so an editor can draw the roster rather than list it.
    #:
    #: Published here rather than looked up client-side for the reason `/options` exists at
    #: all: the walk from team to build to character is one the client has no business
    #: performing, and joining a second endpoint to decorate this one would be that walk
    #: wearing a different name. Nullable — a row with no art is a seeding gap, not an error.
    icon: str | None = None
    #: This character's own names for their abilities, keyed by **gcsim's action** —
    #: `{"skill": "All Schemes to Know"}` — so an editor can offer what the player knows.
    #:
    #: **A gcsim config says `nahida skill`, and that is the complaint that started this
    #: chunk.** The action key still governs everything: this decorates a label and is never
    #: parsed, so a character whose talents are not seeded simply shows the key.
    #:
    #: Keyed by the action rather than by `TalentType`, because the two vocabularies are not
    #: the same and look like they are — gcsim writes `skill`, the catalogue stores
    #: `elemental_skill`. `gcsim_keys.ability_names` owns the correspondence, and only three
    #: of the ten actions have one; see its comment on why a charged attack keeps its key.
    abilities: dict[str, str] = {}


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
    #:
    #: An **int**, unlike a character's `nanoka_id`. `EnemyProfile.nanoka_id` is an Integer
    #: column; characters need a string because 28 Traveler variants are spelled
    #: `10000005-2`. Typed as a string here it reached asyncpg as text for an integer column
    #: and the whole branch raised — found in the R.6 self-review, untested until then.
    enemy_nanoka_id: int | None = None


class ContextKeyRead(BaseModel):
    """The cache key for a rotation, and the parts it was computed from.

    The parts are returned because a key is a hash: opaque by design, and impossible to
    check by eye. A caller that gets an unexpected cache miss can see *what was hashed*
    rather than guess, which is the difference between a debuggable key and a magic one.
    """

    context_key: str
    rotation: list[str]
    #: `rotation`, hashed — the value `sim_runs.rotation_signature` stores.
    #:
    #: Published so a client labelling a cached run never computes this itself. Two
    #: implementations of one digest would not disagree loudly; they would make every
    #: `your_dps` `None`, which is a library that quietly never sorts and leaves nothing in a
    #: log to find. `rotation_compiler.signature_digest` is the one definition.
    rotation_signature: str
    team: list[str]
    target: dict[str, object]
    gcsim_pin: str
    #: The width of an ER bucket, in whole percent. Published so a client submitting a run
    #: never restates it: `sim_context.er_bucket` rounds **down** on purpose, and a client
    #: rounding any other way would write rows keyed to a bucket no reader ever generates —
    #: filling a cache it could not hit, with the miss looking like a cold context.
    er_bucket_percent: int


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
    #: Publish or unpublish. A field of the rotation, not a `/publish` endpoint — a separate
    #: route would be a second way to write one column, and the two would need the same
    #: ownership check written twice. **Unpublishing is allowed and immediate**: a user who
    #: shared something by mistake needs the door to open both ways.
    visibility: Visibility | None = None


class RotationRead(BaseModel):
    """One saved rotation."""

    id: str
    name: str
    team_id: str
    description: str
    steps: list[RotationStep]
    #: Published rotations are readable by everyone on this instance. Private is the default
    #: and the decision (`DECISIONS.md` §21).
    visibility: Visibility = Visibility.PRIVATE

    model_config = {"from_attributes": True}


class LibraryRotationRead(BaseModel):
    """One published rotation, as the library lists it.

    **Not `RotationRead` with fields added.** That schema is what an author sees of their own
    rotation; this is what a stranger sees of someone else's, and the difference is the point:
    `like_count` and `liked_by_me` are facts about the *caller*, and `characters` is the
    derived index rather than the steps.

    The steps are here too, because a rotation nobody can read before copying is one nobody
    should copy — the whole argument for `POST /{id}/compile` applies to a shared rotation with
    more force.
    """

    id: str
    name: str
    description: str
    steps: list[RotationStep]
    #: The nanoka ids this rotation names, from `rotation_characters`.
    characters: list[str]
    like_count: int
    #: Whether *this* caller has liked it. A count alone cannot answer that, which is why
    #: likes are a table (`DECISIONS.md` §21, OQ-3).
    liked_by_me: bool
    #: **Your** DPS for this rotation, on your gear, or `None` if you have not run it.
    #:
    #: Never the author's. `DESIGN_rotation_library.md` §3: DPS depends on the searcher's
    #: artifacts, not the publisher's, so a number computed on somebody else's roster would
    #: answer a question nobody asked. `None` is the honest state for a rotation you have not
    #: run — and for one you ran *before editing it*, since a run whose signature no longer
    #: matches describes a previous version.
    your_dps: float | None = None


class RotationCopyRequest(BaseModel):
    """Body for `POST /rotations/{id}/copy` — which of the caller's teams to copy it onto."""

    team_id: str


class RotationImportRequest(BaseModel):
    """Body for `POST /rotations/import` — a gcsim config to read back into steps."""

    #: The team the rotation's characters must be on. Imported steps are only meaningful
    #: against a roster: gcsim names characters by *its* key, and mapping one back needs the
    #: team's rows. It is also what makes the refusal specific — "no character on this team
    #: is gcsim's `bennett`" is actionable in a way "unknown key" is not.
    team_id: str
    #: The config text. A whole `.txt` file is expected, not a hand-cut action block:
    #: `build_config` wraps the loop in options, character stanzas and a target, and asking a
    #: user to find the block is asking them to do the parser's job.
    config: str = Field(..., min_length=1, max_length=100_000)


class RotationImportRead(BaseModel):
    """The steps a config was read as — a **preview**, not a saved rotation.

    Importing does not create anything. The steps come back for the user to look at and then
    save through the ordinary create endpoint, because a config that parses is not
    automatically a rotation someone wants: it may name a team member they meant to swap, or
    be the third variant of something they already have. Writing it for them would make
    "import" a verb with a side effect nobody asked for, and the undo is a delete.
    """

    steps: list[RotationStep]
    #: What the converter rewrote, in words. **Never silent**: a `for` becoming a `while 1` is
    #: a real change to the author's config, and a user should meet it here rather than in a
    #: damage number.
    rewrites: list[str] = []
