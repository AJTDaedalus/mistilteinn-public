"""Schemas for saved builds and for the optimize/rank requests over them."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.formula.genshin import tags
from app.formula.genshin.damage import Amplifying, ScalingStat


class BuildCreate(BaseModel):
    """Body for `POST /builds`."""

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


class BuildUpdate(BaseModel):
    """Body for `PATCH /builds/{id}` — all fields optional."""

    weapon_id: str | None = None
    character_level: int | None = Field(None, ge=1, le=90)
    ascension_phase: int | None = Field(None, ge=0, le=6)
    weapon_level: int | None = Field(None, ge=1, le=90)
    refinement: int | None = Field(None, ge=1, le=5)
    constellation_level: int | None = Field(None, ge=0, le=6)
    talent_levels: dict[str, int] | None = None
    notes: str | None = None


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

    model_config = {"from_attributes": True}


class HitSpec(BaseModel):
    """The hit a search or a ranking is judged on — **supplied, not derived**.

    Deriving a talent's multiplier, scaling stat and damage channel from a character's
    stored talent rows is the kit corpus's job (Chunk H), and this repo has no kit corpus.
    Rather than parse a multiplier out of a `desc` string and present the result as though
    it came from the game, the caller states the hit. `TODO(chunk-H)`: a `talent` field that
    resolves this from the build's own character replaces it.
    """

    multiplier: float = Field(..., gt=0)
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


