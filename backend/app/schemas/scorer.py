"""Pydantic schemas for the disc scorer API (Phase 7b)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.damage import CustomBuffCarrier


class DiscScoreSchema(BaseModel):
    """Upgrade-potential breakdown for one disc."""

    disc_id: str
    rolls_used: int = Field(description="Substat rolls already placed")
    remaining_rolls: int = Field(description="Rolls remaining to max level")
    current_damage: float = Field(
        description="Combo damage with this disc equipped as-is, no leveling",
    )
    baseline_damage: float = Field(
        description=(
            "Damage of the build improvements are measured against — "
            "the current 6-disc build with whichever disc is presently "
            "in this slot."
        ),
    )
    max_improvement: float = Field(
        description="Best-case damage gain (favorable RNG to the cap)",
    )
    mean_improvement: float = Field(
        description="Expected damage gain over the multinomial PMF",
    )
    stddev_improvement: float = Field(description="Spread of the gain distribution")
    p10: float = Field(description="10th percentile damage gain")
    p50: float = Field(description="Median damage gain")
    p90: float = Field(description="90th percentile damage gain")
    distribution: list[tuple[float, float]] | None = Field(
        default=None,
        description=(
            "Full PMF as (improvement, probability) pairs sorted ascending. "
            "Only present when ``include_distribution`` is true on the request."
        ),
    )


class _ScorerContextBase(CustomBuffCarrier):
    """Shared damage-calc context between single-disc and inventory scoring.

    Inherits ``custom_buffs`` (Task B5a). Rank carries one of these *per context*
    (``RankContextSchema``), which is the right granularity for a stage buff: ranking the
    same inventory against two different Deadly-Assault stages is a normal thing to want,
    and a single run-level field could not express it.
    """

    combo_id: str = Field(description="UUID of the combo to score against")
    enemy_profile_id: str = Field(description="UUID of the enemy profile")
    active_index: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Index of the team member to score discs for (0=build1, 1=build2, 2=build3).",
    )

    active_conditions: list[str] = Field(default_factory=lambda: ["always"])
    stack_counts: dict[str, int] = Field(default_factory=dict)
    disabled_buffs: list[str] = Field(
        default_factory=list,
        description=(
            "Kit modifiers to exclude from the calc, as buff_id() values "
            "(DESIGN_buff_context.md §2.1). Replaces the build's (and each "
            "support's) disabled_buffs column entirely -- never merged with it."
        ),
    )
    refinement: int = Field(default=1, ge=1, le=5)
    mindscape_level: int | None = None
    crit_mode: str = Field(default="expected", description="expected, crit, or no_crit")
    is_stunned: bool = False
    stun_dmg_mult: int = Field(default=15000)
    include_distribution: bool = Field(
        default=False,
        description="Return the full PMF in addition to the summary stats.",
    )


class DiscScoreRequest(_ScorerContextBase):
    """Score a single disc."""

    disc_id: str = Field(description="UUID of the disc to score")


class InventoryScoreRequest(_ScorerContextBase):
    """Score multiple discs at once."""

    disc_ids: list[str] | None = Field(
        default=None,
        description=("Explicit disc IDs to score. When null, scope determines the set."),
    )
    scope: str = Field(
        default="default",
        description=(
            '"default" — build\'s equipped discs plus every unequipped disc. '
            '"all" — every disc in the DB (includes discs on other builds). '
            "disc_ids, when given, takes precedence over scope."
        ),
    )
    allowed_set_ids: list[int] | None = Field(
        default=None,
        description=(
            "When set, only score discs whose DiscSet.hakushin_id is in this list. "
            "Applied after scope/disc_ids resolution. None = no filter."
        ),
    )


class DiscScoreResponse(BaseModel):
    """Response for ``POST /scorer/disc``."""

    combo_id: str
    combo_name: str
    agent_name: str
    enemy_name: str
    score: DiscScoreSchema


class InventoryScoreResponse(BaseModel):
    """Response for ``POST /scorer/inventory`` — sorted by mean_improvement desc."""

    combo_id: str
    combo_name: str
    agent_name: str
    enemy_name: str
    scores: list[DiscScoreSchema]


# ---------------------------------------------------------------------------
# Rank schemas (Phase 2)
# ---------------------------------------------------------------------------


class RankContextSchema(_ScorerContextBase):
    """One (build, combo, enemy, weight) entry in a multi-build rank request.

    ``build_id`` may be omitted when ``team_id`` is provided; the target
    build is then derived from ``team_id`` + ``active_index``.
    ``allowed_set_ids`` is a per-context server-side pre-filter; ``None``
    means score all sets for this context.
    """

    build_id: str | None = Field(
        default=None,
        description=(
            "UUID of the build to score against. "
            "Optional when team_id is set — derived from team slot at active_index."
        ),
    )
    team_id: str | None = Field(
        default=None,
        description=(
            "Optional Team UUID. When provided, support builds for this context "
            "are resolved from team members at active_index."
        ),
    )
    active_index: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Index of the team member to treat as the active (DPS) build.",
    )
    weight: float = Field(
        default=1.0,
        gt=0,
        description="Relative weight for the portfolio weighted-average aggregation",
    )
    allowed_set_ids: list[int] | None = Field(
        default=None,
        description=(
            "Only score discs whose DiscSet.hakushin_id is in this list for this "
            "context.  None = no filter.  Per-context (not global)."
        ),
    )
    support_slot: int | None = Field(
        default=None,
        description=(
            "None = DPS scoring (default). 1 or 2 = score discs onto the primary's "
            "support{N} build, measured by the primary's combo delta."
        ),
    )

    @field_validator("support_slot")
    @classmethod
    def _validate_support_slot(cls, v: int | None) -> int | None:
        if v is not None and v not in {1, 2}:
            raise ValueError("support_slot must be 1 or 2")
        return v


class RankFilters(BaseModel):
    """Optional inventory pre-filter for ``POST /scorer/rank``."""

    slot: int | None = Field(default=None, description="Keep only discs in this slot (1-6).")
    set_ids: list[int] = Field(
        default_factory=list,
        description="Keep only discs from these set hakushin_ids.",
    )
    rarities: list[str] = Field(
        default_factory=list,
        description="Keep only discs with these rarities (e.g. 'S', 'A').",
    )
    main_stats: list[str] = Field(
        default_factory=list,
        description="Keep only discs whose main_stat_type is in this list.",
    )
    level_value: int | None = Field(
        default=None,
        description="Filter by disc level; paired with level_mode.",
    )
    level_mode: Literal["min", "max", "exact"] = Field(
        default="min",
        description='"min" -> level >= value; "max" -> level <= value; "exact" -> level == value.',
    )


class RankRequest(BaseModel):
    """Request body for ``POST /scorer/rank``."""

    contexts: list[RankContextSchema] = Field(
        min_length=1,
        description=(
            "One or more (build, combo, enemy, weight) contexts.  A single-element "
            "list is the single-build case."
        ),
    )
    disc_ids: list[str] | None = Field(
        default=None,
        description="Explicit disc IDs to rank.  Null → use scope.",
    )
    scope: str = Field(
        default="default",
        description='"default" — build-equipped + unequipped; "all" — every disc in DB.',
    )
    filters: RankFilters | None = Field(
        default=None,
        description="Optional pre-filter on the inventory before scoring. None = no constraint.",
    )


class PerBuildBreakdown(BaseModel):
    """Per-context scores for one disc."""

    build_id: str
    avg_pct: float | None = Field(
        description="Avg potential % for this context; null when set filter excluded this disc.",
    )
    max_pct: float | None = Field(
        description="Max potential % for this context; null when excluded.",
    )
    reference_mode: str | None = Field(
        default=None,
        description=(
            '"equipped" — avg_pct/max_pct are vs this context\'s currently-equipped discs. '
            '"best" — the context has no equipped discs, so avg_pct/max_pct are norm_pct: '
            "this disc's % gap to the best-scoring disc in this context (<=0, 0 for the "
            "best). Null when excluded by set filter. See DESIGN_ranker_discless.md D1/D2a."
        ),
    )
    team_id: str | None = Field(
        default=None,
        description=(
            "Team UUID this context was scored under, when the request specified "
            "team_id (DESIGN §3.4 keystone deep-link). None for build_id-only contexts."
        ),
    )
    combo_id: str | None = Field(
        default=None,
        description="Combo UUID this context was scored against.",
    )
    enemy_profile_id: str | None = Field(
        default=None,
        description="Enemy profile UUID this context was scored against.",
    )
    active_index: int | None = Field(
        default=None,
        description="Team slot (0-2) the scored build occupies, for the evaluate-discs deep-link.",
    )


class DiscRankSchema(BaseModel):
    """Rank result for a single disc."""

    disc_id: str
    per_build: list[PerBuildBreakdown] = Field(
        description="Per-context breakdown, one entry per context in the request (same order).",
    )
    best_build_avg: float = Field(
        description=(
            "Max norm_pct across scored contexts — this disc's % gap to the best-scoring "
            "disc in its best context, NOT the same quantity as per_build[].avg_pct. "
            "Baseline-free, so a disc-less context can no longer dominate this number "
            "(DESIGN_ranker_discless.md D3). <= 0; saturates at exactly 0.0 for any disc "
            "that is the best candidate in at least one scored context (D4). Run-relative: "
            "adding a better disc, or filtering out the current best, shifts every other "
            "disc's value even though its own score did not change (D5)."
        ),
    )
    best_build_avg_build_id: str = Field(description="build_id of the winning context")
    best_build_max: float = Field(
        description="Same as best_build_avg but over norm_pct's max variant. See D3-D5.",
    )
    portfolio_avg: float = Field(
        description=(
            "Weight-normalised mean of norm_pct across scored contexts — baseline-free "
            "(D3), so <= 0 and subject to the same D4 saturation and D5 run-relative "
            "instability as best_build_avg. This is the discriminating ranking key: "
            "best_build_avg ties at 0.0 for every disc that is best somewhere (D4)."
        ),
    )


class RankResponse(BaseModel):
    """Response for ``POST /scorer/rank``."""

    job_id: str = Field(description="UUID of the async rank job; poll via job-detail endpoint")
