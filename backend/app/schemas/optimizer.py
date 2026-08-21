"""Pydantic schemas for the disc optimizer API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import Element
from app.schemas.damage import CustomBuffCarrier

# Shared descriptions for the fluxed_element contract (DESIGN_remielle.md §5.3).
# Attribute Flux is a Lumiflux-only mechanic (Remielle et al.) — every other
# agent's fluxed_element is always null and unaffected by this field.
_FLUXED_ELEMENT_REQUEST_DESC = (
    "Attribute Flux override, Lumiflux agents only (e.g. Remielle). When set, "
    "this element's `<element>_dmg` disc stat is unioned into the top-K "
    "prefilter keep-set instead of the auto-derived value (the element of "
    "the next team slot, cyclic). With no team_id, a solo/empty team, or a "
    "non-Lumiflux agent, the derived value is null: no attribute DMG% disc "
    "stat is unioned (a Lumiflux agent has no such bucket by design). A "
    "missing team is therefore the documented default, not a calc bug."
)
_FLUXED_ELEMENT_RESPONSE_DESC = (
    "The element actually used for this run's DMG%-bucket disc-stat union "
    "(override if provided, else the derived value). Null for non-Lumiflux "
    "agents and for a Lumiflux agent with no team / a solo team."
)


class SetFrameSchema(BaseModel):
    """One acceptable set-count distribution across six slots.

    ``counts`` maps ``set_hakushin_id → piece_count`` and must sum to 6.
    """

    counts: dict[int, int] = Field(
        description="Map of set_hakushin_id to piece count; must sum to 6",
    )


class DiscOptimizeRequest(CustomBuffCarrier):
    """Input for ranking disc assignments against a saved combo.

    Inherits ``custom_buffs`` (Task B5a): you optimize *for* a stage, so a Deadly-Assault
    buff has to be expressible here or the discs it favours never win.
    """

    # Team context (optional; when provided, support builds are resolved from team members).
    team_id: str | None = Field(
        default=None,
        description=(
            "UUID of a Team. When provided, the other two members at active_index "
            "are used as supports for the DPS snapshot."
        ),
    )
    active_index: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Index of the team member to treat as the active (DPS) build.",
    )

    # Exactly one of combo_id / combo_ids must be provided.
    combo_id: str | None = Field(
        default=None,
        description="UUID of a single combo to score against (legacy)",
    )
    combo_ids: list[str] | None = Field(
        default=None,
        description=(
            "UUIDs of one or more combos. Each is evaluated; the build's "
            "total_damage is max(per_combo_damage). Use this to find the "
            "disc set that maximises performance across a rotation."
        ),
    )
    aggregation: Literal["max"] = Field(
        default="max",
        description="How to aggregate per-combo damages into total_damage.",
    )
    enemy_profile_id: str = Field(description="UUID of the enemy profile")

    # Inventory scope
    disc_ids: list[str] | None = Field(
        default=None,
        description=(
            "Explicit disc IDs to consider. When null, the pool is determined by inventory_scope."
        ),
    )
    inventory_scope: Literal["this_build", "priority"] = Field(
        default="this_build",
        description=(
            "How to resolve the disc pool when disc_ids is null. "
            "'this_build' (default): build's equipped discs + all unequipped. "
            "'priority': same, but discs equipped on higher-priority builds are excluded."
        ),
    )

    # Constraints (keyed by slot 1-6, set_hakushin_id, or TotalStats field name)
    locked_slots: dict[int, str] = Field(
        default_factory=dict,
        description="Map of slot (1-6) to disc_id that must fill it",
    )
    required_sets: dict[int, int] = Field(
        default_factory=dict,
        description="Map of set_hakushin_id to minimum piece count",
    )
    min_stats: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Map of TotalStats field name to minimum value (basis points for "
            "percentages, absolute for flats). Combos below any floor are "
            "pruned before DAG evaluation."
        ),
    )
    allowed_frames: list[SetFrameSchema] | None = Field(
        default=None,
        description=(
            "When provided, the optimizer evaluates only combos whose "
            "set-count distribution matches one of the declared frames."
        ),
    )
    top_n: int = Field(default=10, ge=1, le=100)

    # Search acceleration (optional; default None = exhaustive)
    prefilter_top_k: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Heuristic accelerator: keep only the top-K candidates per (slot, "
            "set) bucket by solo marginal damage before enumeration. null "
            "(default) searches exhaustively. K >= a bucket's size is exact."
        ),
    )

    # Energy gating (optional; both must be set to take effect)
    rotation_energy_cost: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Total Energy the rotation's EX-Special casts require. When set, "
            "each build's EX-Special damage is credited by an energy-feasibility "
            "factor derived from its ER (base + disc) over rotation_duration_s, "
            "so ER% influences rankings. null (default) credits EX damage in "
            "full (current behavior)."
        ),
    )
    rotation_duration_s: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Wall-clock seconds over which passive energy regen accrues; only "
            "used when rotation_energy_cost is set."
        ),
    )

    # Damage-calc context (parallel to /combos/{id}/evaluate)
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

    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_REQUEST_DESC,
    )

    @field_validator("fluxed_element")
    @classmethod
    def _validate_fluxed_element(cls, value: str | None) -> str | None:
        """Reject anything that is not a real element (F4, hardening Task 18).

        The value was never validated against anything: `fluxed_element:
        "banana"` was accepted, silently unioned no disc stat at all, and was
        echoed straight back as the resolved value. Rejecting at the schema
        makes it a 422 instead of a quietly worse keep-set plus a response
        asserting an element that does not exist.

        `lumiflux` is excluded deliberately as well as the nonsense values: a
        Lumiflux build has no `lumiflux_dmg` bucket by design (DESIGN 4.2), so
        fluxing *to* Lumiflux is a request for something that cannot exist.
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
    def _validate_combo_source(self) -> DiscOptimizeRequest:
        has_single = self.combo_id is not None
        has_multi = self.combo_ids is not None and len(self.combo_ids) > 0
        if has_single and has_multi:
            raise ValueError("Provide combo_id or combo_ids, not both.")
        if not has_single and not has_multi:
            raise ValueError("Either combo_id or combo_ids is required.")
        return self


class SubstatRollSummary(BaseModel):
    """One substat entry on a disc."""

    stat_type: str
    value: int
    rolls: int


class OptimizerDiscSummary(BaseModel):
    """Disc metadata projected onto each result build."""

    disc_id: str
    slot: int
    set_id: int
    set_name: str
    main_stat_type: str
    main_stat_value: int
    rarity: str
    substats: list[SubstatRollSummary] = Field(default_factory=list)
    score: float | None = None
    icon_path: str = ""


class BuildStatsSummary(BaseModel):
    """Fully resolved stats for one optimizer result build."""

    # Flat stats
    hp: int = 0
    atk: int = 0
    defense: int = 0

    # Combat stats (basis points for percentages)
    crit_rate: int = 0
    crit_dmg: int = 0
    pen_flat: int = 0
    pen_ratio: int = 0
    anomaly_mastery: int = 0
    anomaly_proficiency: int = 0
    impact: int = 0
    energy_regen: int = 0

    # Elemental damage bonuses (basis points)
    physical_dmg: int = 0
    fire_dmg: int = 0
    ice_dmg: int = 0
    electric_dmg: int = 0
    ether_dmg: int = 0


class OptimizerDiscBuildSchema(BaseModel):
    """One candidate build produced by the optimizer."""

    teammate_unattributed_damage: float = Field(
        default=0.0,
        description=(
            "Teammate damage this build's stats do NOT move, summed. A pure "
            "constant: no disc choice changes it, so it cannot affect ranking. "
            "Subtract it from `total_damage` to get the target's attributed "
            "share — its own damage plus the part of a teammate's that its stats "
            "produce. 0 for a single-agent rotation or a target that owns every "
            "event."
        ),
    )
    total_damage: float = Field(
        description=(
            "DAG-computed combo total for THIS build — the target's own damage plus "
            "the share of a teammate's damage that the target's own stats produce "
            "(currently the Refringe uplift, #160). It is NOT the team's total: a "
            "teammate's own output is excluded, and buffs the target grants that "
            "feed a teammate's SNAPSHOT rather than scaling their damage "
            "multiplicatively — squad ATK, whose cap makes it piecewise-linear — are "
            "not yet included. Subtract `teammate_unattributed_damage` for the "
            "target-attributed share, and see "
            "`search_transparency.scored_event_kinds` for the composition."
        )
    )
    disc_ids: list[str] = Field(description="Disc IDs ordered by slot 1..6")
    set_counts: dict[int, int] = Field(
        description="set_hakushin_id → piece count for this combo",
    )
    per_combo_damage: dict[str, float] = Field(
        default_factory=dict,
        description="combo_id → damage for each evaluated combo",
    )
    discs: list[OptimizerDiscSummary] = Field(
        default_factory=list,
        description="Disc metadata for each slot (ordered by slot 1..6)",
    )
    total_stats: BuildStatsSummary = Field(
        default_factory=BuildStatsSummary,
        description="Resolved build stats for this disc combo.",
    )


class SearchTransparencySchema(BaseModel):
    """Structured search-space diagnostics for the optimizer run (Task B5).

    Bundles the same counters as the flat ``DiscOptimizeResponse`` fields plus
    ``total_space``/``is_exact`` for a single UI-facing object; the flat fields
    stay for backward compatibility.
    """

    total_space: int = Field(
        description=(
            "Raw per-slot Cartesian-product size (inventory candidates per slot, "
            "respecting locked slots) before any prefilter/Pareto reduction. An "
            "estimate of the full search space, not what was actually scored."
        )
    )
    evaluated: int = Field(description="Combinations scored (passed pruning)")
    pruned_sets: int = Field(description="Rejected by required-set constraints")
    pruned_stats: int = Field(description="Rejected by min_stats floor")
    prefiltered: int = Field(description="Inventory candidates removed by prefilter_top_k")
    auto_prefilter_k: int | None = Field(
        default=None,
        description=(
            "K_dmg auto-selected by the time-denominated budget when prefilter_top_k "
            "was not set explicitly; None if the search ran exact or with an explicit K."
        ),
    )
    is_exact: bool = Field(
        description=(
            "True when no prefilter reduced the inventory "
            "(prefiltered == 0 and auto_prefilter_k is None). The lossless Pareto "
            "layer never affects this — it removes only dominated candidates."
        )
    )
    pareto_removed: int = Field(
        default=0,
        description=(
            "Inventory candidates dropped by the lossless Pareto-dominance layer. "
            "Lossless relative to the scoring model, which is the caveat worth "
            "surfacing: the comparison is projected onto dims the probe found "
            "live, so a stat the model values at zero is not a tiebreak — discs "
            "differing only in it collapse to one keeper. Previously tracked "
            "internally and never reported, which made a 53-billion-to-6,592 "
            "reduction look like it came from nowhere (#161)."
        ),
    )
    scored_event_kinds: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Count of scored steps by event kind (hit, anomaly_tick, luminize, "
            "refringe_credit, …). The diagnostic that makes a mechanic emitting "
            "ZERO events visible: a run whose target never fired its signature "
            "mechanic is otherwise indistinguishable from a healthy one, and its "
            "stat recommendations are confidently wrong (#161)."
        ),
    )


class DiscOptimizeResponse(BaseModel):
    """Top-N optimizer results plus search diagnostics."""

    combo_id: str = Field(description="Primary combo ID (first of combo_ids)")
    combo_name: str
    agent_name: str
    enemy_name: str

    current_build_damage: float | None = Field(
        default=None,
        description="Damage of the build's currently equipped discs (for Δ%).",
    )

    builds: list[OptimizerDiscBuildSchema]
    evaluated: int = Field(description="Combinations scored (passed pruning)")
    pruned_sets: int = Field(description="Rejected by required-set constraints")
    pruned_stats: int = Field(description="Rejected by min_stats floor")
    prefiltered: int = Field(
        default=0, description="Inventory candidates removed by prefilter_top_k"
    )
    auto_prefilter_k: int | None = Field(
        default=None,
        description=(
            "K_dmg auto-selected by the time-denominated budget when prefilter_top_k "
            "was not set explicitly; None if the search ran exact or with an explicit K."
        ),
    )
    search_transparency: SearchTransparencySchema = Field(
        description="Structured search-space diagnostics (Task B5)."
    )
    search_summary: str = Field(
        description="Human-readable one-line summary of the search space, e.g. "
        "'Searched 48,210 of ~1.2M combinations (top-K prefilter K=8 applied — "
        "results are near-exact; run exact search to verify).'"
    )
    fluxed_element: str | None = Field(
        default=None,
        description=_FLUXED_ELEMENT_RESPONSE_DESC,
    )
