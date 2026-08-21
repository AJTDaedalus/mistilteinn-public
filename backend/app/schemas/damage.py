"""Pydantic schemas for damage calculation API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import Element
from app.schemas.disc import SubstatInput
from app.services.buff_resolver import _COMBAT_STATS, _DMG_BONUS_STATS, _STAT_TO_INPUT
from app.services.modifiers import (
    AttackScope,
    Condition,
    DuplicateCustomBuffError,
    UnslugifiableCustomBuffError,
    assert_addressable_custom_buffs,
)

_CONDITION_VALUES: frozenset[str] = frozenset(c.value for c in Condition)
_SCOPE_VALUES: frozenset[str] = frozenset(s.value for s in AttackScope)

# Shared descriptions for the fluxed_element contract (DESIGN_remielle.md §5.3).
# Attribute Flux is a Lumiflux-only mechanic (Remielle et al.) — every other
# agent's fluxed_element is always null and unaffected by this field.
_FLUXED_ELEMENT_REQUEST_DESC = (
    "Attribute Flux override, Lumiflux agents only (e.g. Remielle). When set, "
    "this element is used for DMG%-bucket selection and enemy-RES targeting "
    "instead of the auto-derived value (the element of the next team slot, "
    "cyclic). With no team (solo calc), a solo/empty team, or a non-Lumiflux "
    "agent, the derived value is null and the agent deals pure Lumiflux "
    "damage: no attribute DMG% bonus applies and the enemy RES contribution "
    "is a neutral 0. A missing team is therefore the documented default, "
    "not a calc bug."
)
_FLUXED_ELEMENT_RESPONSE_DESC = (
    "The element actually used for this calc's DMG%-bucket/RES targeting "
    "(override if provided, else the derived value). Null for non-Lumiflux "
    "agents and for a Lumiflux agent with no team / a solo team — see the "
    "request field's description for the no-team default."
)


#: Most stage buffs one request may carry.
#
# A stage rotates a handful of effects, not fifty — but `custom_buffs` now rides on the
# optimizer and rank requests, where every synthesized `Modifier` is re-resolved across
# the whole combo enumeration. Without a cap an authenticated client can multiply the
# search's work with one field. Matches `_MAX_BUFFS_PER_PRESET`, so a preset that saves
# is always a preset that can be applied.
MAX_CUSTOM_BUFFS = 50

#: Stat keys a custom buff may target.
#
# Imported from the resolver rather than restated, exactly as
# `validate_kits.RESOLVABLE_STATS` is: a stat outside these three buckets falls through
# `resolve_modifiers`'s `else` branch, so the buff is accepted, displayed, and then
# silently ignored by the calc — the one failure mode this feature must not have.
#
# `atk` / `def` / `hp` are absent because the resolver never had them, not because
# anything subtracts them: they are `StatType` members — the **disc main/substat**
# vocabulary — and no buff consumer reads them. Measured end to end in
# `docs/RESEARCH_custom_buff_stats.md` (Task B2): they moved no damage number under any of
# 13 probe contexts, while `flat_atk` / `atk_pct` / `final_flat_atk` all did. Which is why
# this is built from the resolver and not from `StatType` — a picker built from the latter
# would offer three controls labelled ATK, DEF and HP that do nothing at all.
CUSTOM_BUFF_STATS: frozenset[str] = frozenset(
    set(_STAT_TO_INPUT) | set(_DMG_BONUS_STATS) | set(_COMBAT_STATS)
)


class StoredCustomBuff(BaseModel):
    """The *shape* of a custom buff, with none of the vocabulary checks.

    Read model only, for data already sitting in a `buff_presets` row (#64). The
    vocabulary a stage buff draws on — `CUSTOM_BUFF_STATS`, `Condition`, `AttackScope` —
    is the engine's, and the engine's changes: a stat key gets renamed and every preset
    saved against the old name becomes unvalidatable. Validating on *read* would then turn
    a stale saved row into a 500 on `GET /buff-presets`, breaking the panel for that user
    with no way back — they cannot even see the offending preset to delete it.

    So the strictness is placed where it belongs: **strict on write** (`CustomBuff`, where
    the user is authoring and can fix it), **permissive on read** (here), **loud on use**
    (applying a stale preset copies its buffs into a request, which 422s naming the stat).
    A stale preset stays visible, deletable and honest about what it holds.
    """

    label: str = Field(max_length=100)
    stat: str
    value: int
    target: Literal["self", "team"] = "team"
    conditions: list[str] = Field(default_factory=lambda: ["always"])
    scopes: list[str] = Field(default_factory=lambda: ["all"])
    max_stacks: int = 1


class CustomBuff(BaseModel):
    """One user-authored buff — a Deadly Assault / Shiyu stage buff, typically.

    DESIGN_buff_context.md §2.3. A stage buff belongs to the *encounter* being
    evaluated, not to a build, which is why it rides on the request-scoped
    :class:`BuffContext` rather than on `builds`.

    B3 synthesises these into ordinary ``Modifier`` rows (``source=EXTERNAL``,
    ``source_label=f"custom:{slug}"``), so condition gating, scope filtering, stacking,
    attribution and ``disabled_buffs`` all work on them with no additional code. This
    schema's whole job is to make sure nothing reaches that synthesis step that the calc
    would then quietly drop.

    Every field is validated against the engine's own vocabulary, and an unknown value is
    a 422 rather than a silently skipped buff: a user who authors a stage buff and sees
    their numbers not move has no way to tell "the buff did nothing" from "the buff is
    not modelled".
    """

    label: str = Field(min_length=1, max_length=100, description='e.g. "DA Stage 3: Ice DMG"')
    stat: str = Field(description="Stat key; must be one the buff resolver reads")
    value: int = Field(description="Basis points; may be negative for a debuff")
    target: Literal["self", "team"] = "team"
    conditions: list[str] = Field(default_factory=lambda: ["always"])
    scopes: list[str] = Field(default_factory=lambda: ["all"])
    max_stacks: int = Field(default=1, ge=1, le=100)

    @field_validator("stat")
    @classmethod
    def _known_stat(cls, v: str) -> str:
        if v not in CUSTOM_BUFF_STATS:
            hint = ""
            if v in {"atk", "def", "hp"}:
                hint = (
                    f" — '{v}' is a disc main/substat key, not a buff key; "
                    f"use 'flat_{v}', '{v}_pct' or 'final_flat_{v}'"
                )
            raise ValueError(f"unknown buff stat '{v}'{hint}")
        return v

    @field_validator("conditions")
    @classmethod
    def _known_conditions(cls, v: list[str]) -> list[str]:
        unknown = [c for c in v if c not in _CONDITION_VALUES]
        if unknown:
            raise ValueError(f"unknown condition(s): {', '.join(unknown)}")
        return v

    @field_validator("scopes")
    @classmethod
    def _known_scopes(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in _SCOPE_VALUES]
        if unknown:
            raise ValueError(f"unknown scope(s): {', '.join(unknown)}")
        return v


class CustomBuffCarrier(BaseModel):
    """Mixin for any request body that accepts ``custom_buffs``.

    ``BuffContext`` is the natural home for the field, but the optimizer and rank
    requests never adopted ``BuffContext`` — they carry the same buff state as flat
    fields (Task B5a). Rather than restate the field and its validator on each of them,
    they inherit it here: a stage buff must mean the same thing, and be rejected for the
    same reasons, on every surface that accepts one. Two copies of this validator is a
    validator that agrees today and drifts later — the same argument that moved
    ``slugify`` into one place in B3.
    """

    custom_buffs: list[CustomBuff] = Field(
        default_factory=list,
        max_length=MAX_CUSTOM_BUFFS,
        description=(
            "User-authored stage / Deadly-Assault buffs for THIS request (#64). "
            "Synthesized into ordinary Modifier rows, so conditions, scopes, stacking, "
            "attribution and disabled_buffs all apply to them unchanged. Addressable in "
            "disabled_buffs as 'custom:<slug-of-label>'."
        ),
    )

    @model_validator(mode="after")
    def _addressable_custom_buff_labels(self) -> CustomBuffCarrier:
        """Every custom buff must slugify to an id, and to its own.

        The synthesiser enforces the same rule -- this calls the same function -- but
        raising there surfaces as a 500. Catching it here makes it a 422 naming the
        offending labels, which is what the user can act on.

        Duplicates are rejected rather than suffixed: a suffix would make the id depend
        on list order, so reordering the list would silently move which buff a
        ``disabled_buffs`` entry refers to — and that id has to stay stable across
        requests or a stage buff switched off comes back on the next calculation.

        An all-punctuation label (``"!!!"``, ``"🔥"``) clears ``min_length=1`` but
        slugifies to nothing, which is the same failure wearing a different hat: the id
        ``"custom:"`` names no particular buff.
        """
        try:
            assert_addressable_custom_buffs(self.custom_buffs)
        except (UnslugifiableCustomBuffError, DuplicateCustomBuffError) as exc:
            raise ValueError(str(exc)) from exc
        return self


class BuffContext(CustomBuffCarrier):
    """User-toggled buff state for one calculation, sourced from the request only.

    DESIGN_buff_context.md §2.1 — the server resolves buff state from the
    request and only from the request; no endpoint reads
    ``build.active_conditions`` / ``build.stack_counts`` / ``build.disabled_buffs``
    during a calculation. The three ``builds`` JSONB columns still exist and
    still store data, but their role is now "defaults the client reads to
    seed this object when a build loads" — never a fallback the server
    consults mid-calculation.

    ``custom_buffs`` carries the stage/Deadly-Assault buffs of #64. They are synthesized
    into ordinary ``Modifier`` rows in ``build_snapshot_from_db``, so nothing downstream
    treats them as a special case (DESIGN_buff_context.md §2.3).
    """

    active_conditions: list[str] = Field(default_factory=lambda: ["always"])
    stack_counts: dict[str, int] = Field(default_factory=dict)
    disabled_buffs: list[str] = Field(default_factory=list)


class StandardDamageRequest(BaseModel):
    """Input for a standard damage calculation."""

    # Attack parameters
    scaling_stat: int = Field(description="Stat the attack scales off (usually total ATK)")
    multiplier: int = Field(description="Attack multiplier in basis points (3120 = 31.20%)")

    # Damage bonuses (basis points) — sum of elemental DMG%, generic DMG%, skill-type DMG%, etc.
    dmg_bonuses: list[int] = Field(default_factory=list)

    # Crit
    crit_rate: int = Field(default=500, description="Crit rate in basis points (500 = 5%)")
    crit_dmg: int = Field(default=5000, description="Crit DMG in basis points (5000 = 50%)")
    crit_mode: str = Field(default="expected", description="expected, crit, or no_crit")

    # Defense calculation
    attacker_level: int = Field(default=60, ge=1, le=60)
    enemy_base_def: int = Field(default=50, ge=0)
    enemy_level: int = Field(default=60, ge=1, le=60)
    pen_ratio: int = Field(default=0, description="PEN Ratio in basis points")
    pen_flat: int = Field(default=0, description="Flat PEN")
    def_ignore: int = Field(default=0, description="DEF ignore in basis points")

    # Resistance
    enemy_res: int = Field(default=0, description="Enemy elemental RES in basis points")
    res_reduction: int = Field(default=0, description="RES reduction in basis points")
    res_ignore: int = Field(default=0, description="RES ignore in basis points")

    # Vulnerability / damage taken
    vulnerability_bonuses: list[int] = Field(default_factory=list)

    # Stun
    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000, description="Stun DMG multiplier in basis points")


class StandardDamageResponse(BaseModel):
    """Result of a standard damage calculation."""

    total: int
    base_dmg: int
    boost_mult: int
    crit_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int


class AnomalyDamageRequest(BaseModel):
    """Input for an anomaly damage calculation."""

    anomaly_type: str = Field(description="burn, shock, corruption, shatter, or assault")
    atk: int = Field(description="Total ATK stat")
    anomaly_proficiency: int = Field(default=0, description="Raw anomaly proficiency value")
    attacker_level: int = Field(default=60, ge=1, le=60)

    dmg_bonuses: list[int] = Field(default_factory=list)
    anomaly_dmg_bonus: int = Field(default=0, description="Anomaly DMG bonus in basis points")

    enemy_base_def: int = Field(default=50, ge=0)
    enemy_level: int = Field(default=60, ge=1, le=60)
    pen_ratio: int = Field(default=0)
    pen_flat: int = Field(default=0)
    def_ignore: int = Field(default=0)

    enemy_res: int = Field(default=0)
    res_reduction: int = Field(default=0)
    res_ignore: int = Field(default=0)

    vulnerability_bonuses: list[int] = Field(default_factory=list)

    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000)

    procs: int | None = Field(default=None, description="Override number of procs")


class AnomalyDamageResponse(BaseModel):
    """Result of an anomaly damage calculation."""

    per_proc: int
    total: int
    procs: int
    base_dmg: int
    boost_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int
    anomaly_prof_mult: int
    level_mult: int
    anomaly_boost_mult: int


class CompareRequest(BaseModel):
    """Compare two standard damage calculations side by side."""

    a: StandardDamageRequest
    b: StandardDamageRequest


class CompareResponse(BaseModel):
    """Side-by-side comparison result."""

    a: StandardDamageResponse
    b: StandardDamageResponse
    diff: int = Field(description="b.total - a.total")
    diff_pct: float = Field(description="Percentage difference: (b-a)/a * 100")


# ---------------------------------------------------------------------------
# Build-aware damage calculation (uses DB models + modifier JSONs)
# ---------------------------------------------------------------------------


class BuildDamageRequest(BaseModel):
    """Calculate damage for a saved build against a specific attack and enemy."""

    build_id: str = Field(description="UUID of the build")
    attack_id: str = Field(description="UUID of the attack to evaluate")
    enemy_profile_id: str = Field(description="UUID of the enemy profile")

    buff_context: BuffContext = Field(
        default_factory=BuffContext,
        description="Run-level buff state (DESIGN_buff_context.md §2.1).",
    )
    # deprecated: superseded by buff_context (Task A4). No known caller sends
    # these directly (grep of frontend/src found none) -- unread by the
    # endpoint, kept only so an old request body doesn't 422 on an unknown
    # field. Remove once Phase A ships and no caller is found using them.
    active_conditions: list[str] = Field(
        default_factory=lambda: ["always"],
        description="Deprecated, unread -- use buff_context.active_conditions.",
    )
    stack_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Deprecated, unread -- use buff_context.stack_counts.",
    )

    # W-Engine refinement (1-5)
    refinement: int = Field(default=1, ge=1, le=5)

    # Mindscape level to include modifiers for (0-6)
    mindscape_level: int | None = Field(
        default=None,
        description="Override mindscape level (default: use build's mindscape_level)",
    )

    # Crit mode
    crit_mode: str = Field(default="expected", description="expected, crit, or no_crit")

    # Stun state
    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000)

    # Skill level for the attack (1-12, used with damage_growth)
    skill_level: int | None = Field(
        default=None,
        description="Skill level for multiplier calc (default: from build.skill_levels)",
    )

    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_REQUEST_DESC,
    )

    @field_validator("fluxed_element")
    @classmethod
    def _validate_fluxed_element(cls, value: str | None) -> str | None:
        """Reject anything that is not a real element (F4, hardening Task 18).

        Applied to every REQUEST that carries this field, because hardening
        Task 17 made the value reach the damage chain: an unvalidated string
        silently selects no DMG% bucket and a neutral 0 enemy RES, then gets
        echoed back as "the element actually used". `lumiflux` is rejected
        alongside the nonsense values -- a Lumiflux build has no
        `lumiflux_dmg` bucket by design (DESIGN 4.2).
        """
        if value is None:
            return None
        valid = {e.value for e in Element} - {Element.LUMIFLUX.value}
        if value not in valid:
            raise ValueError(
                f"fluxed_element must be one of {sorted(valid)}, got {value!r}"
            )
        return value


class BuildDamageResponse(BaseModel):
    """Damage result with full breakdown and resolved stats."""

    # Damage result
    total: int
    base_dmg: int
    boost_mult: int
    crit_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int

    # Resolved stats used in the calc
    total_atk: int
    total_crit_rate: int
    total_crit_dmg: int
    total_pen_ratio: int

    # Sheer Damage (Rupture agents only). Non-null when this hit used the Sheer
    # path: effective scaling stat is SheerForce, not ATK. def_mult=10000 (no
    # DEF zone). Frontend should label the scaling stat as "SheerForce" and
    # hide or grey-out the DEF row when sheer_force is non-null.
    sheer_force: int | None = None

    # Attack info
    attack_name: str
    attack_multiplier: int
    agent_name: str
    enemy_name: str

    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_RESPONSE_DESC,
    )


class BuildAnomalyRequest(BaseModel):
    """Calculate anomaly damage for a saved build."""

    build_id: str
    enemy_profile_id: str
    anomaly_type: str = Field(description="burn, shock, corruption, shatter, or assault")

    buff_context: BuffContext = Field(default_factory=BuffContext)
    # deprecated: superseded by buff_context (Task A4); see BuildDamageRequest.
    active_conditions: list[str] = Field(default_factory=lambda: ["always"])
    stack_counts: dict[str, int] = Field(default_factory=dict)
    refinement: int = Field(default=1, ge=1, le=5)
    mindscape_level: int | None = None

    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000)
    procs: int | None = None


class BuildAnomalyResponse(BaseModel):
    """Anomaly damage result with breakdown."""

    per_proc: int
    total: int
    procs: int
    base_dmg: int
    boost_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int
    anomaly_prof_mult: int
    level_mult: int
    anomaly_boost_mult: int

    total_atk: int
    total_anomaly_proficiency: int
    agent_name: str
    enemy_name: str


# ---------------------------------------------------------------------------
# Combo evaluation
# ---------------------------------------------------------------------------


class ComboEvaluateRequest(BaseModel):
    """Evaluate a saved combo against an enemy with the build's stats."""

    enemy_profile_id: str = Field(description="UUID of the enemy profile")

    active_conditions: list[str] = Field(default_factory=lambda: ["always"])
    stack_counts: dict[str, int] = Field(default_factory=dict)

    refinement: int = Field(default=1, ge=1, le=5)
    mindscape_level: int | None = Field(
        default=None,
        description="Override mindscape level (default: build.mindscape_level)",
    )

    crit_mode: str = Field(default="expected", description="expected, crit, or no_crit")

    is_stunned: bool = Field(
        default=False,
        description=(
            "DEPRECATED. Use StunTriggerStep / StunEndStep markers in the combo "
            "sequence instead. This flag is still honoured as the initial stun "
            "state when no markers are present, but will be removed in a future "
            "version. Prefer explicit markers for per-step precision."
        ),
    )
    stun_dmg_mult: int | None = Field(
        default=None,
        description=(
            "Override the enemy's stun DMG multiplier in basis points. "
            "Defaults to the enemy profile's value (10000 + stun_dmg_taken_ratio)."
        ),
    )

    with_attribution: bool = Field(
        default=False,
        description=(
            "Include per-zone source attribution on each step. Adds JSON "
            "weight, so callers that only need totals (optimizer, scorer) "
            "leave it off."
        ),
    )


class ContributionSchema(BaseModel):
    """One labelled contributor to a damage zone (e.g. ``Core F: 1440``).

    ``source_category``/``source_kind``/``owner_agent_name``/``notes`` are
    populated when the contribution comes from a tagged modifier (v0.1+).
    Older / synthesised contributions may leave them None — the UI falls
    back to ``source`` for display. ``description`` is reserved and always
    None.
    """

    source: str
    value: int
    source_category: str | None = None  # "agent"|"wengine"|"disc_set"|"base"|"discs"|"external"
    source_kind: str | None = None  # ModifierSource.value string (e.g. "core_skill")
    owner_agent_name: str | None = None  # which agent produced the buff
    description: str | None = None  # reserved; always None in v0.1
    notes: str | None = None  # curator citation/rationale, from the modifier JSON `notes` field


class ZoneAttributionSchema(BaseModel):
    """All contributions to one zone, sorted server-side by absolute value."""

    contributions: list[ContributionSchema]
    total: int


class StepAttributionSchema(BaseModel):
    """Per-zone provenance for one step. Surfaced behind the hover tooltip."""

    atk_components: ZoneAttributionSchema
    atk_pct_components: ZoneAttributionSchema
    crit_rate: ZoneAttributionSchema
    crit_dmg: ZoneAttributionSchema
    boost_bonuses: ZoneAttributionSchema
    pen_ratio: ZoneAttributionSchema
    pen_flat: ZoneAttributionSchema
    res_reduction: ZoneAttributionSchema
    res_ignore: ZoneAttributionSchema
    def_ignore: ZoneAttributionSchema
    vulnerability: ZoneAttributionSchema
    stun_bonuses: ZoneAttributionSchema
    # Sheer Damage zones (Rupture agents only — null for standard hits).
    sheer_force_components: ZoneAttributionSchema | None = None
    sheer_boost_bonuses: ZoneAttributionSchema | None = None


class ZoneFormulaSchema(BaseModel):
    """One zone's derivation formula: template name + substituted operands.

    Purely presentational — mirrors ``app.services.attribution.ZoneFormula``.
    ``pre_clamp_bp`` is set only when a clamp/floor actually changed the
    zone's result (differs from ``result_bp``); the UI shows "capped from X"
    exactly when this is not None.
    """

    template: str
    terms: dict[str, int]
    result_bp: int
    pre_clamp_bp: int | None = None


class BuffRosterEntrySchema(BaseModel):
    """One resolved buff, pivoted for a build-level "active buffs" panel.

    Mirrors ``app.services.buff_roster.BuffRosterEntry``. Emitted once per
    build (not per-step) alongside ``attribution``/``zone_formulas`` when
    ``with_attribution=true``. ``is_modeled=False`` marks a buff whose
    ``scaling_stat`` was never baked to a flat value — it is genuinely
    active but contributes 0; shown rather than hidden (BRIEF_explainability.md).
    """

    source_label: str
    source_category: str | None = None
    source_kind: str | None = None
    owner_agent_name: str | None = None
    stat: str
    zone: str
    value_bp: int
    magnitude_display: str
    condition: str | None = None
    is_modeled: bool = True
    notes: str | None = None  # curator citation/rationale, from the modifier JSON `notes` field


class ZoneDeltaSchema(BaseModel):
    """One zone's before/after change in a build-delta comparison.

    Mirrors ``app.services.build_delta.ZoneDelta``. ``ratio`` is
    ``to_bp / from_bp``; ``gain_share_pct`` is this zone's exact log-space
    share of the overall damage change — every zone's share sums to ~100%
    (DESIGN_explainability.md §3.2, DECISIONS.md D-EXPL-1).
    """

    zone: str
    from_bp: int
    to_bp: int
    ratio: float
    gain_share_pct: float


class BuildDeltaSchema(BaseModel):
    """Delta decomposition vs. a comparison build (DESIGN §3.2).

    Mirrors ``app.services.build_delta.BuildDelta``. Present on
    ``TeamCalculateResponse.delta`` only when the keystone request carried
    ``compare_to`` and/or ``compare_to_disc_ids``.

    ``is_exact`` is ``False`` when a zone varies across same-type steps in the
    run (e.g. a partial stun window, or standard+anomaly steps mixed); the
    per-zone ``gain_share_pct`` values are then approximate and the UI should
    caveat the breakdown.
    """

    from_total: int
    to_total: int
    pct_change: float
    zone_deltas: list[ZoneDeltaSchema]
    is_exact: bool = True


class ComboStepResultSchema(BaseModel):
    """Per-step result in a combo evaluation.

    ``is_anomaly=True`` steps use anomaly-specific multiplier fields;
    ``is_anomaly=False`` (default) steps use the standard crit-triad fields.
    """

    label: str
    attack_id: str
    attack_name: str
    scope: str
    element: str
    multiplier: int

    # Headline total (uses requested crit_mode)
    total: int

    # Crit triad (standard hits)
    damage_no_crit: int = 0
    damage_crit: int = 0
    damage_expected: int = 0

    # Zone breakdown (standard hits)
    base_dmg: int = 0
    boost_mult: int = 0
    crit_mult: int = 0
    def_mult: int = 0
    res_mult: int = 0
    vulnerability_mult: int = 0
    stun_mult: int = 0
    effective_atk: int = 0  # resolved ATK used as scaling stat

    # Anomaly flag + anomaly-specific multipliers (anomaly hits only)
    is_anomaly: bool = False
    anomaly_proficiency_mult: int = 0  # AnomalyProfArea in bp
    anomaly_level_mult: int = 0  # LevelArea in bp
    anomaly_dmg_bonus_mult: int = 0  # AnomalyBoostArea in bp

    # DEF formula intermediates (for formula-card display in the UI)
    level_factor: int = 0  # attacker's LF = floor(0.1551·L² + 3.141·L + 47.2039)
    effective_enemy_def: int = 0  # enemy DEF after PEN%, DEF Ignore, PEN Flat
    # Stun formula intermediate (non-zero only when is_stunned)
    stun_base_mult: int = 0  # raw stun_dmg_mult in bp when stunned (e.g. 15000)

    # Sheer Damage (Rupture agents only). Non-null when this step used the Sheer
    # path. effective_atk holds SheerForce in this case (not raw ATK).
    # def_mult=10000 (no DEF zone). Frontend: label effective_atk as
    # "SheerForce" and hide/grey-out the DEF row when sheer_force is non-null.
    sheer_force: int | None = None

    # Optional source-by-source attribution. Present when the request set
    # ``with_attribution=true`` (the combo evaluator skips it otherwise to
    # keep the JSON small for the bulk optimizer / scorer paths).
    attribution: StepAttributionSchema | None = None

    # Optional per-zone derivation formulas (DESIGN_explainability.md §2.1),
    # keyed by zone name. Present only alongside ``attribution``.
    zone_formulas: dict[str, ZoneFormulaSchema] | None = None


class MarkerStepResultSchema(BaseModel):
    """Placeholder result for a stun marker step (zero damage)."""

    label: str
    step_type: str  # "stun_trigger" | "stun_end"
    total: int = 0


class CategoryBreakdownSchema(BaseModel):
    """Aggregate damage for one attack-type category."""

    category: str
    total: int
    pct: float


class ElementBreakdownSchema(BaseModel):
    """Aggregate damage for one element."""

    element: str
    total: int
    pct: float


class ComboEvaluateResponse(BaseModel):
    """Aggregate combo evaluation result with Fribbels-style breakdowns."""

    combo_id: str
    combo_name: str
    agent_name: str
    enemy_name: str

    total_damage: int
    standard_total: int
    # Was hardcoded to 0 and documented "always 0 in v1", because the team-combo
    # path could not derive an anomaly at all: every synthesised step zeroed its
    # buildup. It now carries the real total for any rotation that accrues gauge.
    anomaly_total: int

    steps: list[ComboStepResultSchema | MarkerStepResultSchema]
    by_category: list[CategoryBreakdownSchema]
    by_element: list[ElementBreakdownSchema]

    # Resolved stats (constant across steps in v1)
    total_atk: int
    total_crit_rate: int
    total_crit_dmg: int
    total_pen_ratio: int


# ---------------------------------------------------------------------------
# Team evaluation (Phase 5A — DPS-only with team-context buffs)
# ---------------------------------------------------------------------------


class TeamCalculateRequest(CustomBuffCarrier):
    """Evaluate a team combo under Phase 5B: all members contribute damage.

    The primary build (team slot 1) is the designated DPS for stat display.
    Each combo step carries ``agent_id`` identifying the owning member; steps
    without an explicit ``agent_id`` are attributed to the primary build.
    Supports contribute via ``target=team`` modifiers + auto-derived
    team-composition conditions.
    """

    combo_id: str = Field(description="Team-owned combo to evaluate")
    enemy_profile_id: str = Field(description="UUID of the enemy profile")

    active_conditions: list[str] = Field(default_factory=lambda: ["always"])
    stack_counts: dict[str, int] = Field(default_factory=dict)
    disabled_buffs: list[str] = Field(
        default_factory=list,
        description=(
            "Buffs to exclude from this calc, as buff_id() values or a stage buff's "
            "'custom:<slug>' (DESIGN_buff_context.md §2.1). Replaces each member's "
            "disabled_buffs column entirely -- never merged with it. Without this field "
            "the keystone endpoints applied a buff the run that produced the candidate "
            "had switched off, so clicking a candidate showed a number that run could "
            "not reproduce."
        ),
    )

    refinement: int = Field(default=1, ge=1, le=5)
    mindscape_level: int | None = Field(
        default=None,
        description="Override mindscape level for all members (default: each build's own level)",
    )

    crit_mode: str = Field(default="expected", description="expected, crit, or no_crit")

    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000)

    with_attribution: bool = Field(
        default=False,
        description=(
            "Include per-step source attribution + zone formulas and the "
            "build-level buff roster. Adds JSON weight, so bulk/summary "
            "callers leave it off (default payload unchanged)."
        ),
    )

    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_REQUEST_DESC,
    )

    @field_validator("fluxed_element")
    @classmethod
    def _validate_fluxed_element(cls, value: str | None) -> str | None:
        """Reject anything that is not a real element (F4, hardening Task 18).

        Applied to every REQUEST that carries this field, because hardening
        Task 17 made the value reach the damage chain: an unvalidated string
        silently selects no DMG% bucket and a neutral 0 enemy RES, then gets
        echoed back as "the element actually used". `lumiflux` is rejected
        alongside the nonsense values -- a Lumiflux build has no
        `lumiflux_dmg` bucket by design (DESIGN 4.2).
        """
        if value is None:
            return None
        valid = {e.value for e in Element} - {Element.LUMIFLUX.value}
        if value not in valid:
            raise ValueError(
                f"fluxed_element must be one of {sorted(valid)}, got {value!r}"
            )
        return value


class DiscStatsInput(BaseModel):
    """Inline disc stats for the keystone endpoint (DESIGN §3.1).

    Same operand shape ``accumulate_disc_stats`` already consumes -- lets an
    optimizer/rank candidate that isn't a persisted ``Disc`` row be evaluated
    without first saving it.
    """

    main_stat_type: str
    main_stat_value: int = 0
    substats: list[SubstatInput] = Field(default_factory=list)


class EvaluateDiscsRequest(CustomBuffCarrier):
    """Evaluate a team combo against a specified six-disc combination (DESIGN §3.1).

    The keystone endpoint: swaps ``disc_ids`` (persisted discs) or
    ``disc_stats`` (inline stats, e.g. an unpersisted optimizer candidate)
    onto the team member at ``active_index`` before stat resolution, then
    evaluates with full attribution. Exactly one of ``disc_ids``/``disc_stats``
    must be set.
    """

    combo_id: str = Field(description="Team-owned combo to evaluate")
    enemy_profile_id: str = Field(description="UUID of the enemy profile")
    active_index: int = Field(
        default=0,
        ge=0,
        le=2,
        description=(
            "Index of the team member whose discs are overridden "
            "(0=build1, 1=build2, 2=build3)."
        ),
    )

    disc_ids: list[str] | None = Field(
        default=None,
        max_length=6,
        description=(
            "Persisted disc IDs (up to 6) to evaluate as the overridden set. "
            "Fewer than 6 is accepted and evaluates a partial set (the "
            "unfilled slots contribute no stats / set bonuses) — pass all 6 "
            "for a full build comparison."
        ),
    )
    disc_stats: list[DiscStatsInput] | None = Field(
        default=None,
        max_length=6,
        description=(
            "Inline disc stats (up to 6), e.g. an unpersisted optimizer "
            "candidate. Fewer than 6 evaluates a partial set (unfilled slots "
            "contribute nothing) — pass all 6 for a full build comparison."
        ),
    )

    active_conditions: list[str] = Field(default_factory=lambda: ["always"])
    stack_counts: dict[str, int] = Field(default_factory=dict)
    disabled_buffs: list[str] = Field(
        default_factory=list,
        description=(
            "Buffs to exclude from this calc, as buff_id() values or a stage buff's "
            "'custom:<slug>' (DESIGN_buff_context.md §2.1). Replaces each member's "
            "disabled_buffs column entirely -- never merged with it. Without this field "
            "the keystone endpoints applied a buff the run that produced the candidate "
            "had switched off, so clicking a candidate showed a number that run could "
            "not reproduce."
        ),
    )

    refinement: int = Field(default=1, ge=1, le=5)
    mindscape_level: int | None = Field(
        default=None,
        description="Override mindscape level for all members (default: each build's own level)",
    )

    crit_mode: str = Field(default="expected", description="expected, crit, or no_crit")

    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000)

    compare_to: Literal["equipped"] | None = Field(
        default=None,
        description=(
            "Compute a BuildDeltaSchema against a comparison build. "
            "'equipped' compares against the team member's currently-equipped "
            "discs (no override). Omit both this and compare_to_disc_ids for "
            "no delta."
        ),
    )
    compare_to_disc_ids: list[str] | None = Field(
        default=None,
        max_length=6,
        description=(
            "Compare against this specific persisted disc set instead of the "
            "equipped set. Independent of compare_to -- providing this alone "
            "also computes a delta."
        ),
    )

    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_REQUEST_DESC,
    )

    @field_validator("fluxed_element")
    @classmethod
    def _validate_fluxed_element(cls, value: str | None) -> str | None:
        """Reject anything that is not a real element (F4, hardening Task 18).

        Applied to every REQUEST that carries this field, because hardening
        Task 17 made the value reach the damage chain: an unvalidated string
        silently selects no DMG% bucket and a neutral 0 enemy RES, then gets
        echoed back as "the element actually used". `lumiflux` is rejected
        alongside the nonsense values -- a Lumiflux build has no
        `lumiflux_dmg` bucket by design (DESIGN 4.2).
        """
        if value is None:
            return None
        valid = {e.value for e in Element} - {Element.LUMIFLUX.value}
        if value not in valid:
            raise ValueError(
                f"fluxed_element must be one of {sorted(valid)}, got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_disc_source(self) -> EvaluateDiscsRequest:
        has_ids = bool(self.disc_ids)
        has_stats = bool(self.disc_stats)
        if has_ids and has_stats:
            raise ValueError("Provide disc_ids or disc_stats, not both.")
        if not has_ids and not has_stats:
            raise ValueError("Either disc_ids or disc_stats is required.")
        return self


class AppliedTeamBuffSchema(BaseModel):
    """One team-target modifier from a support that is live for this calc."""

    source_build_id: str
    source_agent_name: str
    source_label: str
    stat: str
    value: int


class AgentContributionSchema(BaseModel):
    """Per-agent damage breakdown for Phase 5B team evaluation."""

    agent_name: str
    build_id: str
    damage: float
    pct: float


class TeamCalculateResponse(BaseModel):
    """Team-context combo result for the designated DPS."""

    team_id: str
    team_name: str
    dps_build_id: str
    dps_agent_name: str
    combo_id: str
    combo_name: str
    enemy_name: str

    # Auto-derived team-composition conditions that were activated
    # (on top of whatever the user passed in active_conditions).
    auto_conditions: list[str]

    # Team buffs that were live for this calc — for UI attribution.
    applied_team_buffs: list[AppliedTeamBuffSchema]

    # Per-agent damage breakdown (Phase 5B). Empty in Phase 5A responses.
    by_agent: list[AgentContributionSchema] = Field(default_factory=list)

    # Build-level "every resolved buff, once" panel for the DPS (DESIGN
    # §2.3). Populated only when the request set ``with_attribution=true``;
    # empty list otherwise.
    buff_roster: list[BuffRosterEntrySchema] = Field(default_factory=list)

    # Delta vs. a comparison build (Task B4). Populated only by
    # /evaluate-discs when the request carried compare_to/compare_to_disc_ids;
    # None otherwise (including every /calculate response).
    delta: BuildDeltaSchema | None = None

    # DPS combo damage (identical structure to ComboEvaluateResponse).
    total_damage: int
    standard_total: int
    anomaly_total: int

    steps: list[ComboStepResultSchema | MarkerStepResultSchema]
    by_category: list[CategoryBreakdownSchema]
    by_element: list[ElementBreakdownSchema]

    total_atk: int
    total_crit_rate: int
    total_crit_dmg: int
    total_pen_ratio: int

    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_RESPONSE_DESC,
    )
