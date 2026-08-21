"""Pydantic schemas for the stateful anomaly simulation API."""

from pydantic import BaseModel, Field

from app.schemas.damage import BuffContext, BuffRosterEntrySchema


class SimulationStepRequest(BaseModel):
    """Input for one attack step or state marker in a simulated timeline."""

    agent_id: str = Field(description="The key/ID mapping to the acting build in team_builds")
    move_name: str = Field(
        description=(
            "Curated move name (e.g. 'EX Special Attack: Intense Heat Aging "
            "Method') or marker ('stun_trigger', 'stun_end')"
        )
    )
    conditions: list[str] = Field(
        default_factory=list, description="Active condition strings for this specific step"
    )
    variant_label: str | None = Field(
        default=None, description="Optional variant label selected for the move"
    )
    single_tap: bool | None = Field(
        default=None, description="Whether this represents a single tap in a sequential chain"
    )
    cycle_position: int | None = Field(
        default=None, description="Explicit cycle position override for sequential moves"
    )
    channel_s: float | None = Field(
        default=None,
        description=(
            "Seconds this hold/channel is sustained, for a move whose hit_mode is "
            "'channel' (Burnice's spray, Norma's Extended Shot). Scales the move's "
            "'tick'-role rows and its per-second resource drain. None resolves to the "
            "spec's default_s with a warning; out-of-range clamps with a warning. "
            "Ignored on any move that is not a channel."
        ),
    )


class SimulationRequest(BaseModel):
    """Input for a stateful team anomaly simulation."""

    team_builds: dict[str, str] = Field(description="Map of agent ID/keys to build IDs (UUIDs)")
    steps: list[SimulationStepRequest] = Field(
        description="Sequential list of attack steps or state markers"
    )
    enemy_profile_id: str = Field(
        description="UUID of the enemy profile to run simulation against"
    )
    buff_context: BuffContext = Field(
        default_factory=BuffContext,
        description=(
            "Run-level buff state (DESIGN_buff_context.md §2.1) -- the server "
            "reads this and only this for active_conditions/stack_counts; "
            "build.active_conditions/stack_counts are never consulted. "
            "active_conditions here compose with each step's own conditions "
            "(dict.fromkeys(context + step) -- a step condition is a "
            "statement about that step, not the run)."
        ),
    )


class TimelineEventSchema(BaseModel):
    """Trace event generated during simulation."""

    t: float = Field(description="Timestamp in seconds")
    kind: str = Field(
        description=(
            "Event kind: hit, anomaly, disorder, vortex, expire, refresh, "
            "stun_trigger, stun_end, switch"
        )
    )
    agent_id: str | None = Field(default=None, description="Acting agent ID/key")
    element: str | None = Field(default=None, description="Elemental context")
    damage: int | None = Field(default=None, description="Damage dealt in this event")
    aura_type: str | None = Field(default=None, description="Active aura element")
    applier_agent_id: str | None = Field(default=None, description="Original applier agent ID/key")
    detail: dict = Field(default_factory=dict, description="Event-specific metadata")


class SimulationResponse(BaseModel):
    """Simulation run results with event trace and damage attribution."""

    events: list[TimelineEventSchema] = Field(description="Ordered timeline of trace events")
    totals: dict[str, int] = Field(description="Damage totals partitioned by source type")
    per_agent_attribution: dict[str, int] = Field(
        description="Total damage attributed to each agent key"
    )
    warnings: list[str] = Field(description="List of simulation warnings or missing specs")
    field_timeline: list[tuple[float, str]] = Field(
        default_factory=list,
        description="Ordered list of (timestamp, agent_id) recording every on-field transition",
    )
    buff_roster: dict[str, list[BuffRosterEntrySchema]] = Field(
        default_factory=dict,
        description=(
            "Build-level 'every resolved buff, once' panel per team_builds key "
            "(DESIGN_explainability.md §2.3). Always-active (ALL scope, SELF "
            "target) resolution -- not per-step."
        ),
    )
