"""Schemas for saved builds and for the optimize/rank requests over them."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

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

    @computed_field
    @property
    def weapon_display(self) -> str | None:
        """`Freedom-Sworn · R1 · Lv90` — the weapon as a build actually holds it.

        Published rather than left to each client for the same reason `weapon_type_display`
        is. Three surfaces named a build's weapon — the saved list, the team slot picker and
        the optimize header — and all three printed the bare name, so a character showed
        `C6` while the weapon beside it showed nothing about how far it had been taken. Three
        format strings would have been three chances to disagree about a build's own gear.

        `None` when there is no weapon: `weapon_id` is nullable by design (OQ-T3), and a
        caller should render "no weapon" rather than a level for a weapon that is not there.

        Refinement before level because refinement is the scarcer fact — a Lv90 R1 and a Lv90
        R5 are different weapons in practice, and the R is what a reader is scanning for.
        """
        if self.weapon is None:
            return None
        return f"{self.weapon.name} · R{self.refinement} · Lv{self.weapon_level}"


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


class KernelSetBonus(BaseModel):
    """One tier of one set, in the terms the browser kernel reads."""

    set_id: int
    pieces_required: int
    #: Keyed by kernel quantity — `cryo_dmg_bonus`, not `FIGHT_PROP_ICE_ADD_HURT`.
    stats: dict[str, float]


class KernelHit(BaseModel):
    """The hit, resolved. `search.ts`'s `Hit` in its own spelling."""

    multiplier: float
    channel: str
    scaling_stat: str
    amplifying: str | None = None


class KernelTarget(BaseModel):
    """What the search scores against. `search.ts`'s `Target`."""

    level: int
    resistance: float
    def_reduction: float = 0.0
    def_ignore: float = 0.0


class SearchContextRead(BaseModel):
    """Everything `search.ts`'s `SearchContext` needs except the inventory.

    O.1. The inventory has its own home — `/artifacts/inventory`, which is ETag'd because the
    browser holds it across searches (OQ-S3). This is the per-build, per-hit half.

    **Published, not recomputed.** Every figure here is one the server already works out for
    `/explain`: the base from `build_assembler.base_contributions`, set bonuses from the same
    module, the hit through `resolve_talent_hit`. A second assembly of "what a build starts
    from" is how two definitions of it begin — which `build_assembler` records having already
    happened once.

    `base` is keyed by **kernel quantity**, which is the reason this endpoint exists at all:
    the kernel reads `base_atk` and the source spells it `FIGHT_PROP_BASE_ATTACK`, and the
    mapping between them decides what every stat means.
    """

    base: dict[str, float]
    hit: KernelHit
    target: KernelTarget
    character_level: int
    #: Which damage-bonus quantity this hit reads, e.g. `cryo_dmg_bonus`. The kernel needs it
    #: named because it sums that one quantity and ignores the other seven.
    dmg_bonus_quantity: str
    set_bonuses: list[KernelSetBonus]


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
    #: Every resolved stat total, keyed by quantity — `{"atk": 2431.7, "crit_rate": 0.624}`.
    #:
    #: **The value the chain acts on, which `stats` above cannot be added up to reach.** A
    #: contribution is an input: `base_atk`, `atk_pct` and `flat_atk` compose as
    #: `base * (1 + pct) + flat`, and `StatAccountRead.sum_of_parts` says in its own docstring
    #: that it "is not necessarily the stat". A client that summed the parts would be a second
    #: implementation of the damage chain, and a wrong one — which is why this is published
    #: rather than left to be derived.
    #:
    #: Resolved by the same evaluator and under the same scope as `damage`, so the number and
    #: the stats behind it always describe one build.
    totals: dict[str, float] = {}
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


class CalibrationRequest(BaseModel):
    """Body for `POST /builds/{id}/calibrate` (R.3).

    One calibration per **4-piece state**. `RESEARCH_conditional_sets.md`: every 4-piece bonus
    in the game is conditional, so only a run with the set equipped can hold it — and R.2
    measured the cost of not doing so at **15–25 % understated**.
    """

    rotation_id: str
    #: The catalogue id of the 4-piece set to equip, or `None` for the state where a
    #: combination reaches no 4-piece. Not the gcsim key — the caller works in catalogue ids
    #: and this resolves them, so a client never has to know gcsim's spelling.
    artifact_set_id: str | None = None
    #: Catalogue ids of sets to equip at **two** pieces, for a 2+2 combination. At most two.
    #:
    #: Equipped rather than left to the caller's stat pool because **nine of the sixty**
    #: 2-piece bonuses are conditional, six of them ability-scoped — Noblesse Oblige's burst
    #: +20 %, Marechaussee Hunter's normal/charged +15 % — which no flat stat pool can express.
    #: Owner ruling 1 (2026-08-28, `docs/DECISIONS.md`) calibrates them rather than deriving
    #: them from `param_list`, which is the fabricated-citation failure this repo legislates
    #: against.
    #:
    #: Mutually exclusive with `artifact_set_id`: five slots cannot hold both.
    two_piece_set_ids: list[str] = Field(default_factory=list, max_length=2)
    #: Artifact-borne Energy Recharge to calibrate at, as a fraction.
    #:
    #: **Not zero, and that is the point.** ER is an artifact stat, so a zero-ER calibration
    #: runs at the character's base ER and lands on a different burst count — measured at 2
    #: against a real candidate's 3 (`RESEARCH_recipe_risks.md` §1).
    energy_recharge: float = Field(0.30, ge=0.0, le=4.0)
    #: What the probe perturbs, and by how much — **all three scaling stats, by different
    #: amounts**.
    #:
    #: This moved exactly one stat (`def%`) until 2026-08-31, on the reasoning that
    #: `resolveConversions` cannot separate two stats that move *together*. True, but the
    #: constraint is that they must not move by the **same factor**, not that only one may
    #: move — and a one-stat probe can only ever resolve conversions *from that stat*. Every
    #: ATK- or HP-derived conversion was structurally unresolvable, which on an ATK-scaling
    #: character is most of them.
    #:
    #: Distinct deltas make a collision unlikely rather than impossible: a stat's ratio is
    #: `1 + base * delta / total`, so two stats can still coincide. That is safe rather than
    #: wrong — the matcher resolves a term only when **exactly one** stat's ratio matches, so
    #: a collision leaves the term unresolved exactly as before.
    probe_deltas: dict[str, float] = Field(
        default_factory=lambda: {"atk%": 0.50, "hp%": 0.30, "def%": 0.70},
    )

    @field_validator("probe_deltas")
    @classmethod
    def _probe_moves_distinctly(cls, value: dict[str, float]) -> dict[str, float]:
        """Known stats, positive, and no two by the same amount."""
        allowed = {"atk%", "hp%", "def%"}
        unknown = set(value) - allowed
        if unknown:
            msg = f"probe_deltas may only name {sorted(allowed)}; got {sorted(unknown)}"
            raise ValueError(msg)
        if not value:
            msg = "probe_deltas must move at least one stat, or no conversion can be resolved"
            raise ValueError(msg)
        if any(delta <= 0 for delta in value.values()):
            msg = "every probe delta must be positive; a stat that does not move tells nothing"
            raise ValueError(msg)
        if len(set(value.values())) != len(value):
            # Two stats moved by the same amount are the case the one-stat design was
            # protecting against, and the one this must still refuse.
            msg = f"probe deltas must differ from each other; got {value}"
            raise ValueError(msg)
        return value
    enemy_id: str | None = None
    iterations: int = Field(100, ge=1, le=1000)


class CalibrationConfigs(BaseModel):
    """The two configs a recipe is built from.

    The browser runs both through `sample()`: the first becomes the recipe, and the difference
    between them identifies what each frozen term was converted from.
    """

    #: The calibration itself — one 4-piece set, one ER, no other stat.
    baseline: str
    #: The same, with the scaling stats moved by different amounts.
    probe: str
    #: Echoed so a caller can key its cache without re-deriving what it asked for.
    artifact_set_id: str | None
    #: Echoed for the same reason. A 2+2 state is keyed by **both** sets, and a cache that
    #: keyed only the first would serve one pair's recipe for another's.
    two_piece_set_ids: list[str] = Field(default_factory=list)
    energy_recharge: float
    #: What the probe moved, so a caller can say why a conversion resolved or did not.
    probe_deltas: dict[str, float]
    #: The same characters as `characters`, in the same order, as a player reads them.
    #:
    #: gcsim's keys are `kaedeharakazuha`; a damage-share row wants "Kaedehara Kazuha". Sent
    #: rather than prettified client-side because no rule turns one into the other.
    character_names: list[str] = []
    #: The gcsim keys this config declares, **in the order it declares them**.
    #:
    #: gcsim's aggregate reports `character_actions` as a positional list with no names in it,
    #: so a caller reading per-character instance counts has nothing to label them with. Read
    #: off the emitted config by `gcsim_config.character_order` rather than rebuilt, because a
    #: parallel construction that drifted would attribute one character's instability to
    #: another — a warning naming the wrong person, which is worse than no warning.
    characters: list[str] = Field(default_factory=list)


class GcsimComparisonRequest(BaseModel):
    """Body for `POST /builds/{id}/compare-weapons/gcsim` (W.6).

    **`rotation_id` is required and has no default.** A rotation belongs to a *team*, and a
    build can sit in several teams each with several rotations, so there is no rotation this
    endpoint could pick on its own. Inventing one would make the ranking an answer about a
    rotation the user never wrote — which is the same objection that closed Chunk I's
    optimization half.
    """

    rotation_id: str
    #: Candidate weapons by catalogue id. Unlike the fast tier this does **not** silently add
    #: the worn weapon: it is returned separately as `equipped`, because a simulated baseline
    #: costs a full gcsim run and a caller comparing against nothing worn should not pay for
    #: one it did not ask for.
    weapon_ids: list[str] = Field(..., min_length=1)
    #: Monte Carlo iterations per candidate. The cost is linear and real — ~4.9 s per config
    #: per 100 iterations, measured — and the standard error falls as 1/sqrt(n), so this trades
    #: wall time for separability. See `docs/DESIGN_weapon_passives.md` §4.
    iterations: int = Field(100, ge=1, le=1000)
    #: Which enemy to simulate against, or null for gcsim's default target. A rotation carries
    #: no enemy of its own — it is a team's action list, not a scenario — so this is the
    #: caller's to state rather than something to be inferred from the rotation.
    enemy_id: str | None = None


class GcsimCandidateConfig(BaseModel):
    """One candidate, and the config that simulates it."""

    weapon_id: str
    name: str
    #: Complete gcsim config text. The browser runs this; the server never does.
    config: str


class RefusedCandidate(BaseModel):
    """A candidate that could not be turned into a config, and why.

    **Reported, never dropped.** A silently omitted candidate is a ranking that is missing a
    weapon the user asked about, presented as though it had considered it — and the omission
    is invisible precisely because the result still looks like a complete answer.
    """

    weapon_id: str
    reason: str


class GcsimComparisonConfigs(BaseModel):
    """What the browser needs to run a gcsim weapon comparison.

    **The server emits configs; it does not simulate.** `RESEARCH_gcsim_embed.md` §6 put gcsim
    in the browser, and W.4 measured a full sword pool at ~96 s across four workers — that is
    a job on the user's machine, not a request a server should hold open.
    """

    #: The worn weapon's config, or null when the build has no weapon. Rendered separately
    #: from the candidates because it is the thing they are being compared *to*.
    equipped: GcsimCandidateConfig | None
    candidates: list[GcsimCandidateConfig]
    refused: list[RefusedCandidate] = []
    iterations: int


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




class EquippedStatsRead(BaseModel):
    """One build's equipped artifacts, summed into the kernel's own quantities.

    **Narrow on purpose.** The browser already has a translation-free path to *every* artifact
    via `/artifacts/inventory`, and widening that payload with a build binding would be paid
    for across a 2,370-piece inventory to answer a question about five pieces. This is the five.

    Summed rather than listed, because every consumer wants the total: `evaluateRecipe` takes
    one number per quantity, and a caller re-summing five pools is a second place for the
    vocabulary to be got wrong.

    The translation is `stat_calculator._quantity_for_prop`, the same one `/artifacts/inventory`
    uses — which is the reason this is computed here rather than in TypeScript. A client-side
    mapping would be a second definition of what every stat means, with a silent failure mode: a
    mis-mapped substat produces a build optimal for a stat the character does not have.
    """

    #: Kernel quantity → summed value across the build's equipped pieces. Empty when nothing
    #: is equipped, which is a real state and not an error.
    stats: dict[str, float] = {}
    #: How many pieces contributed. Published so a caller can tell "no artifacts" from "five
    #: artifacts that happen to sum to nothing".
    pieces: int = 0
