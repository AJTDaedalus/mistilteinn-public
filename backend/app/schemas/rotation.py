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
from app.services.gcsim_keys import all_offerable_actions, authorable_actions

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
    #:
    #: **The superset**, not the base ten. Kit variants are actions here
    #: (`DESIGN_rotation_builder_gui.md` §3), and publishing the ten while accepting fifteen
    #: gave a generated TypeScript client a union that refused `skill_hold` — caught by the
    #: frontend failing to compile, which is the drift this line exists to prevent and had
    #: stopped preventing the moment the validator moved and this did not.
    action: str = Field(..., json_schema_extra={"enum": list(all_offerable_actions())})
    #: `attack ×3` compiles to gcsim's own `attack:3`.
    repeat: int = Field(default=1, ge=1, le=MAX_REPEAT)
    #: The user's own label for this step. Never interpreted.
    note: str = Field(default="", max_length=200)
    #: The chunk this step belongs to, or `""` for a step standing on its own.
    #:
    #: `DECISIONS.md` §27. A group repeats; the compiler **unrolls** it before anything else
    #: sees it, so gcsim receives character-for-character what it received before groups
    #: existed. An id rather than a nesting structure because the model stays a flat ordered
    #: list — which is what makes `unroll` a function over a list rather than a tree walk.
    group: str = Field(default="", max_length=64)
    #: How many times this step's group repeats. Carried on every member and required to
    #: agree, so `unroll` cannot silently pick one of two answers.
    #:
    #: Meaningless without `group`, and refused there rather than ignored — a repeat count on
    #: an ungrouped step is a user believing something is happening that is not.
    group_repeat: int = Field(default=1, ge=1, le=MAX_REPEAT)

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
        allowed = all_offerable_actions()
        if value not in allowed:
            msg = (
                f"{value!r} is not an action a rotation step can name. The base ten are "
                f"{list(authorable_actions())}, plus the kit variants some characters have: "
                f"{[a for a in allowed if a not in authorable_actions()]}. `swap` is implicit "
                f"— gcsim inserts one when the next character is not active — and "
                f"`wait`/`delay` are timing controls this model deliberately does not expose."
            )
            raise ValueError(msg)
        return value


class ActionOffer(BaseModel):
    """One move a particular character can be given, as a button can draw it.

    **Composed here rather than assembled by the client**, for the reason `/options` exists at
    all: the correspondence between gcsim's actions and the catalogue's talents is one thing
    (`gcsim_keys`) and it should have one owner.
    """

    #: What a step stores. `"skill"`, or `"skill_hold"` for a variant.
    #:
    #: Published as the **same enum** `RotationStep.action` carries, so a generated client
    #: types an offer and a step alike. Without it the offer is a bare `string` and the
    #: TypeScript that feeds one into the other does not compile — which is how this was
    #: found, and is the type system making the same guarantee the validator does.
    action: str = Field(..., json_schema_extra={"enum": list(all_offerable_actions())})
    #: The move without its variant — `"skill"` for both of the above. What the readiness gate
    #: names, and what the sprite belongs to. Always one of the base ten.
    base: str = Field(..., json_schema_extra={"enum": list(authorable_actions())})
    #: `"hold"`, `"short_hold"`, `"recast"`, or `None` for the plain form. Drives the badge and
    #: nothing else: the compiler reads `action`, never this.
    variant: str | None = None
    #: The character's own name for it — "All Schemes to Know". Falls back to `base` for the
    #: seven actions that are not talents, because calling a charged attack "Akara" would be a
    #: wrong name rather than a missing one (`gcsim_keys._ACTION_TALENTS`).
    name: str
    #: The game's sprite for the talent, or `None` where there is none. Only the three talents
    #: have one; the other seven are drawn as words (owner, 2026-08-30).
    icon: str | None = None


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
    #: The vision's emblem basename, from `element_symbols` — the one place that decides.
    #:
    #: Published for the same reason as `icon`: the owner wants the vision shown as its emblem
    #: rather than the word "Hydro", and a client building `f"{element}.webp"` would be a
    #: second copy of that mapping which silently 404s the moment a patch adds a vision.
    element_icon: str | None = None
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
    #: Every move **this character** can be given, in the order a palette should draw them.
    #:
    #: Per character, not one list for everyone, because a hold-E is a different move from a
    #: tap-E and only 55 of gcsim's 117 characters have one. The guarantee `RotationOptions`
    #: has always made — *the picker offers exactly what the validator accepts* — is now made
    #: per character, which is a stronger claim and an easier one to break, so it has a test
    #: per character rather than one assertion over the whole list.
    actions: list[ActionOffer] = []


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


def check_groups(steps: list[RotationStep]) -> list[RotationStep]:
    """Refuse a group that is split apart or disagrees with itself.

    Two rules, and each closes a way `unroll` could otherwise produce something nobody wrote:

    - **Contiguous.** A group is a *chunk* of the rotation. If its members were scattered,
      unrolling would either reorder the user's steps or repeat them in several places, and
      both are the editor inventing a rotation.
    - **One repeat count.** Every member carries `group_repeat` and they must agree. `unroll`
      reads the first member's; without this it would be picking one of two answers silently.

    A `group_repeat` above 1 on a step with no group is refused for the same reason: it is a
    number the user set that nothing would read.
    """
    seen: set[str] = set()
    previous = ""
    for index, step in enumerate(steps):
        if not step.group:
            if step.group_repeat != 1:
                msg = (
                    f"step {index + 1} sets a group repeat of {step.group_repeat} but belongs "
                    f"to no group, so nothing would repeat it. Put it in a group, or leave "
                    f"the repeat at 1."
                )
                raise ValueError(msg)
            previous = ""
            continue
        if step.group != previous and step.group in seen:
            msg = (
                f"group {step.group!r} appears in more than one place (step {index + 1}). A "
                f"group is a chunk of the rotation and repeats where it stands; scattered "
                f"members would have to be gathered or repeated somewhere the user did not "
                f"write."
            )
            raise ValueError(msg)
        seen.add(step.group)
        previous = step.group
    by_group: dict[str, set[int]] = {}
    for step in steps:
        if step.group:
            by_group.setdefault(step.group, set()).add(step.group_repeat)
    disagreeing = sorted(g for g, repeats in by_group.items() if len(repeats) > 1)
    if disagreeing:
        msg = (
            f"these groups disagree about how many times they repeat: {disagreeing}. Every "
            f"step in a group carries the count and they must match, because the compiler "
            f"reads one of them."
        )
        raise ValueError(msg)
    return steps


class RotationCreate(BaseModel):
    """Body for `POST /rotations`."""

    name: str = Field(..., min_length=1, max_length=200)
    team_id: str
    steps: list[RotationStep] = Field(default_factory=list, max_length=MAX_STEPS)
    description: str = Field(default="", max_length=2000)

    _groups = field_validator("steps")(check_groups)


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

    @field_validator("steps")
    @classmethod
    def _groups(cls, value: list[RotationStep] | None) -> list[RotationStep] | None:
        return None if value is None else check_groups(value)
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


class RotationPreviewRequest(BaseModel):
    """Body for `POST /rotations/preview` — compile steps that have not been saved.

    **Why this exists rather than the editor compiling client-side.** `POST /{id}/compile`
    reads the *stored* rotation, so an editor showing a live preview of unsaved work would
    either show the saved version — worse than no preview, because it looks current — or grow
    a second compiler in TypeScript. The second compiler is the real hazard: the gates are what
    stop gcsim's two silent failures (`DESIGN_rotation.md` §3.4), and two implementations of
    them would eventually disagree about a config nobody reads.

    So the steps come here and the **same** `compile_rotation` answers.
    """

    _groups = field_validator("steps")(check_groups)

    #: Ask for a **runnable** config rather than the action block alone.
    #:
    #: The block is what an author reads — it is the gates and the loop, and it is what
    #: `/{id}/compile` has always returned. It is *not* something gcsim can run: there is no
    #: `options`, no character, no weapon, no target. The builder's "Run once" needs the whole
    #: thing, and assembling it here rather than in TypeScript is the same argument this schema
    #: already makes about the compiler — one implementation, not two that drift.
    runnable: bool = False
    #: The team the steps are validated against. A step naming someone not on it is refused,
    #: exactly as it is on save — a preview that accepted more than the save would is a
    #: preview of something that cannot exist.
    team_id: str
    steps: list[RotationStep] = Field(default_factory=list, max_length=MAX_STEPS)


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
