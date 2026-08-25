"""Schemas for saved builds and for the optimize/rank requests over them."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.formula.genshin import tags
from app.formula.genshin.damage import Amplifying, ScalingStat
from app.models.enums import LEVELLED_TALENTS, MAX_TALENT_LEVEL, TalentType
from app.schemas.catalogue import CharacterSummary, WeaponSummary


def _validated_talents(levels: dict[str, int]) -> dict[str, int]:
    """Refuse a talent key nothing renders, or a level outside 1-15.

    The key check is the load-bearing one. `gcsim_config._talents` reads a missing key as
    level 1, so `{{"burst": 9}}` — which looks entirely reasonable — stores a 9 that nothing
    reads and simulates the burst at level 1. Nothing errors and the number is wrong, which
    is the failure this repo treats as non-negotiable.

    Checked against `LEVELLED_TALENTS`, the tuple the renderer iterates, rather than a list
    restated here. `alternate_sprint` is a real `TalentType` and is deliberately not in it:
    a sprint has no scaling table, so a level against it is a number nothing reads.
    """
    known = [str(talent) for talent in LEVELLED_TALENTS]
    unknown = sorted(set(levels) - set(known))
    if unknown:
        msg = (
            f"{unknown} are not talents that carry a level. The three are {known} — a key "
            f"outside them is stored and never read, and a misspelling of one is rendered "
            f"as level 1, so the talent simulates far weaker than it is."
        )
        raise ValueError(msg)
    out_of_range = sorted(k for k, v in levels.items() if not 1 <= v <= MAX_TALENT_LEVEL)
    if out_of_range:
        msg = (
            f"{out_of_range} are outside 1-{MAX_TALENT_LEVEL}. The cap is "
            f"{MAX_TALENT_LEVEL} rather than 10 because C3 and C5 each add three levels."
        )
        raise ValueError(msg)
    return levels


class BuildCreate(BaseModel):
    """Body for `POST /builds`.

    Unknown fields are refused rather than dropped, for the reason `BuildUpdate` records: a
    typo'd field name silently becomes "you did not set that", and the caller is told the
    write succeeded.
    """

    model_config = {"extra": "forbid"}

    character_id: str
    weapon_id: str | None = None
    character_level: int = Field(90, ge=1, le=90)
    #: Distinct from level because two builds at level 80 can differ by it.
    ascension_phase: int = Field(6, ge=0, le=6)
    weapon_level: int = Field(90, ge=1, le=90)
    refinement: int = Field(1, ge=1, le=5)
    constellation_level: int = Field(0, ge=0, le=6)
    #: Keyed by `TalentType` value. 1-15, because constellations raise the cap past 10.
    talent_levels: dict[str, int] = {}
    notes: str = ""

    @field_validator("talent_levels")
    @classmethod
    def _check_talents(cls, value: dict[str, int]) -> dict[str, int]:
        return _validated_talents(value)


class BuildUpdate(BaseModel):
    """Body for `PATCH /builds/{id}` — all fields optional.

    `character_id` is **not** here, and an unknown field is now a 422 rather than silently
    dropped (T.1). Those two facts go together: sending `{"character_id": …}` used to return
    200 having changed nothing, so a caller was told their edit succeeded when it had been
    discarded. Changing a build's character makes it a different build — and
    `uq_builds_owner_character` would collide with the existing one anyway — so the field
    stays out, and refusing it says so instead of pretending.
    """

    model_config = {"extra": "forbid"}

    weapon_id: str | None = None
    character_level: int | None = Field(None, ge=1, le=90)
    ascension_phase: int | None = Field(None, ge=0, le=6)
    weapon_level: int | None = Field(None, ge=1, le=90)
    refinement: int | None = Field(None, ge=1, le=5)
    constellation_level: int | None = Field(None, ge=0, le=6)
    talent_levels: dict[str, int] | None = None
    notes: str | None = None

    @field_validator("talent_levels")
    @classmethod
    def _check_talents(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        # `None` means "not in this patch", which is not the same as an empty dict.
        return None if value is None else _validated_talents(value)


class BuildOptions(BaseModel):
    """What an editor may offer for a build.

    The same guarantee `/rotations/options` gives (R.5): **the form offers exactly what the
    validator accepts.** `talents` is `LEVELLED_TALENTS`, which is both what `_validated_talents`
    checks against and what `gcsim_config._talents` renders — so a form built from this cannot
    produce a key that is stored and ignored, or one that renders as level 1.

    A list rather than a TypeScript union, because a generated type is erased at runtime and a
    page needs to *iterate* these to draw three inputs. Hardcoding them there would be a third
    copy of the tuple.
    """

    #: In the order gcsim's `talent=` field expects, which is the order to draw them in.
    talents: list[str]
    max_talent_level: int


class BuildRead(BaseModel):
    """One saved build."""

    id: str
    character_id: str | None
    weapon_id: str | None
    character_level: int
    ascension_phase: int
    weapon_level: int
    refinement: int
    constellation_level: int
    talent_levels: dict[str, int] = {}
    notes: str = ""
    #: The catalogue rows a list needs to draw a row, **beside** the ids rather than instead
    #: of them: a client that stores `character_id` keeps working, and these are for drawing
    #: rather than for referring.
    #:
    #: Explicitly `None` when absent rather than omitted — `weapon_id` is nullable by design
    #: (OQ-T3), and a missing key would read as "we did not look" rather than "there is no
    #: weapon". Reusing the catalogue's own summaries, so a build page and the catalogue page
    #: describe a character the same way.
    character: CharacterSummary | None = None
    weapon: WeaponSummary | None = None

    model_config = {"from_attributes": True}


class TalentRef(BaseModel):
    """Which hit of which talent, to be resolved against the build's own character.

    This closed the chunk-H marker here. `HitSpec` used to require a bare `multiplier`,
    because deriving one was the kit corpus's job and there is no kit corpus.
    `talent_scaling` parses the published rows now, and M.4 checked that parse against gcsim
    across 105 characters, so a caller can name the hit instead of typing 1.2091.
    """

    talent: TalentType
    #: The published label, e.g. `Cutting DMG` — the game's own wording, not an invented name.
    label: str = Field(..., min_length=1, max_length=200)
    #: Which hit under that label. `Low/High Plunge DMG` is two, and only an index separates
    #: them.
    index: int = Field(default=0, ge=0)


class HitSpec(BaseModel):
    """The hit a search or a ranking is judged on.

    **Either a `multiplier` or a `talent`, never both and never neither.** Naming the talent
    resolves the multiplier from the build's own character at its own talent level; giving a
    multiplier outright still works, because asking about a hypothetical hit is legitimate and
    the optimizer's fixtures do exactly that.

    **`channel` stays required either way.** The published table gives a multiplier and says
    nothing about which element the hit lands as — a normal attack is physical for most
    characters and not for a catalyst user, and infusions move it. Deriving it would be
    inventing a rule the data does not state.
    """

    multiplier: float | None = Field(default=None, gt=0)
    #: Resolved against the build. Mutually exclusive with `multiplier`.
    talent: TalentRef | None = None
    #: One of the seven visions or `physical`.
    channel: str
    #: What the multiplier scales off.
    scaling_stat: ScalingStat = ScalingStat.ATK
    #: Which attack this is — every stat read is resolved under it, so a scope-gated crit
    #: rate is visible exactly when it should be.
    #:
    #: **Required, with no default.** There is no "any scope": `stats.scoped` accepts one of
    #: seven and a hit is always one of them. Defaulting to `normal` would silently score a
    #: burst under normal-attack buffs, which is a wrong number that looks like a right one.
    scope: str
    #: Melt/vaporize, if this hit is amplified. Absent means no reaction.
    amplifying: Amplifying | None = None
    flat_damage: float = 0.0

    @model_validator(mode="after")
    def _exactly_one_source(self) -> HitSpec:
        """One of the two, never both.

        Both would mean the request states a multiplier *and* a talent that resolves to a
        different one, and whichever the server picked would silently contradict the other
        half of the same body. Neither leaves nothing to score.
        """
        if (self.multiplier is None) == (self.talent is None):
            msg = (
                "a hit needs exactly one of `multiplier` or `talent`. Both would let the "
                "request state two different numbers for one hit; neither leaves nothing "
                "to score."
            )
            raise ValueError(msg)
        return self

    @field_validator("channel")
    @classmethod
    def _known_channel(cls, value: str) -> str:
        if value not in tags.DAMAGE_CHANNELS:
            msg = f"{value!r} is not a damage channel; the eight are {tags.DAMAGE_CHANNELS}"
            raise ValueError(msg)
        return value

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        # Checked against `tags.SCOPES` rather than restated here: a second list would drift
        # from the one `stats.scoped` actually enforces, and the drift would show up as a
        # 500 from inside the damage chain.
        if value not in tags.SCOPES:
            msg = f"{value!r} is not an attack scope; the seven are {tags.SCOPES}"
            raise ValueError(msg)
        return value


class EnemySpec(BaseModel):
    """The target.

    `Enemy` requires **all eight** damage channels, because treating a missing one as 0%
    overstates every hit against it. Listing eight numbers on every request is not something
    to ask of a caller, so any channel `resistances` does not mention takes
    `default_resistance` — a **stated** default that appears in the schema and can be
    changed, rather than a silent zero.

    That distinction is the whole point: the first version of this documented a 10% default
    and passed `{}` straight through, so every request without an explicit eight-channel map
    was a 500 from inside the damage chain.
    """

    level: int = Field(90, ge=1)
    #: Per damage channel, as fractions — `0.1` is 10%. Negative is a weakness.
    resistances: dict[str, float] = {}
    #: Applied to every channel `resistances` omits. 10% is the ordinary trash-mob value.
    default_resistance: float = 0.1
    #: A stored profile to take level and resistances from instead. Wins over the above.
    enemy_profile_id: str | None = None

    @field_validator("resistances")
    @classmethod
    def _known_channels(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(value) - set(tags.DAMAGE_CHANNELS))
        if unknown:
            msg = f"{unknown} are not damage channels; the eight are {tags.DAMAGE_CHANNELS}"
            raise ValueError(msg)
        return value

    def resolved_resistances(self) -> dict[str, float]:
        """All eight channels, with the stated default filling whatever was not given."""
        return {
            channel: self.resistances.get(channel, self.default_resistance)
            for channel in tags.DAMAGE_CHANNELS
        }


class AvailableHitRead(BaseModel):
    """One hit a build can be asked about, in the terms `HitSpec.talent` takes.

    Offered from the **same parse** `resolve_talent_hit` uses, so a page built from this
    cannot name a hit the resolver then refuses — the picker-matches-validator guarantee this
    repo applies wherever a user chooses from a list.
    """

    talent: TalentType
    label: str
    index: int
    #: At this build's own talent level, so a page can show what it is choosing between.
    multiplier: float
    #: How many times it lands per use.
    hits: int
    #: True when it is one of several alternatives and only one of them happens.
    exclusive: bool


class ExplainRequest(BaseModel):
    """Body for `POST /builds/{id}/explain`.

    **No contributions in the body, deliberately.** The caller names artifacts by id and the
    server resolves them through the same `build_combination_log` the search and the ranker
    use. Accepting numbers from the client would make the explanation an account of whatever
    was posted rather than of the build, and an explanation of a lie is the one output where
    that would be hardest to notice.
    """

    hit: HitSpec
    enemy: EnemySpec
    #: The five pieces to explain. Omit to explain what is currently equipped.
    artifact_ids: list[str] | None = None
    #: When given, the explanation is a comparison against what is equipped — "why is this
    #: better" rather than "what is this made of".
    compare_to_equipped: bool = True
    #: Together these pull in a simulated run and its measured divergence. Both or neither:
    #: a context key with no ER cannot pick a bucket, and an ER with no key has no context to
    #: pick one from.
    context_key: str | None = None
    energy_recharge: float | None = None


class ContributionRead(BaseModel):
    """One value and where it came from."""

    quantity: str
    value: float
    source: str
    note: str = ""


class StatAccountRead(BaseModel):
    """One quantity and every contribution recorded against it."""

    quantity: str
    parts: list[ContributionRead]
    #: The **arithmetic sum of the parts**, which is not necessarily the stat: an additive
    #: pool agrees with the damage chain, `base * (1 + pct) + flat` does not. Named for what
    #: it is so no reader takes it for a total.
    sum_of_parts: float
    sources: list[str]


class SetEffectRead(BaseModel):
    """A set bonus that applied, in the catalogue's own words."""

    note: str
    #: Null when the catalogue publishes no text for it — never a paraphrase composed here.
    description: str | None
    contributions: list[ContributionRead]


class SimulationNoteRead(BaseModel):
    """What the retrieved run says, and how far it was from this build."""

    matched_bucket: int
    requested_bucket: int
    bucket_distance: int
    is_exact_bucket: bool
    dps_mean: float | None
    divergence_pct: float | None
    noise_floor: float | None
    exceeds_noise: bool | None
    #: One sentence a reader must not be able to miss — stated even at distance zero, because
    #: an exact *key* is not an exact *answer*.
    caveat: str


class UncitedRead(BaseModel):
    """Something the explanation could not attribute, reported rather than dropped."""

    what: str
    why: str


class StatDifferenceRead(BaseModel):
    """One quantity that differs between the proposal and what is equipped."""

    quantity: str
    equipped: float
    proposed: float
    delta: float
    gained: list[ContributionRead]
    lost: list[ContributionRead]


class ExplainResponse(BaseModel):
    """A build's account of itself, and optionally of what it improves on."""

    damage: float
    stats: list[StatAccountRead]
    set_effects: list[SetEffectRead]
    simulation: SimulationNoteRead | None = None
    #: Anything that could not be tied to a contribution, a run, or the catalogue. Listed
    #: rather than rendered anyway — a confident sentence with nothing behind it is the
    #: failure mode this repo has spent every chunk avoiding.
    uncited: list[UncitedRead] = []
    #: Null when nothing was compared against. Largest *relative* difference first: a
    #: quantity is only comparable with itself, so ranking by absolute size would order
    #: builds by which stats happen to be big numbers.
    differences: list[StatDifferenceRead] | None = None
    equipped_damage: float | None = None
    unchanged: list[str] | None = None


class CompareWeaponsRequest(BaseModel):
    """Body for `POST /builds/{id}/compare-weapons`."""

    hit: HitSpec
    enemy: EnemySpec
    #: Candidate weapons by catalogue id. The build's own weapon is always compared as the
    #: baseline whether or not it is listed — a marginal-value question measures against what
    #: is worn, so omitting it would leave nothing to be better than.
    weapon_ids: list[str] = Field(..., min_length=1)


class WeaponScoreRead(BaseModel):
    """One weapon's damage in this build, and what it changed."""

    weapon_id: str
    name: str
    damage: float
    delta: float
    delta_pct: float
    is_equipped: bool
    #: The contribution diff against the equipped weapon — the "why", not just the "how
    #: much". Empty for the equipped weapon itself.
    differences: list[StatDifferenceRead] = []


class UnmodelledPassiveRead(BaseModel):
    """A passive stored in the catalogue that this comparison does not apply."""

    weapon_id: str
    weapon_name: str
    passive_name: str
    text: str
    #: Which refinement step the text was read at — the build's own, because a candidate the
    #: user does not own has no refinement of its own. Reported so nobody infers otherwise.
    refinement: int


class CompareWeaponsResponse(BaseModel):
    """Every candidate scored in one build, best first — and what the ranking cannot see."""

    weapons: list[WeaponScoreRead]
    equipped_weapon_id: str
    #: **Not a footnote.** Weapon passives are imported but not yet applied (Chunk H), and
    #: for weapons the unmodelled part is frequently the entire reason to equip one. A
    #: non-empty list means the ordering above may be *wrong*, not merely imprecise.
    unmodelled_passives: list[UnmodelledPassiveRead] = []
    #: True only when every candidate's effect is modelled. All-or-nothing: one unapplied
    #: passive is enough to reorder the list.
    is_complete: bool
    #: One sentence naming what the ranking does not know. A caller that shows the numbers
    #: without this is publishing a ranking this API does not claim to have made.
    caveat: str


