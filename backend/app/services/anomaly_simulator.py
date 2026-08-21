"""Stateful Anomaly, Disorder, and Vortex Simulator (Option B)."""

# ruff: noqa: PLR0912, PLR0915
import contextlib
import heapq
import re
from collections import deque  # noqa: TC003 -- used in a runtime-evaluated local annotation below
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

from app.data.loaders.moves import AftershockSpec
from app.models.build import EnemyProfile
from app.models.enums import HitMode, RowCondition
from app.services.attribution import build_step_attribution
from app.services.buff_resolver import ActiveConditions
from app.services.build_damage_service import (
    AttackScope,
    BuildSnapshot,
    CritMode,
    EnemySnapshot,
    _resolve_and_calc,
    calculate_build_anomaly,
    calculate_build_damage,
    resolve_build_stats,
)
from app.services.combo_step_resolver import (
    is_phase_flow_swap_legal,
    resolve_channel_length,
    scope_for_skill_key,
)
from app.services.damage_calculator import (
    ANOMALY_BASE,
    AnomalyType,
    calculate_abloom_damage,
    calculate_buildup,
    calculate_disorder_damage,
    calculate_luminize_damage,
    calculate_vortex_damage,
)
from app.services.kit_formulas import KitFormula
from app.services.lumiflux import (
    LumifluxEnemyState,
    LumifluxSpec,
    VoidflareRecord,
    apply_lumiflux_points,
    clear_voidflare_store,
    consume_lumiflux_points,
    phase_flow_expected_value,
    refringe_coefficient,
    store_voidflare,
)
from app.services.modifiers import Condition, ModifierTarget
from app.services.resource_banks import ResourceBanks
from app.services.resource_bill import bill_for_move, clamp_channel_to_bank
from app.services.snapshot_builder import (
    _OFF_FIELD_SWAP_WINDOW_S,
    _slugify,
    inject_stat_threshold_conditions,
)

# Fallback EX energy cost when Agent.ex_energy_cost is NULL (frozen from energy_costs.py).
EX_COST_DEFAULT: int = 60

ELEMENT_TO_ANOMALY = {
    "physical": AnomalyType.ASSAULT,
    "fire": AnomalyType.BURN,
    "ice": AnomalyType.SHATTER,
    "electric": AnomalyType.SHOCK,
    "ether": AnomalyType.CORRUPTION,
    "wind": AnomalyType.WINDSWEPT,
}

# Derived from the canonical `ANOMALY_BASE` table (damage_calculator.py) so the
# two proc-count tables can't drift apart again (F-02).
ANOMALY_PROC_COUNTS = {anomaly_type: procs for anomaly_type, (_, procs) in ANOMALY_BASE.items()}

# F-19: Shock/Corruption only deal tick damage when the enemy is actually attacked,
# throttled by an internal per-anomaly cooldown. Burn/Shatter/Assault/Windswept keep
# the uniform/instant schedule (they are not on-hit anomalies).
GATED_ANOMALY_TYPES = {AnomalyType.SHOCK, AnomalyType.CORRUPTION}
GATED_ANOMALY_CD_S = {AnomalyType.SHOCK: 1.0, AnomalyType.CORRUPTION: 0.5}

# One-proc burst anomalies (`ANOMALY_PROC_COUNTS == 1`): the whole anomaly is a single
# damage instance resolved at trigger time. Applying one onto a live aura of its own
# attribute therefore refreshes the aura AND resolves a fresh instance — Leifa, on the
# wind case: "Applying a Wind Anomaly on an existing Wind Anomaly ... only reapplies the
# Windswept effect" (references/DMG Formula for Anomaly, Disorder and Vortex Leifa.html),
# where reapplying *is* the damage. Jane's damage profile is repeated Assault procs.
#
# The tick anomalies (Burn/Shock/Corruption) are excluded deliberately: their procs are
# already scheduled off the original instance, so re-application extends the aura's life
# without arming a second wave.
REPROC_ON_REAPPLY_TYPES = {AnomalyType.ASSAULT, AnomalyType.SHATTER, AnomalyType.WINDSWEPT}

# F-17b: Leifa wind buildup curve, entry #2 (2nd trigger). Entry #1 lives in the
# DB as anomaly_capacity_wind; from the 3rd trigger wind rejoins the generic
# non-physical curve. Absent from nanoka/hakushin — cited constant.
# Ref: references/DMG Formula for Anomaly, Disorder and Vortex Leifa.html
WIND_ENTRY2_BY_TIER = {"normal": 500, "elite": 2000, "boss": 2700}

# F-17b: maps the enemy's generic (ether) anomaly capacity to its tier, so the
# wind entry-curve knows which WIND_ENTRY2_BY_TIER row applies. An enemy whose
# ether capacity matches none of these (unknown/future enemy) falls back to
# the standard generic curve for all n — never guesses a tier.
WIND_TIER_BY_ETHER_CAPACITY = {600: "normal", 2250: "elite", 3000: "boss"}

# F-11/F-23a: Frostbite (post-Shatter) and Flinch (post-Assault) enemy-state
# windows — sim-only enemy-state modifiers, no calc-chain change (Leifa;
# RESEARCH_math_review.md F-11/F-23). Frostbite adds Crit DMG (taken) into the
# standard-hit crit-DMG input for in-window hits; Flinch adds Daze/Stun-taken
# into the existing `stun_buildup_multiplier` path already used by
# `calculate_buildup` while the enemy is Stunned (F-09's unsourced parameter —
# this is its first sourced caller).
FROSTBITE_CRIT_DMG_BONUS: int = 1000  # +10% Crit DMG, basis points
FROSTBITE_DURATION_S: float = 10.0
FROSTBITE_FROST_DURATION_S: float = 20.0  # Frost variant (e.g. Miyabi)
FLINCH_STUN_BUILDUP_BONUS: int = 750  # +7.5% Daze/Stun-buildup taken, basis points
FLINCH_DURATION_S: float = 10.0

# F-11/F-23b: Windswept opens a Direct-DMG window for its own aura lifetime
# (the existing `duration = 20.0` wind branch below, at the trigger site) —
# unlike Frostbite/Flinch it has no separate secondary-state duration in the
# references. Wind hits landed while the window is open get +10% Direct DMG
# Bonus, a multiplicative zone separate from generic DMG% (does NOT combine
# with it, does NOT apply to anomaly DMG — only wired into
# `calculate_standard_damage`'s `direct_dmg_bonus` param).
WINDSWEPT_DIRECT_DMG_BONUS: int = 1000  # +10% Direct DMG Bonus, basis points

# Maps the non-wind element to its vortex kind string (used in calculate_vortex_damage).
# Wind is absent: vortex always uses the non-wind element's type.
ELEMENT_TO_VORTEX_KIND: dict[str, str] = {
    "fire": "burn",
    "ice": "ice_freeze",
    "electric": "shock",
    "ether": "corruption",
    "physical": "assault",
}

# Agents known to trigger vortex on wind/non-wind anomaly interaction.
# Known limitation: this is a conservative allowlist; agents not listed here will not
# trigger vortex even if their kit supports it.
VORTEX_ALLOWLIST: frozenset[str] = frozenset({"soukaku", "trigger", "velina", "ye_shunguang"})

# Notes-from-the-Chained 4pc grants AP+48 for 30s after any Abloom trigger.
_ABLOOM_TRIGGER_BUFF_S = 30.0

# Ode of Resurrected Wings (Remielle's sig W-Engine, Task 19, DESIGN §6/Task
# 17): +20% self Anomaly DMG / +30% squad DMG for 30s after a Refringe
# trigger, refreshed on re-trigger — same "windowed post-trigger condition"
# shape as Notes-from-the-Chained above, same precedent.
_REFRINGE_TRIGGER_BUFF_S = 30.0

# Windbite cap (Velina Core): consuming Vortex (counter==cap) → Sweeping Cyclone + Core +150%.
_WINDBITE_CAP: int = 2

# Maximum energy an agent can hold (standard ZZZ cap; parameterized here for future overrides).
_ENERGY_CAP: float = 120.0


def _row_is_live(attack: Any, *, is_stunned: bool) -> bool:
    """Does this `attacks` row fire in the current game state? (D-CH5, Task 17b)

    ``select_when`` NULL means unconditional, which is every row in the corpus until Norma
    (Task 17d). The two shipped conditions read the enemy's stun state, which is why this is
    a per-hit call and not a repository filter: unlike ``potential``, which is fixed for a
    build, ``is_enemy_stunned`` starts from the enemy profile and then flips on the rotation's
    own ``stun_trigger`` / ``stun_end`` markers.

    **Unknown values fail OPEN** — the row fires. The loader rejects unknown conditions at
    author time, so a value arriving here means the DB holds something this build does not
    know (a downgrade, or rows seeded from a newer branch). Firing keeps the damage, which is
    wrong *visibly*; the alternative deletes a hit in silence, which is precisely the failure
    the whole column is shaped to avoid — the same reason NULL means "fires" rather than
    "unset".

    Callers must skip at the row's OWN index rather than pre-filtering ``step.attacks``:
    ``attack_scales`` and ``attack_offsets`` are positionally aligned with it.
    """
    condition = getattr(attack, "select_when", None)
    if condition is None:
        return True
    value = getattr(condition, "value", condition)
    if value == RowCondition.ENEMY_STUNNED.value:
        return is_stunned
    if value == RowCondition.ENEMY_NOT_STUNNED.value:
        return not is_stunned
    return True



# Default clock cost of a switch (swap animation window).
LUMIFLUX_ELEMENT: str = "lumiflux"

_SWITCH_DURATION_S: float = 1.0

# Prismatic's post-removal linger, in seconds. db(core_skills, verbatim):
# "Prismatic is removed when the enemy no longer has Lumiflux Buildup.
# After Prismatic is removed, the Anomaly Buildup Rate increase persists
# for an additional 8s."
_PRISMATIC_LINGER_S: float = 8.0


def _serialize_zone(zone: Any) -> dict:
    if not zone:
        return {"contributions": [], "total": 0}
    contribs = sorted(
        zone.contributions,
        key=lambda c: -abs(c.value),
    )
    return {
        "contributions": [
            {
                "source": c.source,
                "value": c.value,
                "source_category": c.source_category,
                "source_kind": getattr(c, "source_kind", None),
                "owner_agent_name": c.owner_agent_name,
                "description": getattr(c, "description", None),
            }
            for c in contribs
        ],
        "total": zone.total,
    }


def _serialize_zone_formulas(attr: Any | None) -> dict | None:
    """Serialize ``StepAttribution.zone_formulas`` as a top-level sibling to
    ``attribution`` on each event's ``detail`` dict -- mirrors
    ``ComboStepResultSchema.zone_formulas`` being a sibling field to
    ``.attribution`` (see ``teams.py::_zone_formula_schemas``), not nested
    inside it.
    """
    if attr is None or not attr.zone_formulas:
        return None
    return {
        zone: {
            "template": zf.template,
            "terms": zf.terms,
            "result_bp": zf.result_bp,
            "pre_clamp_bp": zf.pre_clamp_bp,
        }
        for zone, zf in attr.zone_formulas.items()
    }


def _serialize_attribution(attr: Any | None) -> dict | None:
    if attr is None:
        return None
    return {
        "atk_components": _serialize_zone(attr.atk_components),
        "atk_pct_components": _serialize_zone(attr.atk_pct_components),
        "crit_rate": _serialize_zone(attr.crit_rate),
        "crit_dmg": _serialize_zone(attr.crit_dmg),
        "boost_bonuses": _serialize_zone(attr.boost_bonuses),
        "pen_ratio": _serialize_zone(attr.pen_ratio),
        "pen_flat": _serialize_zone(attr.pen_flat),
        "res_reduction": _serialize_zone(attr.res_reduction),
        "res_ignore": _serialize_zone(attr.res_ignore),
        "def_ignore": _serialize_zone(attr.def_ignore),
        "vulnerability": _serialize_zone(attr.vulnerability),
        "stun_bonuses": _serialize_zone(attr.stun_bonuses),
        "sheer_force_components": (
            _serialize_zone(attr.sheer_force_components)
            if hasattr(attr, "sheer_force_components")
            and attr.sheer_force_components.contributions
            else None
        ),
        "sheer_boost_bonuses": (
            _serialize_zone(attr.sheer_boost_bonuses)
            if hasattr(attr, "sheer_boost_bonuses") and attr.sheer_boost_bonuses.contributions
            else None
        ),
    }


def _split_amount_by_share(amount: int, shares: dict[str, float]) -> dict[str, int]:
    """Split an integer amount across agents by proportional share.

    Largest-remainder method: floor each share's cut, then hand the leftover
    units to the largest fractional remainders first, so the parts always sum
    to exactly `amount` (no rounding leak) — F-20 per-agent tick attribution.
    """
    if not shares:
        return {}
    if len(shares) == 1:
        return dict.fromkeys(shares, amount)
    raw = {agent_id: amount * share for agent_id, share in shares.items()}
    floors = {agent_id: int(v) for agent_id, v in raw.items()}
    remainder = amount - sum(floors.values())
    by_frac = sorted(raw, key=lambda agent_id: raw[agent_id] - floors[agent_id], reverse=True)
    for agent_id in by_frac[:remainder]:
        floors[agent_id] += 1
    return floors


def _prune_aura_ticks(
    events: list["TimelineEvent"],
    totals: dict[str, int],
    per_agent_attribution: dict[str, int],
    element: str,
    applier_id: str,
    t_cutoff: float,
) -> None:
    """Prune any pre-scheduled anomaly ticks for the given element that occur at or after t_cutoff.

    Deducts their damage from standard totals and per-agent attributions.
    """
    pruned_events = []
    for e in events:
        if e.kind == "anomaly_tick" and e.element == element and e.t >= t_cutoff:
            dmg = e.damage or 0
            totals["anomaly"] -= dmg
            totals["total"] -= dmg
            if applier_id in per_agent_attribution:
                per_agent_attribution[applier_id] -= dmg
        else:
            pruned_events.append(e)
    events[:] = pruned_events


@dataclass
class SimulatedAttackStep:
    """One resolved combo step queued for the timeline simulator.

    Bridges a `ComboStep` (author-facing move reference) and the DB `Attack`
    rows it expands to, so the simulator can walk a rotation hit-by-hit while
    tracking anomaly buildup, energy, and (for authored aftershocks) a
    pre-baked ATK% multiplier instead of a real Attack row.
    """

    agent_id: str
    move_name: str
    attacks: list[Any]  # database Attack models
    conditions: list[str] = field(default_factory=list)
    # For authored aftershock steps: multiplier in basis points (e.g. 5000 = 50% ATK).
    aftershock_mv_bp: int = 0
    # How long a `hit_mode='channel'` move is held, in seconds. `None` on every other
    # move, and on a channel step that carries no request -- `resolve_channel_length`
    # then substitutes the spec's `default_s` and warns, the same fallback a missing
    # `variant_label` gets.
    channel_s: float | None = None
    # Per-hit multiplier fractions, positionally aligned with `attacks`. Set only where a
    # channel was expanded (`channel_plan.build_channel_plan`): a tick row repeated N times
    # is N hits at a FRACTION of the authored multiplier, and repeating the row without
    # scaling it would multiply the move's damage by N. `None` means "every hit at face
    # value", which is every other move (Task 10c).
    attack_scales: list[float] | None = None
    # Seconds from the step's start at which each hit lands, positionally aligned with
    # `attacks`. Set only for an expanded channel, where the hits are NOT evenly spaced: an
    # entry at 0, ticks one `tick_s` apart, the release after the non-held tail. `None` falls
    # back to the even spread every other move gets (Task 10b).
    attack_offsets: list[float] | None = None


@dataclass
class _SyntheticAttack:
    """Lightweight stand-in for a DB Attack model, built from a ComboStep."""

    id: str | None
    name: str
    element: str
    skill_key: str = "Basic"
    damage_base: int = 0
    damage_growth: int = 0
    anomaly_buildup: int = 0
    energy_gain: int = 0  # synthetic attacks never grant energy; real DB attacks do


@dataclass
class _StepMoveSpec:
    """Minimal MoveSpec built from a pre-resolved ComboStep.

    The Lumiflux fields below are copied off the acting agent's *real*
    ``moves/agents/<agent>.json`` entry by `_lumiflux_move_fields`, because the
    combo path synthesises its own ``moves_db`` and the step-resolution loop
    reads these three off the move spec. Without them, wiring the assembler into
    this entry point would produce Refringe and silently never Luminize — a
    partial fix that reads as complete (DESIGN_remielle.md §13.4).
    """

    scope: "AttackScope"
    element: str
    # ``None``, not ``0``. The step loop distinguishes an *authored* zero — which
    # deliberately suppresses a move's gauge — from an omitted one, which falls
    # back to summing the step's own DB rows. This spec carries no curation, so
    # it has to take the fallback; defaulting to ``0`` made every synthesised
    # step an authored zero, which was half the reason the team-combo path
    # emitted no `anomaly` event for any agent.
    buildup: int | None = None
    # 1.0 is the same approximation the no-spec fallback uses. The combo path overrides
    # it per step for channel ticks: `_resolve_channel` emits one ComboStep per tick, so
    # leaving each at 1.0 charges 1s of clock PER TICK and a 2s spray costs 5s (Task 10a).
    duration_s: float = 1.0
    hits: int = 1
    consolidated: bool = False
    triggers_luminize: bool = False
    luminize_mult_bp: int = 0
    lumiflux_points: int = 0
    # Also carried, though §13.4 predates it: without the arming flag the
    # assembler derives no Phase Flow windows on this path (Task 30).
    phase_flow_entry: bool = False
    # E-F3: does this move clear the equipper's Voidflare store afterwards?
    clears_voidflare_store: bool = False


class _AgentMovesStub:
    """Duck-typed AgentMovesSpec with a .moves dict."""

    def __init__(self, moves: dict) -> None:
        self.moves = moves


@dataclass
class TimelineEvent:
    """One dated entry in the simulator's output timeline.

    Every hit, anomaly proc, disorder trigger, vortex, buff expiry, or
    aftershock the stateful simulator resolves becomes one of these, in
    chronological order — the timeline is the record the UI and the
    attribution layer replay to explain "what happened, and when."
    """

    t: float
    kind: str  # "hit" | "anomaly" | "disorder" | "vortex" | "expire" | "aftershock"
    # | "lumiflux_point" (P2, DESIGN §7.1 — a point applied to the per-enemy pool)
    # | "refringe" (DESIGN §7.1 — a point consumed to buff a teammate's anomaly)
    # | "luminize" (DESIGN §7.2 — one instance per stored Voidflare; never an
    #   anomaly trigger, so it can never itself become a Disorder/Abloom/Vortex source)
    # | "phase_flow_tick" (P4, DESIGN §7.3 — deterministic EV flight-attack tick)
    # | "phase_flow_unlock_assist" (P4b, DESIGN §7.3 — auto-fires once per
    #   Phase Flow on a legal swap-in)
    agent_id: str | None
    element: str | None
    damage: int | None
    aura_type: str | None
    applier_agent_id: str | None
    detail: dict = field(default_factory=dict)
    # Raw StepAttribution for "hit" events (not the serialized `detail["attribution"]`
    # dict) -- lets sim_result_to_combo_evaluation attach it to ComboStepResult
    # directly without a lossy round-trip through JSON-shaped data.
    attribution: Any = None


@dataclass
class SimulationResult:
    """Full output of a stateful combo simulation.

    Aggregates the event timeline into per-category damage totals and
    per-agent attribution, plus energy/field-swap snapshots over time —
    everything downstream consumers (combo evaluation, UI playback) need
    without re-walking `events`.
    """

    events: list[TimelineEvent]
    totals: dict[str, int]
    per_agent_attribution: dict[str, int]
    warnings: list[str]
    final_energy: dict[str, float] = field(default_factory=dict)
    # (t, agent_id, energy_after) snapshots recorded after each step's regen/gain processing
    energy_timeline: list[tuple[float, str, float]] = field(default_factory=list)
    # (t, active_agent) snapshots — one entry per switch event, at the moment of switch
    field_timeline: list[tuple[float, str]] = field(default_factory=list)
    # P2 (Remielle DESIGN §7.1): the per-enemy Lumiflux Buildup Point pool's
    # point count at the end of the run. 0 whenever no Lumiflux points were
    # ever applied (including every non-Remielle sim today) — mirrors
    # `final_energy`'s "snapshot of otherwise-internal sim state" role.
    final_lumiflux_points: int = 0
    # P1/P3 (DESIGN §7.2): each Lumiflux agent's Voidflare store at run end,
    # keyed by her agent_id, most-recent-last. Empty whenever no Voidflare was
    # ever captured (including every non-Remielle sim today) — same
    # "snapshot of otherwise-internal sim state" role as `final_lumiflux_points`.
    final_voidflares: dict[str, list[VoidflareRecord]] = field(default_factory=dict)


def _get_enemy_stat(enemy: Any, name: str, default: Any) -> Any:
    """Helper to safely get attributes from SQLAlchemy models with None-handling."""
    val = getattr(enemy, name, default)
    return default if val is None else val


def _record_lumiflux_points(
    lumiflux_state: LumifluxEnemyState | None,
    spec: LumifluxSpec,
    count: int,
    *,
    agent_id: str,
    t: float,
    events: list[TimelineEvent],
) -> LumifluxEnemyState:
    """Apply ``count`` Lumiflux Buildup Points to the sim's per-enemy pool and
    emit a ``"lumiflux_point"`` timeline event recording the new state (P2,
    DESIGN §7.1).

    Invoked from `simulate()`'s step-resolution loop for any move whose spec
    declares `lumiflux_points` (Task 31), and by nothing else. The actual
    cap/floor arithmetic lives in `lumiflux.apply_lumiflux_points` (DESIGN
    §3's mechanism/policy split); this function only holds/replaces the
    single per-enemy state slot and serializes it into the timeline.

    Any Lumiflux agent's ``agent_id`` may call this — the state it updates
    is `simulate()`'s single `lumiflux_state` local, not keyed by agent, so
    a second Lumiflux agent's calls land in the same pool (see
    `lumiflux_state`'s docstring at its declaration site).
    """
    new_state = apply_lumiflux_points(lumiflux_state, spec, count, agent_id=agent_id, at=t)
    events.append(
        TimelineEvent(
            t=t,
            kind="lumiflux_point",
            agent_id=agent_id,
            element=None,
            damage=None,
            aura_type=None,
            applier_agent_id=agent_id,
            detail={
                "points_added": count,
                "points": new_state.points,
                "point_cap": spec.point_cap,
                "owner_agent_id": new_state.owner_agent_id,
                "last_point_at": new_state.last_point_at,
            },
        )
    )
    return new_state


def _resolve_with_team_modifiers(
    agent_id: str, builds: dict[str, BuildSnapshot], conditions: ActiveConditions
) -> Any:
    """Resolve ``agent_id``'s own stats with teammates' team-target modifiers
    folded in.

    ``builds[agent_id].modifiers`` alone only carries that build's own
    gear/kit modifiers — team-wide buffs granted by *other* builds are not
    pre-merged into it (this API path, unlike `team_calculator.py`, builds
    snapshots independently per agent). Same merge the Vortex block a few
    hundred lines below already does for an ally's stats; factored out here
    so the Refringe hook (Task 11, DESIGN §7.1) can resolve the Lumiflux
    agent's own Anomaly Proficiency the same way.
    """
    build = builds[agent_id]
    modifiers = list(build.modifiers)
    for other_id, other_build in builds.items():
        if other_id != agent_id:
            modifiers.extend(
                [m for m in other_build.modifiers if m.target in (ModifierTarget.TEAM, "team")]
            )
    build_snap = replace(build, modifiers=modifiers)
    return _resolve_and_calc(build_snap, conditions, AttackScope.ALL)


def _with_equipper_conditions_for(
    conditions: ActiveConditions, build: BuildSnapshot | None
) -> ActiveConditions:
    """``conditions``, but with the ``equipper_is_*`` entries re-derived for
    ``build`` instead of whoever they were injected for.

    The step loop injects ``equipper_is_<specialty>`` / ``equipper_is_<element>``
    for the *acting* agent, which is correct for resolving that agent's own
    damage. It is wrong the moment those conditions are reused to resolve a
    *different* agent's modifiers — engine finding E-F5(a): Refringe resolved
    Remielle's buffs under the acting teammate's condition set, so none of her
    ``equipper_is_lumiflux``-gated rows (Feathered Fate's 4pc, and both of Ode
    of Resurrected Wings' Refringe rows after hardening Task 3) could ever fire
    on the Refringe path. Everything not equipper-scoped — enemy state, team
    composition, Phase Flow — is shared team state and is carried through
    untouched.
    """
    rebuilt = {c for c in conditions.active if not c.value.startswith("equipper_is_")}
    for attr in ("agent_specialty", "agent_element"):
        value = getattr(build, attr, "") if build is not None else ""
        if value:
            with contextlib.suppress(ValueError):
                rebuilt.add(Condition(f"equipper_is_{value.lower()}"))
    # The agent-identity family (EQUIPPER_IS_PYROIS) rides the name, not the
    # specialty/element strings — same re-derivation rule as the two above.
    name = getattr(build, "agent_name", "") if build is not None else ""
    if name:
        with contextlib.suppress(ValueError):
            rebuilt.add(Condition(f"equipper_is_{_slugify(name)}"))
    return ActiveConditions(
        active=rebuilt,
        stack_counts=dict(getattr(conditions, "stack_counts", {}) or {}),
    )


def _resolve_refringe(
    lumiflux_state: LumifluxEnemyState | None,
    builds: dict[str, BuildSnapshot],
    lumiflux_specs: dict[str, LumifluxSpec],
    acting_agent_id: str,
    active_conditions: ActiveConditions,
    t: float,
    events: list[TimelineEvent],
) -> tuple[LumifluxEnemyState | None, int, str | None, dict | None]:
    """Consume one Lumiflux Buildup Point (if available) to Refringe the
    Attribute Anomaly `acting_agent_id` just triggered (DESIGN §7.1).

    Returns ``(updated_lumiflux_state, refringe_mult, lumiflux_agent_id)`` —
    `refringe_mult` is the neutral ``10000`` (no-op, `lumiflux_agent_id`
    ``None``) whenever any gate fails: no points banked, no known Lumiflux
    agent in the squad (i.e. no entry in `lumiflux_specs` — Task 18's kit
    JSON is what populates this in production), or the triggering agent *is*
    the Lumiflux agent (she applies no conventional buildup and can never
    trigger her own anomaly — DESIGN §7.1, Task 11 acceptance). The returned
    `lumiflux_agent_id` (non-``None`` only when Refringe actually fired) is
    who Task 12's Voidflare capture is stored against.

    Only ever consumes from the first Lumiflux agent found with a registered
    spec; two Lumiflux agents on one team is an unmodeled edge case the guide
    does not describe (deferred, `docs/LOG_remielle.md` Task 11 entry).

    The fourth element is the **credit inputs** (#160), ``None`` whenever
    Refringe did not fire. The optimizer needs to rebuild this coefficient at
    each candidate's AP to attribute the uplift back to her build
    (:func:`app.formula.zzz.damage.refringe_credit_node`), and it cannot do that
    from ``refringe_mult`` alone -- that is the coefficient already collapsed at
    her disc-stripped AP, with the flat and AP-derived halves indistinguishable.
    """
    if lumiflux_state is None or lumiflux_state.points < 1:
        return lumiflux_state, 10000, None, None
    acting_build = builds.get(acting_agent_id)
    if acting_build is not None and acting_build.agent_element == "lumiflux":
        return lumiflux_state, 10000, None, None
    lumiflux_agent_id = next(
        (
            aid
            for aid, bld in builds.items()
            if bld.agent_element == "lumiflux" and aid in lumiflux_specs
        ),
        None,
    )
    if lumiflux_agent_id is None:
        return lumiflux_state, 10000, None, None

    spec = lumiflux_specs[lumiflux_agent_id]
    # E-F5(a): resolve HER buffs under HER equipper conditions, not the acting
    # teammate's. `active_conditions` arrives carrying `equipper_is_<teammate>`.
    lumiflux_conditions = _with_equipper_conditions_for(
        active_conditions, builds.get(lumiflux_agent_id)
    )
    lumiflux_ctx = _resolve_with_team_modifiers(lumiflux_agent_id, builds, lumiflux_conditions)
    # Task 18: the flat, Condition-gated term (core passive +10% at 3
    # Anomaly agents, M2 +20%) is authored as a normal `refringe_flat_bonus_bp`
    # combat-bonus modifier in remielle.json -- summed here, not hardcoded.
    flat_bonus_bp = lumiflux_ctx.buffs.combat_bonuses.get("refringe_flat_bonus_bp", 0)
    coefficient_bp = refringe_coefficient(
        spec, lumiflux_ctx.stats.anomaly_proficiency, flat_bonus_bp=flat_bonus_bp
    )
    # `at=t` so the Prismatic linger clock can start from the emptying
    # instant rather than the last application (E-F5(b)).
    new_state = consume_lumiflux_points(lumiflux_state, 1, at=t)
    events.append(
        TimelineEvent(
            t=t,
            kind="refringe",
            agent_id=lumiflux_agent_id,
            element=None,
            damage=None,
            aura_type=None,
            applier_agent_id=lumiflux_agent_id,
            detail={
                "triggering_agent_id": acting_agent_id,
                "refringe_coefficient_bp": coefficient_bp,
                "refringe_mult": 10000 + coefficient_bp,
                "points_remaining": new_state.points,
            },
        )
    )
    return (
        new_state,
        10000 + coefficient_bp,
        lumiflux_agent_id,
        {
            "refringe_agent_id": lumiflux_agent_id,
            "refringe_ap_ratio_bp": spec.refringe_ap_ratio_bp,
            "refringe_flat_bonus_bp": flat_bonus_bp,
        },
    )


def _resolve_stun_onset_abloom(
    builds: dict[str, BuildSnapshot],
    moves_db: dict[str, Any],
    active_aura: dict,
    t: float,
) -> list[TimelineEvent]:
    """Emit stun-onset Abloom events for any build with a 'stun_onset_abloom' move.

    Currently handles: Nangong Yu M6 Vibrato:Modified (DESIGN_abloom_c8.md §C2).
    Isolated from the per-step Abloom path — called only at stun_trigger.
    """
    aura_element = active_aura["element"]
    result_events: list[TimelineEvent] = []
    for bid, bld in builds.items():
        agent_key = _agent_key(bld.agent_name)
        agent_moves = moves_db.get(agent_key)
        if not agent_moves:
            continue
        spec = agent_moves.moves.get("stun_onset_abloom")
        if not spec or not spec.abloom_mv_by_element:
            continue
        if bld.mindscape_level < spec.abloom_requires_mindscape:
            continue
        mv_bp = spec.abloom_mv_by_element.get(aura_element, 0)
        if mv_bp <= 0 or active_aura.get("dmg_per_proc", 0) <= 0:
            continue
        _mv_mult = spec.abloom_mv_multiplier_bp
        _mv_mult_mc = getattr(spec, "abloom_mv_multiplier_requires_mindscape", 0)
        if bld.mindscape_level < _mv_mult_mc:
            _mv_mult = 10_000
        mv_bp = mv_bp * _mv_mult // 10_000
        # Include team buff modifiers from other agents into this build's resolution.
        active_mods = list(bld.modifiers)
        for other_id, other_bld in builds.items():
            if other_id != bid:
                active_mods.extend(
                    [
                        m
                        for m in other_bld.modifiers
                        if m.target
                        in (ModifierTarget.TEAM, "team", ModifierTarget.ACTIVE, "active")
                    ]
                )
        bld_snap = replace(bld, modifiers=active_mods)
        ctx = _resolve_and_calc(
            bld_snap,
            ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED}, stack_counts={}),
            AttackScope.ALL,
        )
        abloom_dmg_bonus = (
            ctx.buffs.combat_bonuses.get("abloom_mv_bonus", 0) + ctx.buffs.abloom_dmg_bonus
        )
        abloom_res = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=active_aura["dmg_per_proc"],
            ap=ctx.stats.anomaly_proficiency,
            abloom_dmg_bonus=abloom_dmg_bonus,
            abloom_ap_scaled=spec.abloom_ap_scaled,
        )
        result_events.append(
            TimelineEvent(
                t=t,
                kind="abloom",
                agent_id=bid,
                element=aura_element,
                damage=abloom_res.total,
                aura_type=aura_element,
                applier_agent_id=active_aura["applier_id"],
                detail={
                    "abloom_mv_bp": mv_bp,
                    "original_anomaly_dmg": active_aura["dmg_per_proc"],
                    "ap": ctx.stats.anomaly_proficiency,
                    "abloom_boost_mult": abloom_res.abloom_boost_mult,
                    "is_anomaly": True,
                    "stun_onset": True,
                },
            )
        )
    return result_events


def _resolve_offfield_modifiers(
    emitter_id: str,
    builds: dict[str, "BuildSnapshot"],
) -> list:
    """Return the merged modifier list for an off-field proc emitted by *emitter_id*.

    Rule: emitter SELF + emitter TEAM + each teammate's TEAM modifiers.
    ACTIVE modifiers are dropped for everyone — they only apply to the on-field actor.
    """
    emitter_build = builds[emitter_id]
    result = [
        m for m in emitter_build.modifiers if m.target not in (ModifierTarget.ACTIVE, "active")
    ]
    for agent_id, other_build in builds.items():
        if agent_id == emitter_id:
            continue
        result.extend(
            m for m in other_build.modifiers if m.target in (ModifierTarget.TEAM, "team")
        )
    return result


def _resolve_onfield_modifiers(
    emitter_id: str,
    builds: dict[str, "BuildSnapshot"],
) -> list:
    """Return the merged modifier list for an on-field proc emitted by *emitter_id*.

    Rule: emitter's own modifiers + each teammate's TEAM and ACTIVE modifiers.
    Mirrors the on-field hit merge — the active actor receives teammate buffs that
    only apply while on field, unlike the off-field path (TEAM-only).
    """
    result = list(builds[emitter_id].modifiers)
    for agent_id, other_build in builds.items():
        if agent_id == emitter_id:
            continue
        result.extend(
            m
            for m in other_build.modifiers
            if m.target in (ModifierTarget.TEAM, "team", ModifierTarget.ACTIVE, "active")
        )
    return result


def _aftershock_enemy_snapshot(enemy: Any, element: str) -> "EnemySnapshot":
    """Build the EnemySnapshot used for every aftershock-damage calculation."""
    return EnemySnapshot(
        level=enemy.level,
        base_def=enemy.defense,
        element_res=_get_enemy_stat(enemy, f"{element}_res", 0),
        stun_dmg_mult=10000 + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000),
    )


def _aftershock_conditions(is_enemy_stunned: bool) -> ActiveConditions:
    """Active conditions for an aftershock proc: ALWAYS + AFTERSHOCK_ACTIVE (+ stun)."""
    active: set[Condition] = {Condition.ALWAYS, Condition.AFTERSHOCK_ACTIVE}
    if is_enemy_stunned:
        active.add(Condition.ENEMY_STUNNED)
    return ActiveConditions(active=active)


def _emit_aftershock_event(
    *,
    emitter_id: str,
    emitter_snap: "BuildSnapshot",
    enemy: Any,
    element: str,
    mv: int,
    is_enemy_stunned: bool,
    on_field: bool,
    t_hit: float,
) -> "TimelineEvent":
    """Calculate one aftershock instance and package it as a kind='aftershock' event.

    Single source of truth for the EnemySnapshot, AFTERSHOCK_ACTIVE conditions,
    damage call, and detail dict shared by every aftershock emission path
    (off-field, on-field self, repeat-chain, White Thunder cascade).
    """
    enemy_snap = _aftershock_enemy_snapshot(enemy, element)
    dmg_res = calculate_build_damage(
        build=emitter_snap,
        enemy=enemy_snap,
        multiplier=mv,
        conditions=_aftershock_conditions(is_enemy_stunned),
        # #154: aftershocks are their own category — ALL would disable scope filtering.
        attack_scope=AttackScope.AFTERSHOCK,
        # …and resolve element_scope against the aftershock's OWN element. Omitting this
        # falls back to the emitter's agent element, which is only coincidentally right:
        # an aftershock whose element differs from its emitter's would collect the wrong
        # element's bonuses.
        element=element,
        crit_mode=CritMode.EXPECTED,
        is_stunned=is_enemy_stunned,
        stun_dmg_mult=enemy_snap.stun_dmg_mult,
        with_attribution=True,
    )
    return TimelineEvent(
        t=t_hit,
        kind="aftershock",
        agent_id=emitter_id,
        element=element,
        damage=dmg_res.damage.total,
        aura_type=None,
        applier_agent_id=emitter_id,
        detail={
            "multiplier": mv,
            "scope": "all",
            "base_dmg": dmg_res.damage.base_dmg,
            "effective_atk": dmg_res.damage.effective_atk,
            "crit_mult": dmg_res.damage.crit_mult,
            "boost_mult": dmg_res.damage.boost_mult,
            "def_mult": dmg_res.damage.def_mult,
            "res_mult": dmg_res.damage.res_mult,
            "vulnerability_mult": dmg_res.damage.vulnerability_mult,
            "stun_mult": dmg_res.damage.stun_mult,
            "is_anomaly": False,
            "on_field": on_field,
            "aftershock": True,
            "attribution": _serialize_attribution(dmg_res.attribution),
            "zone_formulas": _serialize_zone_formulas(dmg_res.attribution),
        },
    )


def _emit_kit_formula_event(
    *,
    emitter_id: str,
    emitter_snap: "BuildSnapshot",
    formula: KitFormula,
    enemy: Any,
    conditions: ActiveConditions,
    is_enemy_stunned: bool,
    t_hit: float,
) -> "TimelineEvent":
    """Calculate one kit `formulas[]` damage instance as a kind='kit_formula' event.

    Structurally the aftershock emission above: an extra damage instance the step
    triggers, with its own element, multiplier, and detail dict. It differs in two
    ways, both because kit formulas are not moves — the multiplier is already
    resolved against mindscape/core level (see kit_formulas.py), and the scaling
    stat may be DEF or Anomaly Proficiency rather than ATK.

    Known under-count (D-KV12). ZO tags three of these instances with a *damage type*
    on top of their scope — Miyabi's frostburn break as `anomaly`, Orphie & Magus's
    and Soldier 0 Anby's M6 as `aftershock` — which makes them eligible for Anomaly
    DMG% and Aftershock DMG% buffs respectively. (They still use the standard damage
    formula: ZO's `customDmg` registers `'standardDmg'` whatever the tag, and reaches
    for `customAnomalyDmg` when it wants the anomaly chain. So `standard_dmg` is the
    right quantity for all three.) The kit schema has no field for that tag, so those
    three miss their bonus bucket today. It is an under-count on three agents, not a
    wrong formula, and closing it is a schema + re-curation job — Task 17.
    """
    element = formula.element or emitter_snap.agent_element
    enemy_snap = EnemySnapshot(
        level=enemy.level,
        base_def=enemy.defense,
        element_res=_get_enemy_stat(enemy, f"{element}_res", 0),
        stun_dmg_mult=10000 + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000),
    )
    dmg_res = calculate_build_damage(
        build=emitter_snap,
        enemy=enemy_snap,
        multiplier=formula.multiplier,
        conditions=conditions,
        attack_scope=formula.scope,
        crit_mode=CritMode.EXPECTED,
        is_stunned=is_enemy_stunned,
        stun_dmg_mult=enemy_snap.stun_dmg_mult,
        with_attribution=True,
        damage_stat=formula.damage_stat,
        element=element,
    )
    return TimelineEvent(
        t=t_hit,
        kind="kit_formula",
        agent_id=emitter_id,
        element=element,
        damage=dmg_res.damage.total,
        aura_type=None,
        applier_agent_id=emitter_id,
        detail={
            "formula_name": formula.name,
            "multiplier": formula.multiplier,
            "scope": formula.scope.value,
            "damage_stat": formula.damage_stat,
            "base_dmg": dmg_res.damage.base_dmg,
            "effective_atk": dmg_res.damage.effective_atk,
            "crit_mult": dmg_res.damage.crit_mult,
            "boost_mult": dmg_res.damage.boost_mult,
            "def_mult": dmg_res.damage.def_mult,
            "res_mult": dmg_res.damage.res_mult,
            "vulnerability_mult": dmg_res.damage.vulnerability_mult,
            "stun_mult": dmg_res.damage.stun_mult,
            "is_anomaly": False,
            "on_field": True,
            "attribution": _serialize_attribution(dmg_res.attribution),
            "zone_formulas": _serialize_zone_formulas(dmg_res.attribution),
        },
    )


def _agent_key(agent_name: str) -> str:
    """Normalise an agent name to a moves-DB lookup key.

    Replaces runs of non-word characters (spaces, ampersands, etc.) with a
    single underscore so 'Orphie & Magus' → 'orphie_magus'.
    """
    return re.sub(r"\W+", "_", agent_name.lower()).strip("_")


def _is_sequential_slice(step: Any, move_spec: Any) -> bool:
    """Is this step one button press of a multi-press `sequential` move?

    The same test the buildup divisor uses: gated on the row's own ``hit_mode``, not on
    ``move_spec.hits > len(attacks)`` — for an ATOMIC move the authored ``hits`` is an
    animation-hit count that legitimately exceeds the row count, and every row of an
    atomic move lands in this one step.
    """
    attacks = getattr(step, "attacks", None) or []
    return (
        move_spec is not None
        and bool(attacks)
        and getattr(attacks[0], "hit_mode", None) == HitMode.SEQUENTIAL
        and len(attacks) < (getattr(move_spec, "hits", 0) or 1)
    )


def _step_duration_s(step: Any, move_spec: Any) -> float:
    """How much clock one step consumes.

    ``duration_s`` is authored as the whole-**move** animation length, exactly as
    ``buildup`` is authored as the whole-**move** gauge total (MODIFIER_AUTHORING.md,
    "duration_s"/"hits"). Both therefore need the same divisor on a single-tap press of
    a `sequential` move, and until this existed only buildup got one: #79 sliced the
    gauge and left the clock alone, so one press of Jane's 6-row Dancing Blades charged
    the full 1.8s of the whole chain. A 6-press cycle spanned 10.8s instead of 1.8s —
    every combo and every optimizer rotation, since both resolve sequential moves
    single-tap.

    That is not a cosmetic timeline difference: anomaly decay, the 3s per-attribute
    re-trigger cooldown, buff windows and passive energy accrual are all read off this
    clock, so the same rotation produced a different anomaly proc count depending only
    on how its steps were encoded. Slicing here makes the two encodings agree, which is
    what makes the bundled crossval fixtures and the single-tap production path
    comparable at all (issue #83).
    """
    if move_spec is None:
        return 1.0
    channel = getattr(move_spec, "channel", None)
    if channel is not None:
        # A channel's authored `duration_s` is the NON-HELD tail -- the entry and release
        # animation -- because the held part is the player's to choose and cannot be
        # authored as a constant. This is the one mode that re-reads the field, which is
        # why it is stated here, in `ChannelSpec`, and in MODIFIER_AUTHORING.md rather
        # than left for a reader to infer from arithmetic.
        chosen_s, _ = resolve_channel_length(
            getattr(step, "move_name", "<channel>"),
            channel,
            getattr(step, "channel_s", None),
        )
        return chosen_s + move_spec.duration_s
    if _is_sequential_slice(step, move_spec):
        return move_spec.duration_s / (move_spec.hits or 1)
    return move_spec.duration_s


@dataclass(frozen=True)
class StepTiming:
    """When one rotation step happens on ``simulate()``'s clock.

    Produced by :func:`walk_step_timeline`, consumed by
    ``lumiflux_assembly`` to derive Phase Flow windows that line up with the
    ticks they schedule.
    """

    index: int  # position in the original `steps` list
    agent_id: str
    move_name: str
    # When this step's agent became the active (on-field) agent, if this step
    # caused a swap. `None` when it was already active or the step is a marker.
    # This is the instant `simulate()` timestamps the "switch" event at — before
    # the 1s swap charge, not after.
    t_switch: float | None
    t_start: float  # clock at which the action itself begins
    t_end: float  # clock after the action; == t_start for non-advancing steps
    # True for a step that occupies the field: an action or an explicit switch.
    # Markers (`stun_trigger`/`stun_end`), authored aftershocks, unknown agents
    # and redundant switches are all False — none of them advances the clock or
    # changes who is on field.
    occupies_field: bool


def walk_step_timeline(
    builds: dict[str, BuildSnapshot],
    steps: Sequence[SimulatedAttackStep],
    moves_db: dict[str, Any],
) -> list[StepTiming]:
    """Replay ``simulate()``'s clock over a rotation without simulating it.

    Policy code outside the simulator sometimes needs to know *when* a step
    happens before the simulation runs — Phase Flow windows (DESIGN §13.3) have
    to be handed to `simulate()` as an argument, and a window that disagrees
    with the simulator's own timing schedules its ticks at the wrong instants.

    This lives here, beside the loop it mirrors, precisely because the two must
    agree: a copy of these rules in another module would drift the first time a
    duration rule changed. `tests/unit/test_lumiflux_assembly.py` pins the
    agreement by comparing this walk against `simulate()`'s own emitted event
    timestamps, so drift fails CI rather than silently mis-scheduling ticks.

    The rules, all read off the step loop below:

    * a step whose ``agent_id`` is not in ``builds`` is skipped entirely;
    * ``stun_trigger`` / ``stun_end`` are markers — no clock advance;
    * an authored ``aftershock`` step resolves at the current instant and does
      not advance the clock or change who is on field;
    * an explicit ``switch`` step to someone who is not already active charges
      ``_SWITCH_DURATION_S``; a redundant one does nothing at all;
    * any other step implicitly switches first (charging the same second, but
      *not* for the very first agent on field) and then advances by the move's
      ``duration_s`` — the curated value when the move is in ``moves_db``, and
      the same ``1.0`` fallback the loop uses when it is not.
    """
    timings: list[StepTiming] = []
    t = 0.0
    active_agent: str | None = None

    for index, step in enumerate(steps):
        agent_id = step.agent_id
        move_name = step.move_name
        if agent_id not in builds:
            continue
        if move_name in ("stun_trigger", "stun_end", "aftershock"):
            timings.append(
                StepTiming(
                    index=index,
                    agent_id=agent_id,
                    move_name=move_name,
                    t_switch=None,
                    t_start=t,
                    t_end=t,
                    occupies_field=False,
                )
            )
            continue

        if move_name == "switch":
            if agent_id == active_agent:
                # Redundant switch: `simulate()` warns and advances nothing.
                timings.append(
                    StepTiming(
                        index=index,
                        agent_id=agent_id,
                        move_name=move_name,
                        t_switch=None,
                        t_start=t,
                        t_end=t,
                        occupies_field=False,
                    )
                )
                continue
            t_switch = t
            active_agent = agent_id
            t += _SWITCH_DURATION_S
            timings.append(
                StepTiming(
                    index=index,
                    agent_id=agent_id,
                    move_name=move_name,
                    t_switch=t_switch,
                    t_start=t_switch,
                    t_end=t,
                    occupies_field=True,
                )
            )
            continue

        t_switch: float | None = None
        if agent_id != active_agent:
            t_switch = t
            if active_agent is not None:
                t += _SWITCH_DURATION_S
            active_agent = agent_id

        move_spec = None
        agent_key = _agent_key(builds[agent_id].agent_name)
        if agent_key in moves_db:
            move_spec = moves_db[agent_key].moves.get(move_name)
        duration_s = _step_duration_s(step, move_spec)

        t_start = t
        t += duration_s
        timings.append(
            StepTiming(
                index=index,
                agent_id=agent_id,
                move_name=move_name,
                t_switch=t_switch,
                t_start=t_start,
                t_end=t,
                occupies_field=True,
            )
        )

    return timings


@lru_cache(maxsize=1)
def _real_agent_moves() -> dict[str, Any]:
    """The committed per-agent move data, loaded once.

    The combo path builds a synthetic ``moves_db`` out of pre-resolved
    ``ComboStep``s, so a move's authored Lumiflux annotations are not otherwise
    reachable from there. Cached because `simulate_combo_steps` runs per team
    combo and re-reading ~26 JSON files per call would be a real cost.
    """
    from app.data.loaders.moves import load_agent_moves  # noqa: PLC0415

    return load_agent_moves()


def _lumiflux_move_fields(agent_name: str, attack_name: str) -> dict[str, Any]:
    """A real move entry's Lumiflux annotations, by agent and attack name.

    Returns the defaults (all off) whenever the agent has no move file or the
    attack is not one of its authored moves — which is every agent but a
    Lumiflux one, and most moves of that one.
    """
    agent_moves = _real_agent_moves().get(_agent_key(agent_name))
    move = agent_moves.moves.get(attack_name) if agent_moves else None
    if move is None:
        return {}
    return {
        "triggers_luminize": getattr(move, "triggers_luminize", False),
        "luminize_mult_bp": getattr(move, "luminize_mult_bp", 0),
        "lumiflux_points": getattr(move, "lumiflux_points", 0),
        "phase_flow_entry": getattr(move, "phase_flow_entry", False),
        "clears_voidflare_store": getattr(move, "clears_voidflare_store", False),
    }


def _aftershock_ready(
    spec: dict,
    agent_id: str,
    t: float,
    resources: dict[str, dict[str, float]],
    cd_until: dict[str, float],
    window: dict[str, list[float]],
    energy: dict[str, float] | None = None,
) -> bool:
    """Return True if the agent may fire an aftershock proc right now.

    Checks three independent gates (all must pass):
      1. Cooldown: t >= cd_until[agent_id]
      2. Resource: resource balance >= cost (energy dict for resource="energy")
      3. Window cap: procs in the last window_s seconds < max_per_window
    """
    if t < cd_until.get(agent_id, float("-inf")):
        return False

    # min_resource is an availability floor separate from cost (e.g. Orphie
    # requires ≥60 energy but only spends 30) — `ResourceBanks.can_afford`'s
    # `floor` argument is that distinction, not a rename of the cost.
    banks = ResourceBanks(energy if energy is not None else {}, resources)
    if not banks.can_afford(
        agent_id,
        spec.get("resource"),
        spec.get("cost", 0.0),
        floor=spec.get("min_resource"),
    ):
        return False

    max_per_window = spec.get("max_per_window")
    window_s = spec.get("window_s")
    if max_per_window is not None and window_s is not None:
        cutoff = t - window_s
        recent = sum(1 for ts in window.get(agent_id, []) if ts > cutoff)
        if recent >= max_per_window:
            return False

    return True


def _aftershock_consume(
    spec: dict,
    agent_id: str,
    t: float,
    resources: dict[str, dict[str, float]],
    cd_until: dict[str, float],
    window: dict[str, list[float]],
    energy: dict[str, float],
) -> None:
    """Record a fired proc: subtract cost, advance cooldown, append t to window."""
    resource = spec.get("resource")
    cost = spec.get("cost", 0.0)
    if resource and cost > 0:
        ResourceBanks(energy, resources).debit(agent_id, resource, cost)

    cooldown_s = spec.get("cooldown_s", 0.0)
    cd_until[agent_id] = t + cooldown_s

    agent_window = window.setdefault(agent_id, [])
    agent_window.append(t)
    # Prune entries outside the current window to keep the list bounded.
    window_s = spec.get("window_s")
    if window_s is not None:
        cutoff = t - window_s
        window[agent_id] = [ts for ts in agent_window if ts > cutoff]


def _dominant_buildup_element(attacks: list, agent_element: str) -> str:
    """Element carrying the most anomaly buildup across a move's DB attack rows.

    Used by the move-spec fallback, which collapses a multi-hit move into a
    single buildup total and therefore needs one element to attribute it to.
    Falls back to the first hit's element (then the agent's own element) when no
    row carries buildup, preserving the previous behaviour for single-element
    and zero-buildup moves.
    """
    if not attacks:
        return agent_element
    totals: dict[str, int] = {}
    for a in attacks:
        elem = getattr(a, "element", None)
        if elem:
            totals[elem] = totals.get(elem, 0) + (a.anomaly_buildup or 0)
    if totals and max(totals.values()) > 0:
        return max(totals, key=lambda e: totals[e])
    return getattr(attacks[0], "element", None) or agent_element


def _state_active(
    agent_states: dict[str, dict[str, float]],
    agent_id: str,
    state: str,
    t: float,
) -> bool:
    """Return True if the named state is active for agent_id at time t."""
    until_t = agent_states.get(agent_id, {}).get(state, float("-inf"))
    return until_t > t


def _resolve_aftershock(
    active_agent: str | None,
    builds: dict[str, BuildSnapshot],
    aftershock_specs: dict[str, AftershockSpec],
    hit_kind: str,
    hit_scope: str,
    t_hit: float,
    enemy: EnemyProfile,
    resources: dict[str, dict[str, float]],
    aftershock_cd_until: dict[str, float],
    aftershock_window: dict[str, list[float]],
    energy: dict[str, float],
    is_enemy_stunned: bool,
    agent_states: dict[str, dict[str, float]] | None = None,
    aftershock_chain: dict[str, dict] | None = None,
) -> list[TimelineEvent]:
    """Auto-emit aftershock procs from off-field agents in reaction to an on-field hit.

    OQ-A5 invariant: only fires when hit_kind == "hit" (never on emitted aftershock events).
    Mutates resources/cd_until/window/energy via _aftershock_consume for each proc.
    aftershock_chain tracks per-emitter repeat-chain state across calls (Pulchra pattern).
    Returns new aftershock TimelineEvents; caller appends them and updates totals.
    """
    if hit_kind != "hit":
        return []

    result: list[TimelineEvent] = []

    for emitter_id, spec in aftershock_specs.items():
        if spec.on_field_self:
            continue  # handled by _resolve_onfield_aftershock

        if spec.requires_off_field and emitter_id == active_agent:
            continue

        if hit_kind not in spec.react_to:
            continue

        if spec.react_scopes is not None and hit_scope not in spec.react_scopes:
            continue

        if spec.requires_state is not None and not _state_active(
            agent_states or {}, emitter_id, spec.requires_state, t_hit
        ):
            continue

        # Repeat-chain path (Pulchra): one proc per qualifying hit, capped at 1+repeat_max
        # per state window; last proc uses finisher_mv_bp.
        if spec.repeat_max > 0:
            window_until = (
                (agent_states or {})
                .get(emitter_id, {})
                .get(spec.requires_state or "", float("-inf"))
            )
            chain_map = aftershock_chain if aftershock_chain is not None else {}
            chain = chain_map.setdefault(emitter_id, {})
            if chain.get("window_until") != window_until:
                chain["window_until"] = window_until
                chain["procs_used"] = 0
            cap = 1 + spec.repeat_max
            if chain["procs_used"] >= cap:
                continue
            position = chain["procs_used"]
            chain["procs_used"] += 1
            mv = (
                spec.finisher_mv_bp
                if (position == cap - 1 and spec.finisher_mv_bp is not None)
                else spec.aftershock_mv_bp
            )

            emitter_build = builds[emitter_id]
            emitter_snap = replace(
                emitter_build, modifiers=_resolve_offfield_modifiers(emitter_id, builds)
            )
            result.append(
                _emit_aftershock_event(
                    emitter_id=emitter_id,
                    emitter_snap=emitter_snap,
                    enemy=enemy,
                    element=spec.element or emitter_build.agent_element,
                    mv=mv,
                    is_enemy_stunned=is_enemy_stunned,
                    on_field=False,
                    t_hit=t_hit,
                )
            )
            continue

        # Standard (non-chain) path: cooldown + resource + window-cap gating.
        spec_dict = spec.model_dump()
        if not _aftershock_ready(
            spec_dict,
            emitter_id,
            t_hit,
            resources,
            aftershock_cd_until,
            aftershock_window,
            energy,
        ):
            continue

        emitter_build = builds[emitter_id]
        emitter_snap = replace(
            emitter_build, modifiers=_resolve_offfield_modifiers(emitter_id, builds)
        )
        as_element_std = spec.element or emitter_build.agent_element

        result.extend(
            _emit_aftershock_event(
                emitter_id=emitter_id,
                emitter_snap=emitter_snap,
                enemy=enemy,
                element=as_element_std,
                mv=spec.aftershock_mv_bp,
                is_enemy_stunned=is_enemy_stunned,
                on_field=False,
                t_hit=t_hit,
            )
            for _ in range(spec.procs_per_trigger)
        )

        _aftershock_consume(
            spec_dict,
            emitter_id,
            t_hit,
            resources,
            aftershock_cd_until,
            aftershock_window,
            energy,
        )

    return result


def _resolve_onfield_aftershock(
    active_agent: str | None,
    builds: dict[str, BuildSnapshot],
    aftershock_specs: dict[str, AftershockSpec],
    hit_kind: str,
    hit_scope: str,
    t_hit: float,
    enemy: EnemyProfile,
    resources: dict[str, dict[str, float]],
    aftershock_cd_until: dict[str, float],
    aftershock_window: dict[str, list[float]],
    energy: dict[str, float],
    is_enemy_stunned: bool,
) -> list[TimelineEvent]:
    """Auto-emit aftershock procs for the active (on-field) agent under on_field_self specs.

    Uses the normal on-field build merge (own modifiers + teammate ACTIVE/TEAM buffs),
    unlike the off-field path which only includes TEAM buffs. Forces AFTERSHOCK_ACTIVE.
    Called from the same post-hit site as _resolve_aftershock, guarded on on_field_self.

    NB: this is generic infrastructure with no kit consumer yet — no agent JSON sets
    on_field_self=True (S0 Anby routes on-field self-emit through _resolve_wt_cascade
    instead). Exercised only by unit tests until a future on-field self-emit kit lands.
    """
    if hit_kind != "hit" or active_agent is None:
        return []

    result: list[TimelineEvent] = []

    for emitter_id, spec in aftershock_specs.items():
        if not spec.on_field_self:
            continue
        if emitter_id != active_agent:
            continue
        if hit_kind not in spec.react_to:
            continue
        if spec.react_scopes is not None and hit_scope not in spec.react_scopes:
            continue

        spec_dict = spec.model_dump()
        if not _aftershock_ready(
            spec_dict,
            emitter_id,
            t_hit,
            resources,
            aftershock_cd_until,
            aftershock_window,
            energy,
        ):
            continue

        emitter_build = builds[emitter_id]
        emitter_snap = replace(
            emitter_build, modifiers=_resolve_onfield_modifiers(emitter_id, builds)
        )
        as_element = spec.element or emitter_build.agent_element

        result.extend(
            _emit_aftershock_event(
                emitter_id=emitter_id,
                emitter_snap=emitter_snap,
                enemy=enemy,
                element=as_element,
                mv=spec.aftershock_mv_bp,
                is_enemy_stunned=is_enemy_stunned,
                on_field=True,
                t_hit=t_hit,
            )
            for _ in range(spec.procs_per_trigger)
        )

        _aftershock_consume(
            spec_dict,
            emitter_id,
            t_hit,
            resources,
            aftershock_cd_until,
            aftershock_window,
            energy,
        )

    return result


def _resolve_wt_cascade(
    active_agent: str | None,
    builds: dict[str, BuildSnapshot],
    aftershock_specs: dict[str, AftershockSpec],
    hit_scope: str,
    t_hit: float,
    enemy: EnemyProfile,
    is_enemy_stunned: bool,
    white_thunder: dict[str, int],
    wt_tally: dict[str, int],
    wt_vortex_tally: dict[str, int] | None = None,
) -> list[TimelineEvent]:
    """White Thunder cascade for S0 Anby's on-field self hits (special scope).

    Each qualifying hit consumes 1 WT stack and emits an extra-instance Aftershock
    (aftershock_mv_bp). When the per-enemy tally reaches wt_tally_cap, additionally
    emits Thunder Smite (wt_smite_mv_bp) then Boundary (wt_boundary_mv_bp).

    A second, independent tally (wt_vortex_tally) counts the same WT-consume
    events on its own modulus (wt_vortex_tally_cap) and emits the M6 vortex
    (wt_vortex_mv_bp) when it reaches cap, gated on wt_vortex_requires_mindscape.
    It does not share or reset wt_tally's counter — DB text describes "every 6
    White Thunder additional-DMG instances", a separate cadence from the cap-3
    Smite/Boundary chain, not a second threshold on the same counter.

    Uses the on-field build merge (own mods + teammate ACTIVE/TEAM buffs).
    Mutates white_thunder, wt_tally and wt_vortex_tally in place.
    """
    if active_agent is None:
        return []

    spec = aftershock_specs.get(active_agent)
    if spec is None or not spec.wt_consume_scopes:
        return []
    if hit_scope not in spec.wt_consume_scopes:
        return []
    if white_thunder.get(active_agent, 0) <= 0:
        return []

    result: list[TimelineEvent] = []

    # Consume 1 WT stack and emit extra-instance Aftershock.
    white_thunder[active_agent] -= 1
    wt_tally[active_agent] = wt_tally.get(active_agent, 0) + 1

    # Build on-field snapshot: own mods + teammate ACTIVE/TEAM buffs.
    emitter_build = builds[active_agent]
    emitter_snap = replace(
        emitter_build, modifiers=_resolve_onfield_modifiers(active_agent, builds)
    )
    as_element = spec.element or emitter_build.agent_element

    def _emit(mv: int) -> TimelineEvent:
        return _emit_aftershock_event(
            emitter_id=active_agent,
            emitter_snap=emitter_snap,
            enemy=enemy,
            element=as_element,
            mv=mv,
            is_enemy_stunned=is_enemy_stunned,
            on_field=True,
            t_hit=t_hit,
        )

    result.append(_emit(spec.aftershock_mv_bp))

    # Check tally threshold → Thunder Smite + Boundary.
    if wt_tally[active_agent] >= spec.wt_tally_cap:
        wt_tally[active_agent] = 0
        if spec.wt_smite_mv_bp is not None:
            result.append(_emit(spec.wt_smite_mv_bp))
        if spec.wt_boundary_mv_bp is not None:
            result.append(_emit(spec.wt_boundary_mv_bp))

    # Independent vortex tally (M6): same event stream, separate modulus.
    if wt_vortex_tally is not None and spec.wt_vortex_mv_bp is not None:
        wt_vortex_tally[active_agent] = wt_vortex_tally.get(active_agent, 0) + 1
        if wt_vortex_tally[active_agent] >= spec.wt_vortex_tally_cap:
            wt_vortex_tally[active_agent] = 0
            if emitter_build.mindscape_level >= spec.wt_vortex_requires_mindscape:
                result.append(_emit(spec.wt_vortex_mv_bp))

    return result


def _team_conditions_by_agent(builds: dict) -> dict[str, set]:
    """Team-composition conditions per member, owner-relative (#157).

    `simulate()` never derived these — they were wired only in `team_calculator`,
    which this path does not use. Every `*_IN_TEAM`-gated modifier was therefore
    inert here unless a caller declared the condition by hand: 28 modifiers across 18
    sources, including Burnice's +65% Fire Anomaly Buildup. On a real Jane+Burnice
    team that single dormant condition was the difference between Burn never
    applying and Burn + Disorder firing (-26% total damage).

    Reuses `team_calculator._derive_auto_conditions` rather than restating the rules,
    so the presence family (team-global, includes the owner) and the `same_*` family
    (owner-relative, excludes self) cannot drift between the two paths.

    Imported inside the function deliberately: `team_calculator` imports
    `simulate_combo_steps` from this module, so a top-level import here is a genuine
    circular import (verified — it raises on import). Duplicating the derivation to
    avoid the cycle would reintroduce exactly the drift this reuse exists to prevent.
    """
    from app.services.team_calculator import (  # noqa: PLC0415  (cycle, see docstring)
        TeamMember,
        _derive_auto_conditions,
    )

    members = {
        aid: TeamMember(
            build_id=aid,
            agent_name=getattr(b, "agent_name", ""),
            agent_element=getattr(b, "agent_element", ""),
            agent_specialty=getattr(b, "agent_specialty", "") or "",
            agent_faction_id=getattr(b, "agent_faction_id", 0) or 0,
        )
        for aid, b in builds.items()
    }
    return {
        aid: _derive_auto_conditions(me, [o for oid, o in members.items() if oid != aid])
        for aid, me in members.items()
    }


def simulate(
    builds: dict[str, BuildSnapshot],
    steps: list[SimulatedAttackStep],
    enemy: EnemyProfile,
    moves_db: dict[str, Any],
    *,
    lumiflux_specs: dict[str, LumifluxSpec] | None = None,
    initial_lumiflux_points: int = 0,
    phase_flow_windows: dict[str, list[tuple[float, float]]] | None = None,
    fluxed_elements: dict[str, str] | None = None,
) -> SimulationResult:
    """Evaluate sequential step-by-step combat events and buildup.

    Returns the simulation timeline of events, damage totals, and attributions.

    ``lumiflux_specs`` (keyed by ``agent_id``, default ``None`` == empty) names
    which builds are Lumiflux agents and supplies their Refringe coefficients
    (DESIGN §7.1). Production callers build it with
    ``lumiflux_assembly.assemble_lumiflux_inputs`` (Task 29); the default stays
    empty so a caller that legitimately has no team — ``simulate_single_hit`` —
    is byte-identical to every pre-Task-11 caller.

    ``initial_lumiflux_points`` seeds the per-enemy pool (Task 9's
    `LumifluxEnemyState`) before the first step runs. This is a convenience for
    tests that want to start mid-rotation with a partly-filled pool — it is
    **not** a stand-in for the real point-application call site any more, which
    now exists in the step-resolution loop below (Task 31, reading each move's
    ``lumiflux_points``). Nothing that claims to prove production reachability
    may pass it.

    ``phase_flow_windows`` (keyed by ``agent_id``, default ``None`` == empty),
    a list of ``(start_s, end_s)`` pairs — the time ranges during which that
    agent is in Phase Flow (P4, DESIGN §7.3). Also produced by
    ``assemble_lumiflux_inputs``, derived from the rotation's own swap events
    (DESIGN §13.3). Deterministic EV ticks land at
    ``start + k * spec.phase_flow_tick_s`` for every whole ``k >= 1`` up to
    (not including) ``end`` — a pure post-pass, so it needs no interleaving
    with the per-step loop's own clock and can't perturb any existing
    caller's output when left at the default empty dict.
    """
    t = 0.0
    gauges = {
        "physical": 0.0,
        "fire": 0.0,
        "ice": 0.0,
        "electric": 0.0,
        "ether": 0.0,
        "wind": 0.0,
    }

    # Active aura tracking
    active_aura: dict | None = None

    # P2 (Remielle DESIGN §7.1): per-enemy Lumiflux Buildup Point pool.
    # Single simulated enemy -> one scalar slot, same convention as
    # `frostbite_until`/`flinch_until`/`windswept_until` below: not a dict
    # keyed by enemy id. It is also not keyed by (enemy, agent) — any
    # Lumiflux agent's points land in this one slot, which is the
    # structural guarantee that a second Lumiflux agent shares the pool
    # rather than getting its own. `None` until the first point is applied
    # (`_record_lumiflux_points`, below `_get_enemy_stat`), invoked from the
    # step-resolution loop for any move declaring `lumiflux_points` (Task 31).
    # `initial_lumiflux_points` seeds this pool directly — a convenience for
    # starting a test mid-rotation, no longer a stand-in for a missing call
    # site.
    lumiflux_state: LumifluxEnemyState | None = (
        LumifluxEnemyState(points=initial_lumiflux_points, owner_agent_id=None, last_point_at=None)
        if initial_lumiflux_points > 0
        else None
    )
    lumiflux_specs = lumiflux_specs or {}
    phase_flow_windows = phase_flow_windows or {}
    fluxed_elements = fluxed_elements or {}

    # P1/P3 (DESIGN §7.2): each Lumiflux agent's own Voidflare store, keyed by
    # her agent_id -- unlike the shared per-enemy point pool (P2), the guide's
    # "Remielle can store a maximum of three Voidflares" is per-Lumiflux-agent,
    # so a second one gets her own deque rather than sharing.
    voidflare_stores: dict[str, deque[VoidflareRecord]] = {}

    # E-F3: Voidflare-store clears owed to Phase Flow entries, as a min-heap of
    # (window start time, agent id). Built up front from `phase_flow_windows`
    # and drained inside the step loop as the clock passes each entry, so the
    # clears land in true chronological order against in-loop captures rather
    # than all-at-once in a post-pass. Empty `phase_flow_windows` leaves this
    # empty and the drain is a no-op for every existing caller.
    _pending_vf_clears: list[tuple[float, str]] = [
        (_w_start, _vf_agent_id)
        for _vf_agent_id, _vf_windows in phase_flow_windows.items()
        for _w_start, _w_end in _vf_windows
    ]
    heapq.heapify(_pending_vf_clears)

    # E-F1: Phase Flow tick POINT applications, as a min-heap of (tick time,
    # agent id). The tick's *damage* stays a post-pass expected-value quantity
    # (it depends only on the window and the spec), but its *point state* has
    # to land inside the step loop at the tick's own timestamp -- otherwise
    # points earned by ticks arrive after every step has been resolved, and
    # nothing in-run can ever consume them. That was the starvation bug: a
    # rotation whose only point source was Phase Flow ticks could never fire a
    # Refringe, and Prismatic never saw tick-earned buildup. Same timestamps
    # the post-pass used, so sorted event order is unchanged.
    _pending_tick_points: list[tuple[float, str]] = []
    for _tp_agent_id, _tp_windows in phase_flow_windows.items():
        _tp_spec = lumiflux_specs.get(_tp_agent_id)
        if _tp_spec is None or phase_flow_expected_value(_tp_spec.flight_attack_points) <= 0:
            continue
        for _tp_start, _tp_end in _tp_windows:
            _tp_k = 1
            while True:
                _tp_t = _tp_start + _tp_k * _tp_spec.phase_flow_tick_s
                if _tp_t >= _tp_end:
                    break
                _pending_tick_points.append((_tp_t, _tp_agent_id))
                _tp_k += 1
    heapq.heapify(_pending_tick_points)

    def _drain_tick_points(until: float) -> None:
        """Apply every Phase Flow tick point owed at or before ``until``."""
        nonlocal lumiflux_state
        while _pending_tick_points and _pending_tick_points[0][0] <= until:
            _tick_t, _tick_agent = heapq.heappop(_pending_tick_points)
            _tick_spec = lumiflux_specs[_tick_agent]
            lumiflux_state = _record_lumiflux_points(
                lumiflux_state,
                _tick_spec,
                phase_flow_expected_value(_tick_spec.flight_attack_points),
                agent_id=_tick_agent,
                t=_tick_t,
                events=events,
            )

    # P4b (Task 16, DESIGN §7.3): per-agent set of Phase Flow window start
    # times whose unlock Assist has already auto-fired -- "once per Phase
    # Flow," so a second legal swap-in during the SAME window must not
    # re-trigger it, while a later, different window may.
    _phase_flow_unlock_fired: dict[str, set[float]] = {}

    # F-18: 3s per-attribute anomaly CD + global 3s disorder CD (Arkkus rules).
    # An Ultimate resets both. Held gauges (threshold reached during CD) are not
    # reset/dropped — the trigger fires once the CD lapses.
    _team_conds = _team_conditions_by_agent(builds)
    anomaly_cd_until: dict[str, float] = {}
    disorder_cd_until = 0.0

    # F-11/F-23a: Frostbite / Flinch enemy-state windows, opened by Shatter /
    # Assault triggers respectively. Single simulated enemy -> scalar timestamps.
    frostbite_until = 0.0
    flinch_until = 0.0
    # F-11/F-23b: Windswept Direct-DMG window, opened by a Windswept trigger.
    windswept_until = 0.0

    # F-17: per-element trigger count driving threshold escalation
    # (Base × 1.02^(n−1), n capped at 10 — Leifa). Never reset (persists for the
    # whole sim); wind uses the same curve here until S-4 adds its entry-curve
    # first-two-trigger values.
    anomaly_trigger_counts: dict[str, int] = {}

    # F-20: per-element buildup contributions since the last trigger, keyed by
    # contributing agent, plus each contributor's own (build, conditions)
    # snapshot at their own accumulation time. On trigger, proc damage is the
    # contribution-share-weighted sum of each contributor's own anomaly calc
    # (Arkkus: dual-anomaly-element comps split credit, not winner-take-all).
    # Reset alongside `gauges` on every trigger.
    gauge_contribs: dict[str, dict[str, float]] = {}
    gauge_snaps: dict[str, dict[str, tuple[BuildSnapshot, ActiveConditions]]] = {}

    # F-19: every hit timestamp the enemy actually takes (regardless of element),
    # used in the post-pass below to gate Shock/Corruption ticks on-hit. Gated
    # aura instances (one per Shock/Corruption trigger) are recorded here instead
    # of pre-scheduling ticks inline, since the gating hits may occur on later steps.
    hit_times: list[float] = []
    gated_aura_instances: list[dict] = []

    # Abloom trigger window: Notes-from-the-Chained 4pc grants AP+48 for 30s after
    # any Abloom fires (Condition.AFTER_ABLOOM_TRIGGER). Tracked sim-wide so the
    # condition persists into subsequent steps' stat resolution rather than being
    # wiped when active_conditions is rebuilt each step.
    abloom_trigger_until = -1.0

    # Refringe trigger window (Task 17, Condition.REFRINGE_TRIGGERED): same
    # shape as the Abloom window above, updated in the Refringe hook (Task
    # 11's call site) whenever `_resolve_refringe` actually fires.
    refringe_trigger_until = -1.0

    warnings = []
    events = []
    energy_timeline: list[tuple[float, str, float]] = []
    field_timeline: list[tuple[float, str]] = []
    active_agent: str | None = None

    totals = {
        "standard": 0,
        "anomaly": 0,
        "disorder": 0,
        "vortex": 0,
        "abloom": 0,
        "aftershock": 0,
        "kit_formula": 0,
        "luminize": 0,
        "phase_flow": 0,
        "total": 0,
    }

    per_agent_attribution = dict.fromkeys(builds, 0)

    # Energy bank — passive regen accrues each step; on-hit gain added in Task 4.
    energy: dict[str, float] = dict.fromkeys(builds, 0.0)

    # Aftershock substrate (Task 3): per-agent generic resource pools, cooldown
    # expiry times, and rolling proc-timestamp windows for the N-per-W cap.
    # Energy is excluded — it lives in the `energy` dict above (resource="energy"
    # specs route there via _aftershock_ready/_aftershock_consume).
    resources: dict[str, dict[str, float]] = {aid: {} for aid in builds}
    aftershock_cd_until: dict[str, float] = dict.fromkeys(builds, float("-inf"))
    aftershock_window: dict[str, list[float]] = {aid: [] for aid in builds}

    # P2 state machine: agent_states[agent_id][state_name] = wall-clock until_t.
    # Set when an authored move spec carries grants_state; persists while off-field.
    agent_states: dict[str, dict[str, float]] = {aid: {} for aid in builds}

    # P2 repeat-chain: per-emitter chain bookkeeping {window_until, procs_used}.
    aftershock_chain: dict[str, dict] = {}

    # P2 White Thunder (S0 Anby): stack counter (<=3) and per-enemy trigger tally.
    white_thunder: dict[str, int] = dict.fromkeys(builds, 0)
    wt_tally: dict[str, int] = dict.fromkeys(builds, 0)
    wt_vortex_tally: dict[str, int] = dict.fromkeys(builds, 0)

    # Velina Windbite counter (cap 2, single-enemy model).
    # Each Vortex increments it; when already at 2 the Vortex is "consuming"
    # (counter resets to 0, cyclone_kind="sweeping") and WINDBITE_CONSUMED is
    # added to the triggerer's resolve conditions so Core +150% arms on that proc only.
    windbite: int = 0

    # Build per-agent aftershock specs from the moves_db (Task 4).
    aftershock_specs: dict[str, AftershockSpec] = {}
    for _aid, _bld in builds.items():
        _akey = _agent_key(_bld.agent_name)
        _amoves = moves_db.get(_akey)
        if _amoves and getattr(_amoves, "aftershock", None):
            _spec_for_build = _amoves.aftershock
            # #90: a retag that exists only with Potential unlocked must not fire for a
            # locked build. Stripped HERE, where the build is in scope, rather than at
            # the use site — same contract as the repository's variant filter, so the
            # hit loop never learns the variant exists. `model_copy` keeps it per-build:
            # the spec objects come from a process-wide moves_db cache, so mutating in
            # place would leak one build's Potential state into every other build.
            #
            # None is normalised to 6 (fully unlocked), not to 0, and not via `or` —
            # rank 0 is falsy, so
            # `or 5` would flip a locked build to unlocked.
            _bld_rank = getattr(_bld, "potential_rank", None)
            if _spec_for_build.retag_requires_potential and (
                (6 if _bld_rank is None else _bld_rank) < 1
            ):
                _spec_for_build = _spec_for_build.model_copy(
                    update={"retag_as_aftershock": []}
                )
            aftershock_specs[_aid] = _spec_for_build
        # Initialize resource pools from spec initial values.
        if _aid in aftershock_specs:
            _spec = aftershock_specs[_aid]
            if _spec.resource and _spec.resource != "energy" and _spec.initial > 0:
                resources[_aid][_spec.resource] = _spec.initial

    # Resolve each agent's effective ER% multiplier once (static across steps).
    # Uses ALWAYS-only conditions so step-specific buffs don't skew the passive rate.
    _always_conds = ActiveConditions(active={Condition.ALWAYS})
    er_mult: dict[str, float] = {
        agent_id: 1.0
        + (_resolve_and_calc(b, _always_conds, AttackScope.ALL).stats.energy_regen / 10_000)
        for agent_id, b in builds.items()
    }

    # Track enemy stun state during simulation
    is_enemy_stunned = getattr(enemy, "is_stunned", False)

    def _apply_switch(target: str, *, charge_time: bool) -> None:
        """Emit a switch event, update active_agent, and optionally advance the clock 1s."""
        nonlocal t, active_agent
        events.append(
            TimelineEvent(
                t=t,
                kind="switch",
                agent_id=target,
                element=None,
                damage=None,
                aura_type=None,
                applier_agent_id=None,
                detail={"from": active_agent},
            )
        )
        active_agent = target
        if charge_time:
            field_timeline.append((t, active_agent))
        if charge_time:
            t += _SWITCH_DURATION_S
            for _aid, _bld in builds.items():
                _passive = _bld.agent_base_energy_regen / 100.0 * er_mult[_aid]
                _passive *= _SWITCH_DURATION_S
                energy[_aid] = min(energy[_aid] + _passive, _ENERGY_CAP)
            for _eid, _evalue in energy.items():
                energy_timeline.append((t, _eid, _evalue))

    def _check_phase_flow_swap_lock(
        target_agent_id: str, step_conditions: list[str] | None
    ) -> None:
        """P4b swap lock. Called for BOTH an explicit `switch` step and an
        implicit swap-in (any step acted by a non-active agent).

        E-F2 found this sitting inside the explicit-`switch` branch only,
        so a rotation that simply had her act -- without an authored switch
        step -- bypassed the lock entirely.

        A cheap rotation-validation WARNING, not a hard block on the swap
        ("prefer the cheap option", Task 16's brief). Only applies while the
        target is genuinely inside one of her own Phase Flow windows; a Chain
        Attack swap (flagged via the sentinel condition string) bypasses it
        entirely, matching the guide's "Chain Attack bypasses the lock".
        """
        if target_agent_id in phase_flow_windows and "chain_attack_swap" not in (
            step_conditions or []
        ):
            _pf_window = next(
                (
                    (w_start, w_end)
                    for w_start, w_end in phase_flow_windows[target_agent_id]
                    # E-F2: INCLUSIVE upper bound here, deliberately.
                    # Windows are half-open [start, end) everywhere else
                    # (ticks, entry clears), but the assembler closes a
                    # window at exactly the instant she is swapped back
                    # to -- so `t < w_end` put the very swap-in that ends
                    # the window outside it, and the lock never fired on
                    # any real assembler-produced window. That swap-in is
                    # precisely the event this lock exists to judge.
                    if w_start <= t <= w_end
                ),
                None,
            )
            if _pf_window is not None:
                _pf_start, _pf_end = _pf_window
                # Derived from state Task 11 already recorded (the
                # "refringe" events) -- no new bookkeeping to drift.
                # Inclusive upper bound: a Refringe landing at the
                # exact instant of the swap still counts (both are
                # timestamped at the same pre-switch `t`).
                _refringe_count = sum(
                    1
                    for e in events
                    if e.kind == "refringe"
                    and e.agent_id == target_agent_id
                    and _pf_start <= e.t <= t
                )
                # Informational only -- NOT part of the legality
                # predicate (see `is_phase_flow_swap_legal`'s
                # docstring for why a bare Voidflare-count fallback
                # would be vacuous here).
                _voidflare_count = sum(
                    1
                    for r in voidflare_stores.get(target_agent_id, ())
                    if _pf_start <= r.stored_at <= t
                )
                if not is_phase_flow_swap_legal(_refringe_count):
                    warnings.append(
                        f"Illegal Phase Flow swap-in: {target_agent_id} at "
                        f"t={t:.2f} has only {_refringe_count} Refringe(s) and "
                        f"{_voidflare_count} Voidflare(s) since Phase Flow entry "
                        f"(t={_pf_start:.2f}) -- the swap lock unlocks at 3 "
                        "Refringes or >=1 Voidflare (DESIGN_remielle.md §7.3). "
                        "Modeled as a rotation warning, not a hard gate (Task 16)."
                    )
                elif _pf_start not in _phase_flow_unlock_fired.get(
                    target_agent_id, set()
                ):
                    # Unlocking auto-triggers her Assist once per Phase Flow.
                    # Generic move-key lookup (not a Remielle-specific branch):
                    # any Lumiflux agent's moves.json may declare
                    # "phase_flow_unlock_assist"; absent today (Task 20 hasn't
                    # authored her real moves.json yet), so this is a no-op
                    # until then -- but the "fired" bookkeeping below still
                    # counts this window as checked, so a later legal swap in
                    # the SAME window can't re-fire it once a real move lands.
                    _phase_flow_unlock_fired.setdefault(target_agent_id, set()).add(
                        _pf_start
                    )
                    _unlock_build = builds[target_agent_id]
                    _unlock_agent_key = _agent_key(_unlock_build.agent_name)
                    _unlock_moves = moves_db.get(_unlock_agent_key)
                    _unlock_spec = (
                        _unlock_moves.moves.get("phase_flow_unlock_assist")
                        if _unlock_moves
                        else None
                    )
                    if _unlock_spec is not None:
                        _unlock_element = (
                            getattr(_unlock_spec, "element", None)
                            or _unlock_build.agent_element
                        )
                        _unlock_enemy_snap = EnemySnapshot(
                            level=enemy.level,
                            base_def=enemy.defense,
                            element_res=_get_enemy_stat(
                                enemy, f"{_unlock_element}_res", 0
                            ),
                            stun_dmg_mult=(
                                10000
                                + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000)
                            ),
                        )
                        _unlock_dmg = calculate_build_damage(
                            build=_unlock_build,
                            enemy=_unlock_enemy_snap,
                            multiplier=getattr(_unlock_spec, "multiplier_bp", 0),
                            conditions=ActiveConditions(active={Condition.ALWAYS}),
                            attack_scope=AttackScope.ASSIST_FOLLOWUP,
                            crit_mode=CritMode.EXPECTED,
                            is_stunned=is_enemy_stunned,
                            stun_dmg_mult=_unlock_enemy_snap.stun_dmg_mult,
                            with_attribution=True,
                        )
                        events.append(
                            TimelineEvent(
                                t=t,
                                kind="phase_flow_unlock_assist",
                                agent_id=target_agent_id,
                                element=_unlock_element,
                                damage=_unlock_dmg.damage.total,
                                aura_type=None,
                                applier_agent_id=target_agent_id,
                                detail={
                                    "refringe_count": _refringe_count,
                                    "voidflare_count": _voidflare_count,
                                    # #163: the optimizer's event->step mapper
                                    # needs these two to rebuild the hit against
                                    # each candidate. Without them the unlock
                                    # assist mapped to multiplier 0, i.e. was
                                    # scored as zero -- it is ordinary
                                    # ASSIST_FOLLOWUP standard damage.
                                    "multiplier": getattr(_unlock_spec, "multiplier_bp", 0),
                                    "scope": AttackScope.ASSIST_FOLLOWUP.value,
                                    "attack_name": "Phase Flow unlock Assist",
                                    "attribution": _serialize_attribution(
                                        _unlock_dmg.attribution
                                    ),
                                    "zone_formulas": _serialize_zone_formulas(
                                        _unlock_dmg.attribution
                                    ),
                                    "is_anomaly": False,
                                },
                            )
                        )
                        totals["standard"] += _unlock_dmg.damage.total
                        totals["total"] += _unlock_dmg.damage.total
                        per_agent_attribution[target_agent_id] += _unlock_dmg.damage.total

    for step in steps:
        acting_agent_id = step.agent_id
        if acting_agent_id not in builds:
            warnings.append(f"Build not found for agent ID: {acting_agent_id}")
            continue

        build = builds[acting_agent_id]
        move_name = step.move_name
        conditions = step.conditions

        # Stun state transitions from marker steps
        if move_name == "stun_trigger":
            is_enemy_stunned = True
            events.append(
                TimelineEvent(
                    t=t,
                    kind="stun_trigger",
                    agent_id=None,
                    element=None,
                    damage=None,
                    aura_type=None,
                    applier_agent_id=None,
                )
            )
            # Stun-onset Abloom (Nangong Yu M6 Vibrato:Modified, infra C2).
            if active_aura:
                _onset_events = _resolve_stun_onset_abloom(builds, moves_db, active_aura, t)
                for _ev in _onset_events:
                    events.append(_ev)
                    totals["abloom"] += _ev.damage or 0
                    totals["total"] += _ev.damage or 0
                    per_agent_attribution[_ev.agent_id] += _ev.damage or 0
                if _onset_events:
                    abloom_trigger_until = max(abloom_trigger_until, t + _ABLOOM_TRIGGER_BUFF_S)
            continue
        if move_name == "stun_end":
            is_enemy_stunned = False
            events.append(
                TimelineEvent(
                    t=t,
                    kind="stun_end",
                    agent_id=None,
                    element=None,
                    damage=None,
                    aura_type=None,
                    applier_agent_id=None,
                )
            )
            continue

        if move_name == "switch":
            if acting_agent_id != active_agent:
                _check_phase_flow_swap_lock(acting_agent_id, step.conditions)
                _apply_switch(acting_agent_id, charge_time=True)
            else:
                warnings.append(
                    f"Redundant switch: {acting_agent_id} is already the active agent — "
                    "no event emitted, no clock advance"
                )
            continue

        if move_name == "aftershock":
            # Authored aftershock step: resolve conditions with AFTERSHOCK_ACTIVE forced in,
            # compute one standard hit at step.aftershock_mv_bp, emit kind="aftershock" event.
            as_active_set = {Condition.ALWAYS, Condition.AFTERSHOCK_ACTIVE}
            for cond_str in step.conditions or []:
                with contextlib.suppress(ValueError):
                    as_active_set.add(Condition(cond_str))
            if is_enemy_stunned:
                as_active_set.add(Condition.ENEMY_STUNNED)
            if active_aura is not None:
                as_active_set.add(Condition.ENEMY_HAS_ANOMALY)
            as_conditions = ActiveConditions(
                active=as_active_set,
                stack_counts=dict(getattr(build, "stack_counts", {}) or {}),
            )

            # Inject specialty/element-derived conditions (parallel to main step path).
            _as_specialty = getattr(build, "agent_specialty", "")
            _as_elem = getattr(build, "agent_element", "")
            if _as_specialty:
                with contextlib.suppress(ValueError):
                    as_conditions.active.add(Condition(f"equipper_is_{_as_specialty.lower()}"))
            if _as_elem:
                with contextlib.suppress(ValueError):
                    as_conditions.active.add(Condition(f"equipper_is_{_as_elem.lower()}"))
            for _oid, _obld in builds.items():
                if _oid != acting_agent_id:
                    _oe = getattr(_obld, "agent_element", "").lower()
                    if _oe and _oe == _as_elem.lower():
                        as_conditions.active.add(Condition.SAME_ELEMENT_IN_TEAM)
                        break

            # Merge build modifiers the same way as on-field hits
            as_modifiers = list(build.modifiers)
            for other_id, other_build in builds.items():
                if other_id != acting_agent_id:
                    as_modifiers.extend(
                        [
                            m
                            for m in other_build.modifiers
                            if m.target
                            in (ModifierTarget.TEAM, "team", ModifierTarget.ACTIVE, "active")
                        ]
                    )
            as_build_snap = replace(build, modifiers=as_modifiers)

            # GTE-threshold conditions: prelim resolve without GTE-gated modifiers active.
            _as_prelim = resolve_build_stats(as_build_snap, as_conditions)
            inject_stat_threshold_conditions(as_conditions, _as_prelim)

            as_element = build.agent_element
            as_elem_res = _get_enemy_stat(enemy, f"{as_element}_res", 0)
            as_enemy_snap = EnemySnapshot(
                level=enemy.level,
                base_def=enemy.defense,
                element_res=as_elem_res,
                stun_dmg_mult=10000 + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000),
            )

            mv_bp = step.aftershock_mv_bp or 5000  # fallback: 50% ATK
            as_dmg_res = calculate_build_damage(
                build=as_build_snap,
                enemy=as_enemy_snap,
                multiplier=mv_bp,
                conditions=as_conditions,
                # #154: see _emit_aftershock_event — same reasoning, authored-step path.
                attack_scope=AttackScope.AFTERSHOCK,
                crit_mode=CritMode.EXPECTED,
                is_stunned=is_enemy_stunned,
                stun_dmg_mult=as_enemy_snap.stun_dmg_mult,
                with_attribution=True,
            )

            as_detail = {
                "multiplier": mv_bp,
                "scope": "all",
                "base_dmg": as_dmg_res.damage.base_dmg,
                "effective_atk": as_dmg_res.damage.effective_atk,
                "crit_mult": as_dmg_res.damage.crit_mult,
                "boost_mult": as_dmg_res.damage.boost_mult,
                "def_mult": as_dmg_res.damage.def_mult,
                "res_mult": as_dmg_res.damage.res_mult,
                "vulnerability_mult": as_dmg_res.damage.vulnerability_mult,
                "stun_mult": as_dmg_res.damage.stun_mult,
                "is_anomaly": False,
                "on_field": True,
                "aftershock": True,
                "attribution": _serialize_attribution(as_dmg_res.attribution),
                "zone_formulas": _serialize_zone_formulas(as_dmg_res.attribution),
            }

            events.append(
                TimelineEvent(
                    t=t,
                    kind="aftershock",
                    agent_id=acting_agent_id,
                    element=as_element,
                    damage=as_dmg_res.damage.total,
                    aura_type=None,
                    applier_agent_id=acting_agent_id,
                    detail=as_detail,
                )
            )
            totals["aftershock"] += as_dmg_res.damage.total
            totals["total"] += as_dmg_res.damage.total
            per_agent_attribution[acting_agent_id] += as_dmg_res.damage.total
            continue

        # Implicit switch: acting agent differs from the current on-field agent.
        # None→first does not charge the 1s swap window.
        if acting_agent_id != active_agent:
            # E-F2: the swap lock applies here too. It used to live only in the
            # explicit-`switch` branch above, so a rotation that just had her
            # act -- which is how most authored rotations swap -- never hit it.
            _check_phase_flow_swap_lock(acting_agent_id, step.conditions)
            _apply_switch(acting_agent_id, charge_time=(active_agent is not None))

        # Merge active acting agent modifiers with team-buff modifiers from teammates
        active_modifiers = list(build.modifiers)
        for other_id, other_build in builds.items():
            if other_id != acting_agent_id:
                active_modifiers.extend(
                    [
                        m
                        for m in other_build.modifiers
                        if m.target
                        in (ModifierTarget.TEAM, "team", ModifierTarget.ACTIVE, "active")
                    ]
                )

        # Resolve stats under team conditions
        acting_build_snap = replace(build, modifiers=active_modifiers)

        # Resolve active conditions as a set of Condition enums
        active_set = {Condition.ALWAYS}
        for cond_str in conditions:
            with contextlib.suppress(ValueError):
                active_set.add(Condition(cond_str))
        # #157: team-composition conditions, derived rather than user-declared.
        active_set |= _team_conds.get(acting_agent_id, set())
        active_conditions = ActiveConditions(
            active=active_set,
            stack_counts=dict(getattr(acting_build_snap, "stack_counts", {}) or {}),
        )
        if is_enemy_stunned:
            active_conditions.active.add(Condition.ENEMY_STUNNED)
        # Persist the Abloom-trigger buff window across steps (Notes from the Chained 4pc).
        if t < abloom_trigger_until:
            active_conditions.active.add(Condition.AFTER_ABLOOM_TRIGGER)
        # Persist the Refringe-trigger buff window across steps (Task 17,
        # Ode of Resurrected Wings, Task 19).
        if t < refringe_trigger_until:
            active_conditions.active.add(Condition.REFRINGE_TRIGGERED)
        # PHASE_FLOW_ACTIVE (Task 17, DESIGN §6): team-wide -- true for
        # WHOEVER is acting whenever any registered Lumiflux agent's Phase
        # Flow window contains the current clock, not just for her own steps.
        if any(
            w_start <= t < w_end
            for _pf_agent_windows in phase_flow_windows.values()
            for w_start, w_end in _pf_agent_windows
        ):
            active_conditions.active.add(Condition.PHASE_FLOW_ACTIVE)

        # Inject derived conditions for the acting agent
        specialty = getattr(acting_build_snap, "agent_specialty", "")
        elem = getattr(acting_build_snap, "agent_element", "")
        if specialty:
            spec_str = f"equipper_is_{specialty.lower()}"
            try:
                spec_cond = Condition(spec_str)
                active_conditions.active.add(spec_cond)
            except ValueError:
                pass
        if elem:
            elem_str = f"equipper_is_{elem.lower()}"
            try:
                elem_cond = Condition(elem_str)
                active_conditions.active.add(elem_cond)
            except ValueError:
                pass

        # Check if same element in team
        same_elem = False
        for other_id, other_build in builds.items():
            other_elem = getattr(other_build, "agent_element", "").lower()
            if other_id != acting_agent_id and other_elem == elem.lower():
                same_elem = True
                break
        if same_elem:
            active_conditions.active.add(Condition.SAME_ELEMENT_IN_TEAM)

        # Auto-inject aura-derived conditions
        if active_aura is not None:
            active_conditions.active.add(Condition.ENEMY_HAS_ANOMALY)

        # Prismatic (Task 18, DESIGN §6/§7.1): true while the enemy holds
        # >=1 Lumiflux Buildup Point, plus an 8s linger after the pool
        # EMPTIES. E-F5(b) / hardening Task 13: this used to measure the
        # linger from `last_point_at`, the last time a point was ever
        # applied, which cut the buff short by however long the points sat
        # unspent. The DB text ties the 8s to removal -- "Prismatic is
        # removed when the enemy no longer has Lumiflux Buildup. After
        # Prismatic is removed, the Anomaly Buildup Rate increase persists
        # for an additional 8s" -- and the pool is what Prismatic tracks, so
        # removal is the emptying instant.
        if lumiflux_state is not None and (
            lumiflux_state.points > 0
            or (
                lumiflux_state.emptied_at is not None
                and t - lumiflux_state.emptied_at < _PRISMATIC_LINGER_S
            )
        ):
            active_conditions.active.add(Condition.LUMIFLUX_BUILDUP_ACTIVE)

        # OFF_FIELD_OR_5S_AFTER_SWAP: true within the 5s window after the acting
        # agent's most recent swap-in (field_timeline records swap times).
        _last_entry_t = next(
            (t_e for t_e, ag in reversed(field_timeline) if ag == acting_agent_id),
            None,
        )
        if _last_entry_t is not None and (t - _last_entry_t) < _OFF_FIELD_SWAP_WINDOW_S:
            active_conditions.active.add(Condition.OFF_FIELD_OR_5S_AFTER_SWAP)

        # Stat-threshold conditions: preliminary stat resolve (GTE-gated modifiers
        # are inactive here, giving the correct threshold baseline).
        _prelim_stats = resolve_build_stats(acting_build_snap, active_conditions)
        inject_stat_threshold_conditions(active_conditions, _prelim_stats)

        ctx = _resolve_and_calc(acting_build_snap, active_conditions, AttackScope.ALL)

        # Lookup move specs
        move_spec = None
        agent_key = _agent_key(build.agent_name)
        if agent_key in moves_db:
            move_spec = moves_db[agent_key].moves.get(move_name)

        # Issue #149: a real move that resolved to no DB attack rows contributes no
        # direct damage at all. Every marker (`switch`, `stun_trigger`, `stun_end`,
        # `aftershock`) already `continue`d above, so reaching here with an empty list
        # always means the rows were expected and are not there — a data gap, not a
        # legitimately hitless step.
        #
        # This is deliberately separate from the `Move spec missing` warning below.
        # The two failures are independent (curation without rows, rows without
        # curation, both, neither), and the dangerous combination is precisely the one
        # the other warning stays quiet on: with a curated spec present the step still
        # produces anomaly damage off the spec's buildup, so the timeline looks healthy
        # while the hit is gone. Silent is the one thing it must not be.
        if not step.attacks:
            warnings.append(
                f"No attack rows resolved for '{move_name}' on {build.agent_name} — the "
                f"step deals no direct damage. The move name may not match the DB, or "
                f"this agent's attacks may not be seeded."
            )

        if not move_spec:
            # Tolerant fallback: buildup and element come from DB attack rows;
            # duration is unknown so we approximate; scope is derived from skill_key
            # using the same canonical map as combo_step_resolver (avoids drift).
            _first_attack = step.attacks[0] if step.attacks else None
            scope = (
                scope_for_skill_key(_first_attack.skill_key, _first_attack.name)
                if _first_attack is not None
                else AttackScope.ALL
            )
            duration_s = 1.0
            hits = len(step.attacks) if step.attacks else 1
            buildup = sum(a.anomaly_buildup for a in step.attacks) if step.attacks else 0
            # Derived from this step's own rows, so this step's hit count is the
            # right divisor — see the curated branch below for why they can differ.
            buildup_hits = hits
            # The whole step's buildup is applied as one aura, so tag it with the
            # element that actually carries that buildup — not attacks[0]. Many
            # multi-element strings open on a zero-buildup Physical hit (Miyabi,
            # Lycaon, Zhu Yuan, Yanagi ...), and keying off the first hit applied
            # every point of Ice/Ether/Electric buildup to Physical instead.
            element = _dominant_buildup_element(step.attacks, build.agent_element)
            warnings.append(
                f"Move spec missing for '{move_name}' on {build.agent_name} "
                "— duration approximate (scope and buildup derived from DB)"
            )
        else:
            # Sliced per press for a single-tap `sequential` step, the same way the
            # buildup below is — see `_step_duration_s`.
            duration_s = _step_duration_s(step, move_spec)
            hits = len(step.attacks) if step.attacks else (move_spec.hits or 1)
            # A curated `buildup` is authored as the whole-MOVE total, but a
            # `hit_mode='sequential'` step is only one BUTTON PRESS of that move:
            # combo_step_resolver and optimizer_pipeline always resolve those
            # single-tap (one row per step, hit_index cycling), so `len(step.attacks)`
            # is 1 while the authored total covers the whole cycle. Dividing by 1
            # applied the entire cycle's buildup on *every* press — a 5x over-count on
            # Aria's Perfect Pitch, Grace's High-Pressure Spike and Burnice's Direct
            # Flame Blend. Spread it over the authored cycle length instead.
            #
            # Gated on the row's own `hit_mode`, NOT on `move_spec.hits > len(attacks)`:
            # for an ATOMIC move the authored `hits` is an animation-hit count that
            # legitimately exceeds the DB row count (Burnice's Stirring Method authors
            # 6 over 2 rows; several Yuzuha moves author 3-5 over 1), and every row of
            # an atomic move lands in this one step — so there this step's hit count is
            # already the right divisor and must not change.
            # Shared with `_step_duration_s` rather than restated: the gauge divisor and
            # the clock divisor apply to the same steps, and the two drifting apart is
            # precisely the state this code was in before (#83).
            _seq_slice = _is_sequential_slice(step, move_spec)
            if move_spec.buildup is not None:
                buildup = move_spec.buildup
                buildup_hits = (move_spec.hits or 1) if _seq_slice else hits
            else:
                # An OMITTED buildup is not an authored zero. These specs exist to carry
                # non-buildup curation (`grants_state`, `grants_full_charge`, aftershock
                # re-tags) and never meant to suppress the move's gauge — but collapsing
                # None to 0 silently deleted every point of it for 9 entries across
                # Pulchra and Soldier 0 - Anby, including S0 Anby's whole basic combo.
                # Fall back to the same per-step DB row sum the no-spec path uses, which
                # is already this step's own total — so it divides by this step's hits,
                # never the sequential cycle length. An explicit 0 still suppresses; all
                # 18 of those are moves the DB independently agrees carry no gauge.
                buildup = sum(a.anomaly_buildup for a in step.attacks) if step.attacks else 0
                buildup_hits = hits
            # Force consolidated moves to evaluate as a single consolidated hit/buildup tick
            if getattr(move_spec, "consolidated", False):
                hits = 1
                buildup_hits = 1
            element = move_spec.element or build.agent_element
            scope = move_spec.scope or AttackScope.ALL

        # Kit `formulas[]` of quantity `anom_buildup` (Burnice's afterburn: +60 fire
        # gauge) add to this step's gauge. Folding them into the move's buildup total
        # before the buildup loop runs is deliberate: they then flow through
        # calculate_buildup's bonuses, the per-agent gauge contributions, and the
        # anomaly-trigger check for free, instead of a second copy of that machinery.
        # The fold is only sound while the formula's element matches the step's — a
        # cross-element gauge instance would need its own aura, so warn and skip.
        # Tracked separately from the move's own `buildup` because the two carry
        # different bases: a kit formula's gauge is granted once per *step*, while a
        # curated `buildup` is the whole *move*'s total. They need different divisors
        # (see `buildup_hits` above), so they can no longer share one accumulator.
        kit_buildup = 0
        _kit_formulas: tuple[KitFormula, ...] = getattr(acting_build_snap, "kit_formulas", ())
        for _kf in _kit_formulas:
            if _kf.quantity != "anom_buildup" or _kf.scope != scope:
                continue
            if _kf.element is not None and _kf.element != element:
                warnings.append(
                    f"{build.agent_name}: kit formula '{_kf.name}' applies {_kf.element} "
                    f"buildup on a {element} move — cross-element kit buildup is not "
                    f"modelled, so it was skipped"
                )
                continue
            kit_buildup += _kf.buildup

        # F-18: an Ultimate resets both the per-attribute anomaly CD and the
        # global disorder CD (Arkkus rules).
        if scope == AttackScope.ULTIMATE:
            anomaly_cd_until = {}
            disorder_cd_until = 0.0

        # Bill the step's resources.
        # Ultimates spend Decibels (not Energy) — see DESIGN_energy_regen.md §Non-goals.
        #
        # Three branches (DESIGN_channeled_moves.md §4.5), only the third of which is what
        # this used to do unconditionally: a channel bills entry + drain × hold + release, a
        # move that binds its own cost key bills that mode's price, and everything else
        # bills `Agent.ex_energy_cost` exactly as before. The middle branch is a live fix on
        # its own — Burnice's Tossing Method costs 10 and was billed 40, because one scalar
        # cannot hold an agent's six figures.
        _channel = getattr(move_spec, "channel", None)
        _binds_key = bool(getattr(move_spec, "cost_key", None))
        if scope == AttackScope.EX_SPECIAL or _channel is not None or _binds_key:
            _banks = ResourceBanks(energy, resources)
            _costs = getattr(build, "resource_costs", None) or {}
            _billed_s = getattr(step, "channel_s", None)
            if _channel is not None:
                # §4.6: you cannot hold longer than the bank funds. This is what makes ER%
                # and on-hit energy gain buy DAMAGE rather than merely gate whether an EX
                # fires at all — the `project_energy_regen` modelling gap.
                _requested_s = _billed_s if _billed_s is not None else _channel.default_s
                _billed_s, _clamp_warning = clamp_channel_to_bank(
                    _channel,
                    _costs,
                    _banks,
                    acting_agent_id,
                    requested_s=_requested_s,
                    move_name=move_name,
                )
                if _clamp_warning:
                    warnings.append(f"{build.agent_name}: {_clamp_warning}")
            bill = bill_for_move(
                move_spec,
                _costs,
                channel_s=_billed_s,
                ex_energy_cost=build.ex_energy_cost,
                move_name=move_name,
            )
            warnings.extend(f"{build.agent_name}: {_w}" for _w in bill.warnings)
            if _banks.balance(acting_agent_id, bill.resource) < bill.amount:
                warnings.append(
                    f"{build.agent_name}: '{move_name}' used with insufficient "
                    f"{bill.resource} "
                    f"({_banks.balance(acting_agent_id, bill.resource):.1f} < "
                    f"{bill.amount}); bank clamped to 0"
                )
            _banks.debit(acting_agent_id, bill.resource, bill.amount)
            events.append(
                TimelineEvent(
                    t=t,
                    kind="energy_spend",
                    agent_id=acting_agent_id,
                    element=None,
                    damage=None,
                    aura_type=None,
                    applier_agent_id=None,
                    detail={
                        "cost": bill.amount,
                        "move": move_name,
                        "resource": bill.resource,
                    },
                )
            )

        # E-F3 (a): Phase Flow entry clears the equipper's Voidflare store.
        # Core text: "All stored Voidflares are cleared when Remielle enters
        # the Phase Flow state or after using Basic Attack: Rainbow's End or
        # Basic Attack: Fleeting Grace." Driven off each window's START time
        # and drained here, inside the step loop, so a clear interleaves with
        # real captures in chronological order -- a window opening at t=5 must
        # wipe a t=2 capture but must NOT retroactively wipe a t=10 one.
        # Sub-step precision caveat: a window whose start falls strictly
        # inside a step clears at that step's start instead, so a capture
        # earlier in the same step survives. In practice windows open at a
        # swap-out, which is always a step boundary, so the two coincide.
        while _pending_vf_clears and _pending_vf_clears[0][0] <= t:
            _clear_at, _clear_agent = heapq.heappop(_pending_vf_clears)
            if _clear_agent in lumiflux_specs:
                voidflare_stores[_clear_agent] = clear_voidflare_store(
                    lumiflux_specs[_clear_agent].voidflare_cap
                )

        # E-F1: apply any Phase Flow tick points owed by now, so this step's
        # Refringe check and Prismatic gate can actually see them. Drained
        # after the entry clears above; the first tick of a window is one full
        # cadence after its start, so the two never contend for a timestamp.
        _drain_tick_points(t)

        t_start = t
        t += duration_s

        # P2 grants_state side-effect: if the move spec sets a state, activate it now
        # at wall-clock t_start so hits later in this step can still react to it.
        if move_spec and getattr(move_spec, "grants_state", None):
            _gs_name = move_spec.grants_state
            _gs_dur = getattr(move_spec, "state_duration_s", None) or 0.0
            agent_states.setdefault(acting_agent_id, {})[_gs_name] = t_start + _gs_dur

        # P2 grants_full_charge side-effect: EX/Ult that fully charges Silver Star → WT=3.
        if move_spec and getattr(move_spec, "grants_full_charge", None) == "silver_star":
            white_thunder[acting_agent_id] = 3

        # Accrue passive energy regen for ALL agents over this step's duration.
        for _agent_id, _build in builds.items():
            _passive = _build.agent_base_energy_regen / 100.0 * er_mult[_agent_id] * duration_s
            energy[_agent_id] = min(energy[_agent_id] + _passive, _ENERGY_CAP)

        # Snapshot aura state at step start for Abloom trigger check (fires if aura existed here).
        # A *copy*, not an alias: a burst anomaly re-applied inside this same step rewrites
        # `active_aura["dmg_per_proc"]`/`applier_id` in place, and Abloom must still fraction
        # the aura as it stood when the step began — that is the whole point of the variable.
        # Aliasing it let a strong re-applier's per-proc leak backwards into the Abloom basis
        # (measured 20x on a weak-opener / strong-reapplier pair). Read-only downstream, so a
        # shallow copy is sufficient.
        pre_step_aura = dict(active_aura) if active_aura else None

        # Channel gauge split (Task 10b, owner ruling D-CH3): gauge and damage in the same DB
        # row share a basis, so a hit's gauge is its OWN row's `anomaly_buildup` scaled by the
        # same factor as its multiplier. That replaces the authored-total-over-hit-count split
        # for channels, which gave a 0.5s tick the same gauge as Burnice's Fire Blast. The
        # per-role split needs no authoring: the DB's per-row values already sum to exactly
        # the figure the move file authors (41110 + 7155 = 48265).
        _scales = getattr(step, "attack_scales", None)
        _channel_buildups: list[int] | None = None
        if _scales is not None and step.attacks:
            _channel_buildups = [
                round((getattr(a, "anomaly_buildup", 0) or 0) * sc)
                for a, sc in zip(step.attacks, _scales, strict=False)
            ]
        _offsets = getattr(step, "attack_offsets", None)

        # Space out hit buildup and checks across duration
        for i in range(hits):
            # A channel's hits are not evenly spaced — ticks land one `tick_s` apart and the
            # release after the tail — and the spacing is what the 3s per-attribute re-trigger
            # CD and the anomaly decay clock read (DESIGN 4.4).
            # D-CH5, same rule as the damage loop below: a row whose gate does not hold
            # contributes no gauge, no energy and no hit time. Placed before `hit_times`
            # so a skipped row does not count toward the gated-window hit tally either.
            if (
                step.attacks
                and i < len(step.attacks)
                and not _row_is_live(step.attacks[i], is_stunned=is_enemy_stunned)
            ):
                continue

            if _offsets is not None and i < len(_offsets):
                t_hit = t_start + _offsets[i]
            else:
                t_hit = t_start + (i + 1) * (duration_s / hits)
            hit_times.append(t_hit)

            # Check active aura expiration
            if active_aura and t_hit >= active_aura["expires_at"]:
                events.append(
                    TimelineEvent(
                        t=active_aura["expires_at"],
                        kind="expire",
                        agent_id=None,
                        element=active_aura["element"],
                        damage=None,
                        aura_type=active_aura["element"],
                        applier_agent_id=active_aura["applier_id"],
                    )
                )
                active_aura = None

            # On-hit energy gain for the acting agent (ER% does NOT scale this).
            if step.attacks and i < len(step.attacks):
                gain = getattr(step.attacks[i], "energy_gain", 0) / 10_000
                energy[acting_agent_id] = min(
                    energy[acting_agent_id] + gain,
                    _ENERGY_CAP,
                )

            # Calculate and apply buildup for this hit
            if buildup > 0 or kit_buildup > 0:
                # Two different bases: the move's authored total spreads across the
                # whole move, a kit formula's gauge across this step's own hits.
                if _channel_buildups is not None and i < len(_channel_buildups):
                    move_buildup_val = _channel_buildups[i] + kit_buildup // hits
                else:
                    move_buildup_val = buildup // buildup_hits + kit_buildup // hits

                # Resolve element-specific buildup modifiers
                buildup_bonus = ctx.buffs.combat_bonuses.get("anomaly_buildup", 0)
                elem_buildup = ctx.buffs.combat_bonuses.get(f"{element}_anomaly_buildup", 0)
                anomaly_buildup_bonus = buildup_bonus + elem_buildup

                enemy_anomaly_res = _get_enemy_stat(enemy, f"anomaly_res_{element}", 0)
                stun_buildup_multiplier = _get_enemy_stat(enemy, "stun_buildup_multiplier", 10000)
                # F-11/F-23a: Flinch (+7.5% Daze/Stun taken for 10s post-Assault)
                # feeds into the same buildup path (manifests while is_stunned,
                # same as the enemy's own stun_buildup_multiplier above).
                if t_hit < flinch_until:
                    stun_buildup_multiplier += FLINCH_STUN_BUILDUP_BONUS

                hit_buildup = calculate_buildup(
                    move_buildup=move_buildup_val,
                    anomaly_buildup_bonus=anomaly_buildup_bonus,
                    anomaly_mastery=ctx.stats.anomaly_mastery,
                    enemy_anomaly_res=enemy_anomaly_res,
                    is_stunned=is_enemy_stunned,
                    stun_buildup_multiplier=stun_buildup_multiplier,
                )

                gauges[element] += hit_buildup

                # F-20: record this agent's share of the current gauge cycle and
                # snapshot their own (build, conditions) at this accumulation time.
                gauge_contribs.setdefault(element, {})
                gauge_contribs[element][acting_agent_id] = (
                    gauge_contribs[element].get(acting_agent_id, 0.0) + hit_buildup
                )
                gauge_snaps.setdefault(element, {})[acting_agent_id] = (
                    acting_build_snap,
                    active_conditions,
                )

                # Check threshold trigger
                capacity = _get_enemy_stat(enemy, f"anomaly_capacity_{element}", 100)
                # F-17: escalate the threshold Base × 1.02^(n−1) per repeat trigger
                # on this element, n capped at 10 (Leifa buildup curves).
                trigger_count = anomaly_trigger_counts.get(element, 0)
                trigger_n = trigger_count + 1
                escalation_exp = min(trigger_n, 10) - 1
                if element == "wind":
                    # F-17b: wind has no steady state of its own — entry #1 (n=1)
                    # and entry #2 (n=2) are cited Leifa constants, then from n=3
                    # it rejoins the generic (ether) curve at the same index
                    # (identity, not a re-floored table — Brain-confirmed
                    # 2026-07-05, DESIGN_math_review_sim.md "pure-power tail").
                    generic_capacity = _get_enemy_stat(enemy, "anomaly_capacity_ether", 100)
                    tier = WIND_TIER_BY_ETHER_CAPACITY.get(generic_capacity)
                    wind_entry2_trigger_n = 2
                    if tier is None:
                        threshold = generic_capacity * 100 * (1.02**escalation_exp)
                    elif trigger_n == 1:
                        threshold = capacity * 100
                    elif trigger_n == wind_entry2_trigger_n:
                        threshold = WIND_ENTRY2_BY_TIER[tier] * 100
                    else:
                        threshold = generic_capacity * 100 * (1.02**escalation_exp)
                else:
                    threshold = capacity * 100 * (1.02**escalation_exp)
                # F-18: gate on the per-attribute + global disorder CDs. If either
                # is still active, hold the gauge at/above threshold (do not reset,
                # do not drop buildup) — the trigger fires once both CDs lapse.
                if (
                    gauges[element] >= threshold
                    and t_hit >= anomaly_cd_until.get(element, 0.0)
                    and t_hit >= disorder_cd_until
                ):
                    gauges[element] = 0.0
                    anomaly_cd_until[element] = t_hit + 3.0
                    anomaly_trigger_counts[element] = trigger_count + 1
                    anomaly_type = ELEMENT_TO_ANOMALY.get(element, AnomalyType.BURN)

                    # F-11/F-23a: Shatter opens the Frostbite window (Crit DMG
                    # taken); Assault opens the Flinch window (Daze/Stun taken).
                    if anomaly_type == AnomalyType.SHATTER:
                        _frost_variant = ctx.buffs.combat_bonuses.get("frostbite_frost_variant", 0)
                        frostbite_until = t_hit + (
                            FROSTBITE_FROST_DURATION_S if _frost_variant else FROSTBITE_DURATION_S
                        )
                    elif anomaly_type == AnomalyType.ASSAULT:
                        flinch_until = t_hit + FLINCH_DURATION_S

                    # F-20: pull this cycle's contribution shares for `element`
                    # and reset them (mirrors the gauge reset above). Falls back
                    # to the current hit alone if, for any reason, nothing was
                    # recorded (defensive — the accumulation above always runs
                    # first when buildup > 0).
                    _element_contribs = gauge_contribs.pop(element, None) or {
                        acting_agent_id: hit_buildup
                    }
                    _element_snaps = gauge_snaps.pop(element, {})

                    # Anomaly trigger logic
                    duration = (
                        20.0
                        if element == "wind"
                        else _get_enemy_stat(enemy, "anomaly_duration_default", 10.0)
                    )

                    # F-11/F-23b: Windswept opens its Direct-DMG window for the
                    # aura's own lifetime (no separate secondary-state duration
                    # exists in the references for Windswept).
                    if anomaly_type == AnomalyType.WINDSWEPT:
                        windswept_until = t_hit + duration

                    # Set when a wind/non-wind disorder fires; consumed by the vortex block.
                    _vortex_elem: str | None = None
                    # The overridden aura's Refringe snapshot (DESIGN §7.1) — Vortex, like
                    # Disorder, fires off the just-ended aura and must inherit its value.
                    _old_refringe_mult = 10000
                    # True when this crossing re-applied a burst anomaly onto its own live
                    # aura: the aura is kept and refreshed rather than replaced, but the
                    # proc-damage block below still runs for the new instance.
                    _reapplied = False

                    if active_aura:
                        if active_aura["element"] != element:
                            # 1. Disorder override
                            old_elem = active_aura["element"]
                            old_anom = ELEMENT_TO_ANOMALY.get(old_elem, AnomalyType.BURN)
                            old_snap = active_aura["applier_snap"]

                            # H1: resolve under applier's conditions at application time
                            old_ctx = _resolve_and_calc(
                                old_snap, active_aura["applier_conditions"], AttackScope.ALL
                            )

                            disorder_dmg_bonus = old_ctx.buffs.combat_bonuses.get(
                                "disorder_dmg_bonus", 0
                            )
                            disorder_dmg_res = _get_enemy_stat(enemy, f"{old_elem}_res", 0)
                            # Alice core: +18%/s remaining Assault duration (max 180%).
                            _dur_rate = old_ctx.buffs.disorder_duration_bonus_rate
                            _remaining_s = active_aura["expires_at"] - t_hit
                            duration_disorder_bonus = (
                                int(_remaining_s * _dur_rate) if _dur_rate else 0
                            )
                            # Refringe snapshots into the aura at trigger time (DESIGN
                            # §7.1); Disorder on a Refringed aura inherits it explicitly
                            # (Disorder computes independently, unlike Abloom which
                            # fractions the already-Refringed `dmg_per_proc`).
                            _old_refringe_mult = active_aura.get("refringe_mult", 10000)

                            disorder_dmg = calculate_disorder_damage(
                                anomaly_type=old_anom,
                                atk=old_ctx.stats.atk,
                                anomaly_proficiency=old_ctx.stats.anomaly_proficiency,
                                attacker_level=old_snap.agent_level,
                                dmg_bonuses=old_ctx.dmg_bonuses,
                                # Attribute-anomaly DMG% bonuses (e.g. Grace's shock_dmg_bonus)
                                # apply to the triggering anomaly, not to Disorder (Leifa, F-22).
                                anomaly_dmg_bonus=old_ctx.buffs.anomaly_dmg_bonus,
                                disorder_dmg_bonus=disorder_dmg_bonus + duration_disorder_bonus,
                                enemy_base_def=enemy.defense,
                                enemy_level=enemy.level,
                                pen_ratio=old_ctx.stats.pen_ratio,
                                pen_flat=old_ctx.stats.pen_flat,
                                def_ignore=old_ctx.buffs.def_ignore,
                                enemy_res=disorder_dmg_res,
                                res_reduction=old_ctx.buffs.res_reduction,
                                res_ignore=old_ctx.buffs.res_ignore,
                                vulnerability_bonuses=old_ctx.vuln_bonuses,
                                is_stunned=is_enemy_stunned,
                                stun_dmg_mult=(
                                    10000
                                    + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000)
                                    + old_ctx.buffs.stun_dmg_mult_bonus
                                ),
                                remaining_duration=active_aura["expires_at"] - t_hit,
                                max_duration=active_aura["max_duration"],
                                stun_area_override=old_ctx.buffs.stun_area_override,
                                refringe_mult=_old_refringe_mult,
                            )

                            disorder_attr = build_step_attribution(
                                old_snap,
                                old_ctx.stats,
                                old_ctx.disc,
                                old_ctx.buffs,
                                is_anomaly=True,
                                damage=disorder_dmg,
                                multiplier=0,  # disorder MV is time-scaled, not a fixed constant
                                enemy_res=disorder_dmg_res,
                            )
                            disorder_detail = {
                                "multiplier": 0,
                                "base_dmg": disorder_dmg.base_dmg,
                                "effective_atk": old_ctx.stats.atk,
                                "anomaly_proficiency_mult": disorder_dmg.anomaly_prof_mult,
                                "anomaly_level_mult": disorder_dmg.level_mult,
                                "anomaly_dmg_bonus_mult": (
                                    disorder_dmg.anomaly_boost_mult
                                    * disorder_dmg.disorder_boost_mult
                                    // 10000
                                ),
                                "crit_mult": 0,
                                "boost_mult": disorder_dmg.boost_mult,
                                "def_mult": disorder_dmg.def_mult,
                                "res_mult": disorder_dmg.res_mult,
                                "vulnerability_mult": disorder_dmg.vulnerability_mult,
                                "stun_mult": disorder_dmg.stun_mult,
                                "level_factor": disorder_dmg.level_factor_val,
                                "effective_enemy_def": disorder_dmg.effective_enemy_def,
                                "stun_base_mult": disorder_dmg.stun_base_mult,
                                "is_anomaly": True,
                                "attribution": _serialize_attribution(disorder_attr),
                                "zone_formulas": _serialize_zone_formulas(disorder_attr),
                                "disorder_mv": disorder_dmg.base_dmg,
                                "disorder_mv_bp": (
                                    disorder_dmg.base_dmg * 10000 // old_ctx.stats.atk
                                ),
                                # Task 35: the overridden aura's Refringe snapshot, so the
                                # optimizer's event→step mapping can fold it into
                                # `procs_override`. `disorder_mv_bp` above derives from
                                # `base_dmg`, which is pre-Refringe (RefringeArea is applied
                                # after it, damage_calculator.py:774) — so the two are
                                # independent and combining them does not double-apply.
                                "refringe_mult": _old_refringe_mult,
                            }

                            _gated_old = active_aura.get("gated_instance")
                            if _gated_old is not None:
                                # F-19: no ticks were pre-scheduled for a gated aura;
                                # just cut its gating window short instead of pruning.
                                _gated_old["end_at"] = min(_gated_old["end_at"], t_hit)
                            else:
                                _prune_aura_ticks(
                                    events,
                                    totals,
                                    per_agent_attribution,
                                    old_elem,
                                    active_aura["applier_id"],
                                    t_hit,
                                )

                            events.append(
                                TimelineEvent(
                                    t=t_hit,
                                    kind="disorder",
                                    agent_id=acting_agent_id,
                                    element=old_elem,
                                    damage=disorder_dmg.total,
                                    aura_type=old_elem,
                                    applier_agent_id=active_aura["applier_id"],
                                    detail=disorder_detail,
                                )
                            )

                            totals["disorder"] += disorder_dmg.total
                            totals["total"] += disorder_dmg.total
                            per_agent_attribution[active_aura["applier_id"]] += disorder_dmg.total

                            # F-18: Disorder applies a global 3s CD blocking triggers
                            # of ANY attribute, on top of the per-attribute CD above.
                            disorder_cd_until = t_hit + 3.0

                            # Vortex fires on wind/non-wind interaction (Leifa).
                            if old_elem == "wind":
                                _vortex_elem = element  # non-wind lands on Windswept aura
                            elif element == "wind":
                                _vortex_elem = old_elem  # wind lands on non-wind aura

                            active_aura = None
                        else:
                            # 2. Same aura re-application (duration refresh)
                            active_aura["expires_at"] = t_hit + duration
                            _gated_refresh = active_aura.get("gated_instance")
                            if _gated_refresh is not None:
                                _gated_refresh["end_at"] = t_hit + duration
                            events.append(
                                TimelineEvent(
                                    t=t_hit,
                                    kind="refresh",
                                    agent_id=acting_agent_id,
                                    element=element,
                                    damage=None,
                                    aura_type=element,
                                    applier_agent_id=acting_agent_id,
                                )
                            )
                            if anomaly_type not in REPROC_ON_REAPPLY_TYPES:
                                # Tick anomalies: the procs are already scheduled off the
                                # original instance, so this crossing buys duration only.
                                continue
                            # Burst anomalies fall through to proc emission below — the
                            # aura is refreshed, but the damage instance is brand new.
                            # The aura now belongs to *this* application, so its applier
                            # fields move with it (Disorder off this aura must resolve
                            # under the current applier, not the one from N triggers ago).
                            _reapplied = True
                            active_aura["applier_id"] = acting_agent_id
                            active_aura["applier_snap"] = acting_build_snap
                            active_aura["applier_conditions"] = active_conditions
                            active_aura["applied_at"] = t_hit

                    if not _reapplied:
                        # Start new active aura
                        active_aura = {
                            "element": element,
                            "applier_id": acting_agent_id,
                            "applier_snap": acting_build_snap,
                            "applier_conditions": active_conditions,  # H1: applier snapshot
                            "applied_at": t_hit,
                            "expires_at": t_hit + duration,
                            "max_duration": duration,
                        }

                        # A re-application already emitted its own `refresh`; only a
                        # genuinely new aura gets an `anomaly` event.
                        events.append(
                            TimelineEvent(
                                t=t_hit,
                                kind="anomaly",
                                agent_id=acting_agent_id,
                                element=element,
                                damage=None,
                                aura_type=element,
                                applier_agent_id=acting_agent_id,
                                detail={"on_field": True},
                            )
                        )

                    # Refringe (DESIGN §7.1): if the enemy holds a Lumiflux Buildup
                    # Point and the triggering agent isn't the Lumiflux agent
                    # herself, consume one to buff THIS anomaly and snapshot the
                    # resulting multiplier onto the aura so Disorder/Vortex/Abloom
                    # inherit it later (Task 11).
                    (
                        lumiflux_state,
                        refringe_mult,
                        _refringing_agent_id,
                        _refringe_credit,
                    ) = _resolve_refringe(
                        lumiflux_state,
                        builds,
                        lumiflux_specs,
                        acting_agent_id,
                        active_conditions,
                        t_hit,
                        events,
                    )
                    active_aura["refringe_mult"] = refringe_mult
                    active_aura["refringe_credit"] = _refringe_credit
                    if _refringing_agent_id is not None:
                        refringe_trigger_until = max(
                            refringe_trigger_until, t_hit + _REFRINGE_TRIGGER_BUFF_S
                        )

                    # Voidflare capture (DESIGN §7.2): "when teammates trigger
                    # Refringe" -- i.e. only when Refringe actually fired above,
                    # not on every teammate anomaly trigger. Captured from the
                    # triggering teammate's own already-resolved `ctx` (this
                    # step's stats), never Remielle's and never the fluxed
                    # element -- `element` here is the anomaly's own attribute.
                    if _refringing_agent_id is not None:
                        _voidflare_spec = lumiflux_specs[_refringing_agent_id]
                        _record = VoidflareRecord(
                            element=element,
                            atk=ctx.stats.atk,
                            dmg_bonus_bp=sum(ctx.dmg_bonuses),
                            pen_ratio_bp=ctx.stats.pen_ratio,
                            pen_flat=ctx.stats.pen_flat,
                            anomaly_proficiency=ctx.stats.anomaly_proficiency,
                            refringe_coefficient_bp=refringe_mult - 10000,
                            stored_at=t_hit,
                            # Provenance only, never a damage input (E-8). The
                            # store is keyed by the Lumiflux agent, so without
                            # this a mixed store is indistinguishable downstream.
                            captured_from=acting_agent_id,
                        )
                        voidflare_stores[_refringing_agent_id] = store_voidflare(
                            voidflare_stores.get(_refringing_agent_id),
                            _record,
                            _voidflare_spec.voidflare_cap,
                        )

                    # Spawn anomaly proc damage ticks
                    procs = ANOMALY_PROC_COUNTS.get(anomaly_type, 1)
                    enemy_res = _get_enemy_stat(enemy, f"{element}_res", 0)

                    anomaly_enemy_snap = EnemySnapshot(
                        level=enemy.level,
                        base_def=enemy.defense,
                        element_res=enemy_res,
                        stun_dmg_mult=10000 + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000),
                    )
                    # F-20: proc damage is the contribution-share-weighted sum of
                    # each contributor's OWN anomaly calc (own snapshot/conditions
                    # at their own accumulation time), not 100% to whoever's hit
                    # happened to cross the threshold. A single contributor's
                    # share is exactly 1.0, reducing byte-for-byte to the prior
                    # (pre-F-20) single-snapshot behavior.
                    _contrib_ids = list(_element_contribs.keys()) or [acting_agent_id]
                    if len(_contrib_ids) == 1:
                        _solo_id = _contrib_ids[0]
                        _solo_snap, _solo_conditions = _element_snaps.get(
                            _solo_id, (acting_build_snap, active_conditions)
                        )
                        anomaly_build_res = calculate_build_anomaly(
                            build=_solo_snap,
                            enemy=anomaly_enemy_snap,
                            anomaly_type=anomaly_type.value,
                            conditions=_solo_conditions,
                            procs=procs,
                            is_stunned=is_enemy_stunned,
                            stun_dmg_mult=anomaly_enemy_snap.stun_dmg_mult,
                            with_attribution=True,
                            refringe_mult=refringe_mult,
                        )
                        anomaly_dmg_res = anomaly_build_res.damage
                        per_agent_shares = {_solo_id: 1.0}
                        _buildup_shares = {_solo_id: 1.0}
                    else:
                        _total_contrib = sum(_element_contribs.values())
                        _buildup_shares = {
                            aid: contrib / _total_contrib
                            for aid, contrib in _element_contribs.items()
                        }
                        _per_agent_res = {}
                        for aid in _contrib_ids:
                            _snap, _conds = _element_snaps.get(
                                aid, (acting_build_snap, active_conditions)
                            )
                            _per_agent_res[aid] = calculate_build_anomaly(
                                build=_snap,
                                enemy=anomaly_enemy_snap,
                                anomaly_type=anomaly_type.value,
                                conditions=_conds,
                                procs=procs,
                                is_stunned=is_enemy_stunned,
                                stun_dmg_mult=anomaly_enemy_snap.stun_dmg_mult,
                                with_attribution=True,
                                refringe_mult=refringe_mult,
                            )
                        # Each contributor's OWN term in the weighted sum
                        # (buildup share × their own per-proc damage) — this is
                        # both their absolute damage contribution and, once
                        # renormalized, their attribution share of the total. A
                        # near-zero-damage contributor (e.g. Bangboo) dilutes the
                        # total AND ends up with a near-zero attribution share,
                        # rather than being credited a flat slice of the total
                        # proportional only to the buildup it supplied.
                        _dmg_terms = {
                            aid: _buildup_shares[aid] * _per_agent_res[aid].damage.per_proc
                            for aid in _contrib_ids
                        }
                        _total_dmg_term = sum(_dmg_terms.values())
                        _weighted_per_proc = round(_total_dmg_term)
                        per_agent_shares = (
                            {aid: v / _total_dmg_term for aid, v in _dmg_terms.items()}
                            if _total_dmg_term > 0
                            else _buildup_shares
                        )
                        # Display-only breakdown fields (base_dmg, mult zones, etc.)
                        # come from the dominant (largest-share) contributor's own
                        # result; only the damage totals below are share-weighted.
                        _dominant_id = max(per_agent_shares, key=per_agent_shares.get)
                        anomaly_build_res = _per_agent_res[_dominant_id]
                        anomaly_dmg_res = replace(
                            anomaly_build_res.damage,
                            per_proc=_weighted_per_proc,
                            total=_weighted_per_proc * procs,
                        )
                    # Store per-proc DMG on the aura so Abloom can fraction it later
                    active_aura["dmg_per_proc"] = anomaly_dmg_res.per_proc
                    active_aura["per_agent_shares"] = per_agent_shares

                    anomaly_detail = {
                        "multiplier": 0,
                        # Consumed by sim_result_to_combo_evaluation: names the
                        # anomaly ("burn", "shock", …) on each tick's step result
                        # and its by_category bucket — without it the category
                        # falls back to the event kind ("anomaly_tick").
                        "anomaly_type": anomaly_type,
                        "base_dmg": anomaly_dmg_res.base_dmg,
                        "effective_atk": ctx.stats.atk,
                        "anomaly_proficiency_mult": anomaly_dmg_res.anomaly_prof_mult,
                        "anomaly_level_mult": anomaly_dmg_res.level_mult,
                        "anomaly_dmg_bonus_mult": anomaly_dmg_res.anomaly_boost_mult,
                        "crit_mult": 0,
                        "boost_mult": anomaly_dmg_res.boost_mult,
                        "def_mult": anomaly_dmg_res.def_mult,
                        "res_mult": anomaly_dmg_res.res_mult,
                        "vulnerability_mult": anomaly_dmg_res.vulnerability_mult,
                        "stun_mult": anomaly_dmg_res.stun_mult,
                        "level_factor": anomaly_dmg_res.level_factor_val,
                        "effective_enemy_def": anomaly_dmg_res.effective_enemy_def,
                        "stun_base_mult": anomaly_dmg_res.stun_base_mult,
                        "is_anomaly": True,
                        "attribution": _serialize_attribution(anomaly_build_res.attribution),
                        "zone_formulas": _serialize_zone_formulas(anomaly_build_res.attribution),
                        # F-20: buildup-contribution shares behind the weighted per_proc.
                        "per_agent_shares": per_agent_shares,
                        # Task 26 (issue #112): the *buildup* shares, which are NOT
                        # `per_agent_shares` — that one is renormalized by each
                        # contributor's own per-proc damage. The optimizer needs the
                        # raw buildup share, because it re-scores the whole anomaly
                        # against the candidate build and then wants only the target's
                        # slice: target_term = buildup_share * per_proc(candidate).
                        # Using the damage-weighted share there would divide out the
                        # very per-proc the rescore is recomputing.
                        "per_agent_buildup_shares": _buildup_shares,
                        # Task 35 (E-6): this aura's Refringe snapshot. Every tick of one
                        # aura shares it, so the optimizer can carry it as a scalar on
                        # `procs_override` rather than needing a per-tick field.
                        "refringe_mult": refringe_mult,
                        # #160: the coefficient's INPUTS, not just its collapsed
                        # value, so the optimizer can rebuild it at each
                        # candidate's AP and credit her the uplift on a tick that
                        # `_owns` otherwise drops whole. None unless Refringe fired.
                        "refringe_credit": _refringe_credit,
                    }

                    if anomaly_type in GATED_ANOMALY_TYPES:
                        # F-19: Shock/Corruption ticks are on-hit-gated in the
                        # post-pass below, not pre-scheduled uniformly here.
                        active_aura["gated_instance"] = {
                            "anomaly_type": anomaly_type,
                            "element": element,
                            "applier_id": acting_agent_id,
                            "applied_at": t_hit,
                            "end_at": t_hit + duration,
                            "procs": procs,
                            "dmg_per_proc": anomaly_dmg_res.per_proc,
                            "detail": anomaly_detail,
                            "per_agent_shares": per_agent_shares,
                        }
                        gated_aura_instances.append(active_aura["gated_instance"])
                    else:
                        # Spread anomaly procs across duration (unconditional timer)
                        for j in range(procs):
                            t_tick = t_hit + j * (duration / procs)
                            tick_dmg = anomaly_dmg_res.per_proc
                            tick_split = _split_amount_by_share(tick_dmg, per_agent_shares)

                            events.append(
                                TimelineEvent(
                                    t=t_tick,
                                    kind="anomaly_tick",
                                    agent_id=acting_agent_id,
                                    element=element,
                                    damage=tick_dmg,
                                    aura_type=element,
                                    applier_agent_id=acting_agent_id,
                                    detail={**anomaly_detail, "per_agent_attribution": tick_split},
                                )
                            )
                            totals["anomaly"] += tick_dmg
                            totals["total"] += tick_dmg
                            for _aid, _dmg in tick_split.items():
                                per_agent_attribution[_aid] += _dmg

                    # 3. Vortex triggers on wind/non-wind anomaly interaction (Leifa).
                    # _vortex_elem is set above when a wind/non-wind disorder fired.
                    vortex_kind = (
                        ELEMENT_TO_VORTEX_KIND.get(_vortex_elem) if _vortex_elem else None
                    )

                    if vortex_kind:
                        # Windbite state machine (Velina Core Passive).
                        # Each Vortex increments the counter (cap 2). When already at 2,
                        # this Vortex is "consuming": counter resets to 0, cyclone is Sweeping,
                        # and WINDBITE_CONSUMED is injected into the triggerer's resolve so
                        # Core +150% Vortex DMG arms for exactly this proc.
                        _wb_before = windbite
                        _wb_consuming = _wb_before == _WINDBITE_CAP
                        if _wb_consuming:
                            windbite = 0
                            _cyclone_kind = "sweeping"
                        else:
                            windbite = _wb_before + 1
                            _cyclone_kind = "condensed"
                        # Conditions for this Vortex's stat resolve (WINDBITE_CONSUMED injected
                        # only on the consuming Vortex so Core +150% applies on exactly that proc).
                        _v_conditions = (
                            ActiveConditions(
                                active=active_conditions.active | {Condition.WINDBITE_CONSUMED},
                                stack_counts=dict(active_conditions.stack_counts),
                            )
                            if _wb_consuming
                            else active_conditions
                        )

                        # Check if any team member is vortex-capable (VORTEX_ALLOWLIST).
                        # Name normalization: DB stores display names; normalize to snake_case.
                        for v_agent_id, v_build in builds.items():
                            v_agent_name = _agent_key(v_build.agent_name)
                            if v_agent_name in VORTEX_ALLOWLIST:
                                # Resolve vortex applier stats
                                v_modifiers = list(v_build.modifiers)
                                for o_id, o_build in builds.items():
                                    if o_id != v_agent_id:
                                        v_modifiers.extend(
                                            [
                                                m
                                                for m in o_build.modifiers
                                                if m.target in (ModifierTarget.TEAM, "team")
                                            ]
                                        )
                                v_build_snap = replace(v_build, modifiers=v_modifiers)
                                v_ctx = _resolve_and_calc(
                                    v_build_snap, _v_conditions, AttackScope.ALL
                                )

                                v_res = _get_enemy_stat(enemy, f"{_vortex_elem}_res", 0)
                                vortex_dmg_bonus = v_ctx.buffs.combat_bonuses.get(
                                    "vortex_dmg_bonus", 0
                                )
                                vortex_res = calculate_vortex_damage(
                                    vortex_kind=vortex_kind,
                                    atk=v_ctx.stats.atk,
                                    anomaly_proficiency=v_ctx.stats.anomaly_proficiency,
                                    attacker_level=v_build.agent_level,
                                    dmg_bonuses=v_ctx.dmg_bonuses,
                                    anomaly_dmg_bonus=v_ctx.buffs.anomaly_dmg_bonus,
                                    vortex_dmg_bonus=vortex_dmg_bonus,
                                    enemy_base_def=enemy.defense,
                                    enemy_level=enemy.level,
                                    pen_ratio=v_ctx.stats.pen_ratio,
                                    pen_flat=v_ctx.stats.pen_flat,
                                    def_ignore=v_ctx.buffs.def_ignore,
                                    enemy_res=v_res,
                                    res_reduction=v_ctx.buffs.res_reduction,
                                    res_ignore=v_ctx.buffs.res_ignore,
                                    vulnerability_bonuses=v_ctx.vuln_bonuses,
                                    is_stunned=is_enemy_stunned,
                                    stun_dmg_mult=(
                                        10000
                                        + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000)
                                        + v_ctx.buffs.stun_dmg_mult_bonus
                                    ),
                                    remaining_duration=duration,
                                    stun_area_override=v_ctx.buffs.stun_area_override,
                                    refringe_mult=_old_refringe_mult,
                                )

                                vortex_attr = build_step_attribution(
                                    v_build_snap, v_ctx.stats, v_ctx.disc, v_ctx.buffs
                                )
                                vortex_detail = {
                                    "multiplier": 0,
                                    "base_dmg": vortex_res.base_dmg,
                                    "effective_atk": v_ctx.stats.atk,
                                    "anomaly_proficiency_mult": vortex_res.anomaly_prof_mult,
                                    "anomaly_level_mult": vortex_res.level_mult,
                                    "anomaly_dmg_bonus_mult": (
                                        vortex_res.anomaly_boost_mult
                                        * vortex_res.vortex_boost_mult
                                        // 10000
                                    ),
                                    "crit_mult": 0,
                                    "boost_mult": vortex_res.boost_mult,
                                    "def_mult": vortex_res.def_mult,
                                    "res_mult": vortex_res.res_mult,
                                    "vulnerability_mult": vortex_res.vulnerability_mult,
                                    "stun_mult": vortex_res.stun_mult,
                                    "level_factor": vortex_res.level_factor_val,
                                    "effective_enemy_def": vortex_res.effective_enemy_def,
                                    "stun_base_mult": vortex_res.stun_base_mult,
                                    "is_anomaly": True,
                                    "attribution": _serialize_attribution(vortex_attr),
                                    "zone_formulas": _serialize_zone_formulas(vortex_attr),
                                    "vortex_kind": vortex_kind,
                                    "vortex_mv_bp": vortex_res.base_dmg * 10000 // v_ctx.stats.atk,
                                    # Task 35: as for `disorder` above — inherited from the
                                    # overridden aura, and independent of `vortex_mv_bp`
                                    # because RefringeArea is applied after `base_dmg`
                                    # (damage_calculator.py:899).
                                    "refringe_mult": _old_refringe_mult,
                                    "cyclone_kind": _cyclone_kind,
                                    "windbite_before": _wb_before,
                                    "windbite_after": windbite,
                                }

                                events.append(
                                    TimelineEvent(
                                        t=t_hit,
                                        kind="vortex",
                                        agent_id=v_agent_id,
                                        element=_vortex_elem,
                                        damage=vortex_res.total,
                                        aura_type=_vortex_elem,
                                        applier_agent_id=v_agent_id,
                                        detail=vortex_detail,
                                    )
                                )

                                totals["vortex"] += vortex_res.total
                                totals["total"] += vortex_res.total
                                per_agent_attribution[v_agent_id] += vortex_res.total

        # Evaluate standard hits damage
        num_attacks = len(step.attacks)
        for idx, attack in enumerate(step.attacks):
            # D-CH5: a row gated on game state that does not hold contributes nothing.
            # Skipped at its OWN index rather than pre-filtered out of `step.attacks`,
            # because `attack_scales` / `attack_offsets` index alongside that list — a
            # pre-filter would hand every later row the wrong scale, and still return a
            # plausible number.
            if not _row_is_live(attack, is_stunned=is_enemy_stunned):
                continue
            attack_element = attack.element or build.agent_element
            # P-F1 (hardening Task 17): Attribute Flux dual-tagging. A Lumiflux
            # hit is BOTH Lumiflux and its fluxed attribute (DESIGN §5.2), and
            # the fluxed half is what picks the DMG% bucket and the enemy RES
            # row. Before this, the API resolved and echoed `fluxed_element` as
            # "the element actually used" while no caller passed it into the
            # damage chain: her hits ran as pure Lumiflux, so fluxed-element
            # DMG% contributed nothing and the enemy's RES for that element was
            # replaced by a neutral 0 (understating her against a weak enemy,
            # overstating her against a resistant one).
            #
            # Only the Lumiflux tag is substituted. An explicitly-elemented
            # attack keeps its own element, and `build.agent_element` is never
            # touched, so every identity check still sees "lumiflux".
            _flux = fluxed_elements.get(acting_agent_id)
            _dmg_element = (
                _flux if (_flux and attack_element == LUMIFLUX_ELEMENT) else attack_element
            )
            elem_res = _get_enemy_stat(enemy, f"{_dmg_element}_res", 0)
            enemy_snap = EnemySnapshot(
                level=enemy.level,
                base_def=enemy.defense,
                element_res=elem_res,
                stun_dmg_mult=10000 + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000),
            )
            # Pick the build's per-skill level for the attack's skill_key
            levels_str = getattr(acting_build_snap, "skill_levels", "12,12,12,12,12")
            levels_str = levels_str or "12,12,12,12,12"
            levels = [int(x) for x in levels_str.split(",")]
            skill_key_to_index = {
                "Basic": 0,
                "Dodge": 1,
                "Assist": 1,
                "Special": 2,
                "EXSpecial": 2,
                "Chain": 3,
                "Ultimate": 3,
                "Core": 4,
            }
            skill_key = getattr(attack, "skill_key", "Basic")
            skill_idx = skill_key_to_index.get(skill_key, 0)
            skill_level = levels[skill_idx] if skill_idx < len(levels) else 12

            # Scale multiplier by skill level
            growth = getattr(attack, "damage_growth", 0) or 0
            base = getattr(attack, "damage_base", 0) or 0
            multiplier = base + growth * (skill_level - 1)

            # Channel tick fraction (Task 10c). A channel's tick row appears in `attacks`
            # once per tick, so it must be scaled down or the hold multiplies its damage by
            # the tick count. The combo path applies the same factor when it builds its
            # ComboSteps, off the same `build_channel_plan` — this is that plan's other half.
            _scales = getattr(step, "attack_scales", None)
            if _scales is not None and idx < len(_scales):
                multiplier = round(multiplier * _scales[idx])

            # Re-tag: if this agent's spec re-tags the hit's scope as Aftershock,
            # inject AFTERSHOCK_ACTIVE so Aftershock DMG% bonuses apply.
            scope_str = scope.value if hasattr(scope, "value") else scope
            _acting_spec = aftershock_specs.get(acting_agent_id)
            _retag_scopes = _acting_spec.retag_as_aftershock if _acting_spec is not None else []
            _is_retagged = scope_str in _retag_scopes
            _hit_conditions = active_conditions
            if _is_retagged:
                _hit_conditions = ActiveConditions(
                    active=active_conditions.active | {Condition.AFTERSHOCK_ACTIVE},
                    stack_counts=dict(active_conditions.stack_counts),
                )

            # Space out the standard hits over the duration of the move
            t_hit_event = (
                t_start + (idx + 1) * (duration_s / num_attacks) if num_attacks > 0 else t_start
            )

            # F-11/F-23a: Frostbite (+10% Crit DMG taken for 10s/20s post-Shatter)
            # feeds straight into the crit-DMG input via a per-hit build override —
            # no calc-chain change needed.
            _hit_build_snap = acting_build_snap
            if t_hit_event < frostbite_until:
                _hit_build_snap = replace(
                    acting_build_snap,
                    agent_crit_dmg=acting_build_snap.agent_crit_dmg + FROSTBITE_CRIT_DMG_BONUS,
                )

            # F-11/F-23b: Windswept Direct-DMG (+10% Direct DMG Bonus) on wind
            # hits landed within the Windswept window — a separate
            # multiplicative zone from generic DMG% (does not combine with
            # dmg_bonuses), and only ever passed into the standard-damage
            # path, never calculate_anomaly_damage.
            _direct_dmg_bonus = (
                WINDSWEPT_DIRECT_DMG_BONUS
                if attack_element == "wind" and t_hit_event < windswept_until
                else 0
            )

            damage_res = calculate_build_damage(
                build=_hit_build_snap,
                enemy=enemy_snap,
                multiplier=multiplier,
                conditions=_hit_conditions,
                attack_scope=scope,
                crit_mode=CritMode.EXPECTED,
                is_stunned=is_enemy_stunned,
                stun_dmg_mult=enemy_snap.stun_dmg_mult,
                with_attribution=True,
                direct_dmg_bonus=_direct_dmg_bonus,
                # None when unfluxed -- byte-identical to the previous call.
                element=(_dmg_element if _dmg_element != attack_element else None),
            )

            hit_detail = {
                "attack_id": str(getattr(attack, "id", None) or "hit"),
                "attack_name": attack.name,
                "multiplier": multiplier,
                "scope": scope.value if hasattr(scope, "value") else scope,
                "base_dmg": damage_res.damage.base_dmg,
                "effective_atk": damage_res.damage.effective_atk,
                # #160 A4: distinguishes an ATK-scaled instance from a Sheer one,
                # where `effective_atk` holds SheerForce instead. A squad-ATK
                # credit must not be emitted for Sheer damage -- the grant never
                # touched it, so crediting it would scale an unrelated stat.
                "is_sheer": damage_res.damage.is_sheer,
                "crit_mult": damage_res.damage.crit_mult,
                "boost_mult": damage_res.damage.boost_mult,
                "def_mult": damage_res.damage.def_mult,
                "res_mult": damage_res.damage.res_mult,
                "vulnerability_mult": damage_res.damage.vulnerability_mult,
                "stun_mult": damage_res.damage.stun_mult,
                "level_factor": damage_res.damage.level_factor_val,
                "effective_enemy_def": damage_res.damage.effective_enemy_def,
                "stun_base_mult": damage_res.damage.stun_base_mult,
                "direct_mult": damage_res.damage.direct_mult,
                "is_anomaly": False,
                "on_field": True,
                "attribution": _serialize_attribution(damage_res.attribution),
                "zone_formulas": _serialize_zone_formulas(damage_res.attribution),
            }
            if getattr(damage_res.damage, "is_sheer", False):
                hit_detail["sheer_force"] = damage_res.damage.effective_atk

            events.append(
                TimelineEvent(
                    t=t_hit_event,
                    kind="hit",
                    agent_id=acting_agent_id,
                    element=attack.element,
                    damage=damage_res.damage.total,
                    aura_type=None,
                    applier_agent_id=acting_agent_id,
                    detail=hit_detail,
                    attribution=damage_res.attribution,
                )
            )
            totals["standard"] += damage_res.damage.total
            totals["total"] += damage_res.damage.total
            per_agent_attribution[acting_agent_id] += damage_res.damage.total
            # Re-tag: Chain/Ult counted in aftershock bucket; total already incremented above.
            if _is_retagged:
                totals["aftershock"] += damage_res.damage.total

            # Aftershock emit hook: auto-trigger off-field procs reacting to this hit.
            hit_scope_val = hit_detail.get("scope", "")
            _as_events = _resolve_aftershock(
                active_agent=active_agent,
                builds=builds,
                aftershock_specs=aftershock_specs,
                hit_kind="hit",
                hit_scope=hit_scope_val,
                t_hit=t_hit_event,
                enemy=enemy,
                resources=resources,
                aftershock_cd_until=aftershock_cd_until,
                aftershock_window=aftershock_window,
                energy=energy,
                is_enemy_stunned=is_enemy_stunned,
                agent_states=agent_states,
                aftershock_chain=aftershock_chain,
            )
            for _as_ev in _as_events:
                events.append(_as_ev)
                totals["aftershock"] += _as_ev.damage
                totals["total"] += _as_ev.damage
                per_agent_attribution[_as_ev.agent_id] += _as_ev.damage

            # Aftershock emit hook: on-field self procs (on_field_self=True specs).
            _onfield_as_events = _resolve_onfield_aftershock(
                active_agent=active_agent,
                builds=builds,
                aftershock_specs=aftershock_specs,
                hit_kind="hit",
                hit_scope=hit_scope_val,
                t_hit=t_hit_event,
                enemy=enemy,
                resources=resources,
                aftershock_cd_until=aftershock_cd_until,
                aftershock_window=aftershock_window,
                energy=energy,
                is_enemy_stunned=is_enemy_stunned,
            )
            for _ev in _onfield_as_events:
                events.append(_ev)
                totals["aftershock"] += _ev.damage
                totals["total"] += _ev.damage
                per_agent_attribution[_ev.agent_id] += _ev.damage

            # WT cascade: White Thunder consume + Smite/Boundary (S0 Anby pattern).
            _wt_events = _resolve_wt_cascade(
                active_agent=active_agent,
                builds=builds,
                aftershock_specs=aftershock_specs,
                hit_scope=hit_scope_val,
                t_hit=t_hit_event,
                enemy=enemy,
                is_enemy_stunned=is_enemy_stunned,
                white_thunder=white_thunder,
                wt_tally=wt_tally,
                wt_vortex_tally=wt_vortex_tally,
            )
            for _ev in _wt_events:
                events.append(_ev)
                totals["aftershock"] += _ev.damage
                totals["total"] += _ev.damage
                per_agent_attribution[_ev.agent_id] += _ev.damage

        # Kit `formulas[]` damage instances (Ben's M2, Miyabi's frostburn break,
        # Alice's/Jane's AP-scaled M6, …). One per step whose scope matches — the
        # same granularity ZO gives them, where each is a single instance the user
        # adds to a rotation. Inert entries (an M6 formula on an M0 build) never
        # reach here: resolve_kit_formulas drops them at snapshot-build time.
        for _kf in _kit_formulas:
            if _kf.quantity != "standard_dmg" or _kf.scope != scope:
                continue
            _kf_ev = _emit_kit_formula_event(
                emitter_id=acting_agent_id,
                emitter_snap=acting_build_snap,
                formula=_kf,
                enemy=enemy,
                conditions=active_conditions,
                is_enemy_stunned=is_enemy_stunned,
                t_hit=t_start + duration_s,
            )
            events.append(_kf_ev)
            totals["kit_formula"] += _kf_ev.damage
            totals["total"] += _kf_ev.damage
            per_agent_attribution[acting_agent_id] += _kf_ev.damage

        # Check Polarity Disorder at the final hit of the move if marked with
        # polarity_disorder — and, when the trigger is a Mindscape effect rather than base
        # kit, only at or above that Mindscape. Alice's Ultimate: Starfall Finale is the
        # case: its Polarity Assault comes from M2 "Sage at the Sword's Tip", and the base
        # skill text does not mention it, so an M0 Alice was credited an M2 effect.
        # Mirrors `abloom_requires_mindscape` (:565, :3244).
        has_polarity = move_spec and getattr(move_spec, "polarity_disorder", False)
        if has_polarity and getattr(build, "mindscape_level", 0) < getattr(
            move_spec, "polarity_requires_mindscape", 0
        ):
            has_polarity = False
        polarity_additional_mv = (
            getattr(move_spec, "polarity_additional_mv", 0) if move_spec else 0
        )
        if has_polarity:
            t_final = t_start + duration_s
            if active_aura and t_final <= active_aura["expires_at"]:
                old_elem = active_aura["element"]
                old_anom = ELEMENT_TO_ANOMALY.get(old_elem, AnomalyType.BURN)
                old_snap = active_aura["applier_snap"]

                # H1: resolve under applier's conditions at application time
                old_ctx = _resolve_and_calc(
                    old_snap, active_aura["applier_conditions"], AttackScope.ALL
                )

                disorder_dmg_bonus = old_ctx.buffs.combat_bonuses.get("disorder_dmg_bonus", 0)
                disorder_dmg_res = _get_enemy_stat(enemy, f"{old_elem}_res", 0)
                # Alice core: +18%/s remaining aura duration (max 180% at full 10s).
                _pdur_rate = old_ctx.buffs.disorder_duration_bonus_rate
                _premaining_s = active_aura["expires_at"] - t_final
                polarity_duration_bonus = int(_premaining_s * _pdur_rate) if _pdur_rate else 0

                # H2b: flat AP-scaled base term (Leifa: 3200%×CurrentAP at T12).
                # Uses Yanagi's *current* AP (ctx), not the snapshotted applier AP (old_ctx).
                _ms = move_spec
                _ap_base = getattr(_ms, "polarity_ap_coeff_base", 0) if _ms else 0
                _ap_growth = getattr(_ms, "polarity_ap_coeff_growth", 0) if _ms else 0
                _lvls_str = getattr(acting_build_snap, "skill_levels", "12,12,12,12,12")
                _lvls_str = _lvls_str or "12,12,12,12,12"
                _lvls = [int(x) for x in _lvls_str.split(",")]
                _ex_lvl = _lvls[2] if len(_lvls) > 2 else 12  # noqa: PLR2004 — EXSpecial idx
                _ap_coeff = _ap_base + _ap_growth * (_ex_lvl - 1)
                _flat_base = (
                    ctx.stats.anomaly_proficiency * _ap_coeff // 10000 if _ap_coeff > 0 else 0
                )

                # Refringe snapshots into the aura at trigger time (DESIGN §7.1).
                # Polarity Disorder inherits it exactly as ordinary Disorder does
                # (the sibling call site above) -- both compute independently from
                # the old aura, so neither picks the multiplier up implicitly.
                # Omitting it here was engine finding E-F4: a Polarity Disorder on
                # a Refringed aura silently dropped the Lumiflux agent's whole
                # contribution, which mattered because Yanagi is the only agent
                # with Polarity Disorder and Yanagi + Remielle is a headline team.
                _polarity_refringe_mult = active_aura.get("refringe_mult", 10000)

                disorder_dmg = calculate_disorder_damage(
                    anomaly_type=old_anom,
                    atk=old_ctx.stats.atk,
                    anomaly_proficiency=old_ctx.stats.anomaly_proficiency,
                    attacker_level=old_snap.agent_level,
                    dmg_bonuses=old_ctx.dmg_bonuses,
                    # Attribute-anomaly DMG% bonuses (e.g. Grace's shock_dmg_bonus) apply to
                    # the triggering anomaly, not to Disorder/Polarity Disorder (Leifa, F-22).
                    anomaly_dmg_bonus=old_ctx.buffs.anomaly_dmg_bonus,
                    disorder_dmg_bonus=disorder_dmg_bonus + polarity_duration_bonus,
                    enemy_base_def=enemy.defense,
                    enemy_level=enemy.level,
                    pen_ratio=old_ctx.stats.pen_ratio,
                    pen_flat=old_ctx.stats.pen_flat,
                    def_ignore=old_ctx.buffs.def_ignore,
                    enemy_res=disorder_dmg_res,
                    res_reduction=old_ctx.buffs.res_reduction,
                    res_ignore=old_ctx.buffs.res_ignore,
                    vulnerability_bonuses=old_ctx.vuln_bonuses,
                    is_stunned=is_enemy_stunned,
                    stun_dmg_mult=(
                        10000
                        + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000)
                        + old_ctx.buffs.stun_dmg_mult_bonus
                    ),
                    remaining_duration=active_aura["expires_at"] - t_final,
                    max_duration=active_aura["max_duration"],
                    stun_area_override=old_ctx.buffs.stun_area_override,
                    additional_mv=polarity_additional_mv,
                    # Polarity: base = ATK×MV×15% + flat_AP_term (Leifa).
                    base_dmg_bonus_pct=-8500,
                    flat_base_dmg=_flat_base,
                    refringe_mult=_polarity_refringe_mult,
                )

                polarity_total = disorder_dmg.total
                polarity_base = disorder_dmg.base_dmg

                disorder_attr = build_step_attribution(
                    old_snap,
                    old_ctx.stats,
                    old_ctx.disc,
                    old_ctx.buffs,
                    is_anomaly=True,
                    damage=disorder_dmg,
                    multiplier=0,  # polarity base isn't a fixed MV% (flat AP term + scaling)
                    enemy_res=disorder_dmg_res,
                )
                disorder_detail = {
                    "multiplier": 0,
                    "base_dmg": polarity_base,
                    "effective_atk": old_ctx.stats.atk,
                    "anomaly_proficiency_mult": disorder_dmg.anomaly_prof_mult,
                    "anomaly_level_mult": disorder_dmg.level_mult,
                    "anomaly_dmg_bonus_mult": (
                        disorder_dmg.anomaly_boost_mult * disorder_dmg.disorder_boost_mult // 10000
                    ),
                    "crit_mult": 0,
                    "boost_mult": disorder_dmg.boost_mult,
                    "def_mult": disorder_dmg.def_mult,
                    "res_mult": disorder_dmg.res_mult,
                    "vulnerability_mult": disorder_dmg.vulnerability_mult,
                    "stun_mult": disorder_dmg.stun_mult,
                    "level_factor": disorder_dmg.level_factor_val,
                    "effective_enemy_def": disorder_dmg.effective_enemy_def,
                    "stun_base_mult": disorder_dmg.stun_base_mult,
                    "is_anomaly": True,
                    "attribution": _serialize_attribution(disorder_attr),
                    "zone_formulas": _serialize_zone_formulas(disorder_attr),
                    "disorder_mv": polarity_base,
                    "disorder_kind": "polarity",
                    "polarity_flat_ap_dmg": disorder_dmg.flat_base_dmg,
                }

                # Polarity leaves the active aura and its ticks intact (Leifa)
                events.append(
                    TimelineEvent(
                        t=t_final,
                        kind="disorder",
                        agent_id=acting_agent_id,
                        element=old_elem,
                        damage=polarity_total,
                        aura_type=old_elem,
                        applier_agent_id=active_aura["applier_id"],
                        detail=disorder_detail,
                    )
                )

                totals["disorder"] += polarity_total
                totals["total"] += polarity_total
                per_agent_attribution[active_aura["applier_id"]] += polarity_total

        # Abloom: fires once per step if flagged and an aura was active at step start
        abloom_mv_by_element = (
            getattr(move_spec, "abloom_mv_by_element", None) if move_spec else None
        )
        _abloom_requires_mc = getattr(move_spec, "abloom_requires_mindscape", 0)
        _build_mc = getattr(build, "mindscape_level", 0)
        # requires_charge_level (Aria's Perfect Pitch, OQ-1 option (a)): the move spec
        # documents that only the final hit of the sequential cycle is a true
        # charge-level release, so only THAT step's abloom may fire. `hits` doubles as
        # the documented cycle length here — a single-tap step's lone attack must carry
        # the last hit_index in the cycle (0-based: hits-1); a bundled/full-chain step
        # already ends on that same row as its last attack. Without this gate, keying
        # the plain DB name fires the abloom on every press of the 5-hit combo instead
        # of once, over-crediting Aria worse than the pre-fix zero.
        _requires_charge_level = getattr(move_spec, "requires_charge_level", 0)
        _is_final_charge_hit = not _requires_charge_level or (
            bool(step.attacks) and step.attacks[-1].hit_index == (move_spec.hits - 1)
        )
        if (
            abloom_mv_by_element
            and pre_step_aura
            and _build_mc >= _abloom_requires_mc
            and _is_final_charge_hit
        ):
            aura_element = pre_step_aura["element"]
            mv_bp = abloom_mv_by_element.get(aura_element, 0)
            _abloom_mv_mult = getattr(move_spec, "abloom_mv_multiplier_bp", 10_000)
            _abloom_mv_mult_mc = getattr(move_spec, "abloom_mv_multiplier_requires_mindscape", 0)
            if _build_mc < _abloom_mv_mult_mc:
                _abloom_mv_mult = 10_000
            mv_bp = mv_bp * _abloom_mv_mult // 10_000
            _stun_mv_bonus = getattr(move_spec, "abloom_stun_mv_bonus", 0)
            if is_enemy_stunned and _stun_mv_bonus:
                mv_bp = mv_bp * (10000 + _stun_mv_bonus) // 10000
            if mv_bp > 0 and pre_step_aura.get("dmg_per_proc", 0) > 0:
                _abloom_stat = getattr(move_spec, "abloom_stat", "anomaly_proficiency")
                abloom_ap = getattr(ctx.stats, _abloom_stat, ctx.stats.anomaly_proficiency)
                abloom_dmg_bonus = (
                    ctx.buffs.combat_bonuses.get("abloom_mv_bonus", 0) + ctx.buffs.abloom_dmg_bonus
                )
                _abloom_ap_scaled = getattr(move_spec, "abloom_ap_scaled", True)
                # Aria M1: Abloom crit (DESIGN_abloom_c8.md §Feature A, OQ-A1).
                # initial_AM = live ctx.stats.anomaly_mastery (matches C5 base-path).
                # +0.5%/AM>100 is Aria-specific; not generalised.
                _abloom_crit_rate = ctx.buffs.combat_bonuses.get("abloom_crit_rate", 0)
                _abloom_crit_dmg = ctx.buffs.combat_bonuses.get("abloom_crit_dmg", 0)
                if _abloom_crit_rate > 0:
                    _initial_am = ctx.stats.anomaly_mastery
                    _abloom_crit_rate = min(
                        10000,
                        _abloom_crit_rate + max(0, _initial_am - 100) * 50,
                    )
                abloom_res = calculate_abloom_damage(
                    abloom_mv_bp=mv_bp,
                    original_anomaly_dmg=pre_step_aura["dmg_per_proc"],
                    ap=abloom_ap,
                    abloom_dmg_bonus=abloom_dmg_bonus,
                    abloom_ap_scaled=_abloom_ap_scaled,
                    crit_rate_bp=_abloom_crit_rate,
                    crit_dmg_bp=_abloom_crit_dmg,
                )
                t_abloom = t_start + duration_s
                events.append(
                    TimelineEvent(
                        t=t_abloom,
                        kind="abloom",
                        agent_id=acting_agent_id,
                        element=aura_element,
                        damage=abloom_res.total,
                        aura_type=aura_element,
                        applier_agent_id=pre_step_aura["applier_id"],
                        detail={
                            "abloom_mv_bp": mv_bp,
                            "original_anomaly_dmg": pre_step_aura["dmg_per_proc"],
                            "ap": abloom_ap,
                            "abloom_boost_mult": abloom_res.abloom_boost_mult,
                            "abloom_crit_mult": abloom_res.crit_mult,
                            "is_anomaly": True,
                        },
                    )
                )
                totals["abloom"] += abloom_res.total
                totals["total"] += abloom_res.total
                per_agent_attribution[acting_agent_id] += abloom_res.total
                # Open the Abloom-trigger buff window (consumed by subsequent steps).
                abloom_trigger_until = max(abloom_trigger_until, t_abloom + _ABLOOM_TRIGGER_BUFF_S)

                # Extra instance (e.g. Promeia M6 fixed-200% second Abloom on EX).
                _extra_mv_bp = getattr(move_spec, "abloom_extra_instance_bp", 0)
                _extra_mc_req = getattr(move_spec, "abloom_extra_instance_requires_mindscape", 0)
                if _extra_mv_bp > 0 and _build_mc >= _extra_mc_req:
                    extra_res = calculate_abloom_damage(
                        abloom_mv_bp=_extra_mv_bp,
                        original_anomaly_dmg=pre_step_aura["dmg_per_proc"],
                        ap=abloom_ap,
                        abloom_dmg_bonus=abloom_dmg_bonus,
                        abloom_ap_scaled=False,
                    )
                    events.append(
                        TimelineEvent(
                            t=t_abloom,
                            kind="abloom",
                            agent_id=acting_agent_id,
                            element=aura_element,
                            damage=extra_res.total,
                            aura_type=aura_element,
                            applier_agent_id=pre_step_aura["applier_id"],
                            detail={
                                "abloom_mv_bp": _extra_mv_bp,
                                "original_anomaly_dmg": pre_step_aura["dmg_per_proc"],
                                "ap": abloom_ap,
                                "abloom_boost_mult": extra_res.abloom_boost_mult,
                                "abloom_crit_mult": extra_res.crit_mult,
                                "is_anomaly": True,
                            },
                        )
                    )
                    totals["abloom"] += extra_res.total
                    totals["total"] += extra_res.total
                    per_agent_attribution[acting_agent_id] += extra_res.total

        # Lumiflux Buildup Points (P2, DESIGN §7.1, Task 31): a move that
        # declares `lumiflux_points` applies them to the per-enemy pool once the
        # skill resolves. Generic move-spec field read via getattr, and gated on
        # the acting agent being a registered Lumiflux agent -- same shape and
        # same reason as the Luminize gate below: a `lumiflux_points` value on
        # some other agent's move must not be able to open a pool.
        #
        # Once per enemy, not once per animation hit. The DB text is "after the
        # skill ends, apply 2 Lumiflux Buildup to all enemies hit" -- the count
        # is per enemy, and this engine simulates a single enemy, so the whole
        # move contributes one application. (Every point-granting move authored
        # today is `hits: 1`, so this is indistinguishable from a per-hit
        # placement right now; it stops a future multi-hit applier from
        # silently multiplying its own authored count.) `t` has already been
        # advanced past this step's duration, so the application lands at the
        # end of the skill, which is what the DB text says and what makes the
        # points visible to the *next* step's Prismatic check rather than this
        # one's.
        if getattr(move_spec, "lumiflux_points", 0) and acting_agent_id in lumiflux_specs:
            lumiflux_state = _record_lumiflux_points(
                lumiflux_state,
                lumiflux_specs[acting_agent_id],
                move_spec.lumiflux_points,
                agent_id=acting_agent_id,
                t=t,
                events=events,
            )

        # Luminize (Remielle, DESIGN §7.2, Task 14): fires on Assist/Ultimate/
        # Hold Basic/Enhanced Hold Basic -- generic move-spec flags
        # (`triggers_luminize`/`luminize_mult_bp`), not a Remielle-specific
        # branch, so a second Lumiflux agent's kit JSON gets this for free.
        # Gated on the acting agent actually being a registered Lumiflux
        # agent with a non-empty Voidflare store -- neither exists without
        # Task 11/12 having fired for her first. One instance PER stored
        # Voidflare (DESIGN §2 OQ-2), each against its own stored element's
        # RES (§9.1 test 9). Deliberately does not touch `active_aura`,
        # `gauges`, or anything else Disorder/Abloom/Vortex read from --
        # structurally incapable of triggering any of them (§7.2, §9.1
        # test 5), unlike a real anomaly trigger.
        if getattr(move_spec, "triggers_luminize", False) and acting_agent_id in lumiflux_specs:
            _luminize_spec = lumiflux_specs[acting_agent_id]
            _luminize_mult_bp = getattr(move_spec, "luminize_mult_bp", 0)
            _remielle_anomaly_dmg_bonus = ctx.buffs.anomaly_dmg_bonus
            for _voidflare in voidflare_stores.get(acting_agent_id, ()):
                _luminize_enemy_res = _get_enemy_stat(enemy, f"{_voidflare.element}_res", 0)
                _luminize_res = calculate_luminize_damage(
                    voidflare_atk=_voidflare.atk,
                    voidflare_dmg_bonus_bp=_voidflare.dmg_bonus_bp,
                    voidflare_pen_ratio_bp=_voidflare.pen_ratio_bp,
                    voidflare_pen_flat=_voidflare.pen_flat,
                    voidflare_anomaly_proficiency=_voidflare.anomaly_proficiency,
                    luminize_mult_bp=_luminize_mult_bp,
                    attacker_level=build.agent_level,
                    remielle_anomaly_proficiency=ctx.stats.anomaly_proficiency,
                    ap_bonus_per_point_bp=_luminize_spec.luminize_ap_bonus_bp,
                    remielle_anomaly_dmg_bonus=_remielle_anomaly_dmg_bonus,
                    enemy_base_def=enemy.defense,
                    enemy_level=enemy.level,
                    def_ignore=ctx.buffs.def_ignore,
                    enemy_res=_luminize_enemy_res,
                    res_reduction=ctx.buffs.res_reduction,
                    res_ignore=ctx.buffs.res_ignore,
                    luminize_res_ignore=ctx.buffs.luminize_res_ignore,
                    vulnerability_bonuses=ctx.vuln_bonuses,
                    is_stunned=is_enemy_stunned,
                    stun_dmg_mult=(
                        10000
                        + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000)
                        + ctx.buffs.stun_dmg_mult_bonus
                    ),
                )
                events.append(
                    TimelineEvent(
                        t=t,
                        kind="luminize",
                        agent_id=acting_agent_id,
                        element=_voidflare.element,
                        damage=_luminize_res.total,
                        aura_type=None,
                        applier_agent_id=acting_agent_id,
                        detail={
                            "luminize_mult_bp": _luminize_mult_bp,
                            "voidflare_element": _voidflare.element,
                            "voidflare_stored_at": _voidflare.stored_at,
                            "boost_mult": _luminize_res.boost_mult,
                            "def_mult": _luminize_res.def_mult,
                            "res_mult": _luminize_res.res_mult,
                            "anomaly_prof_mult": _luminize_res.anomaly_prof_mult,
                            "anomaly_dmg_bonus_mult": _luminize_res.anomaly_boost_mult,
                            "is_anomaly": True,
                            # --- Task 36 (E-8): everything the optimizer's
                            # event→step mapping needs to rebuild this instance
                            # against a candidate disc set. The mapping sees
                            # events, never the Voidflare store, so provenance
                            # and the Remielle-side constants have to ride here.
                            "voidflare_captured_from": _voidflare.captured_from,
                            "luminize_effective_mult_bp": _luminize_res.effective_mult_bp,
                            # P-F2 (hardening Task 15): the two inputs needed to
                            # RE-fold the multiplier against a candidate AP when
                            # the Lumiflux agent is herself the optimized DPS.
                            # `luminize_effective_mult_bp` above is that fold
                            # evaluated at her disc-STRIPPED AP, so on its own it
                            # freezes her own discs out of her own damage.
                            "luminize_ap_bonus_bp": _luminize_spec.luminize_ap_bonus_bp,
                            "luminize_owner_agent_id": acting_agent_id,
                            # Remielle's, not the captured teammate's -- DEFArea
                            # subtracts it from the *scored* build's PEN, so it
                            # cannot fold into the constant factor below.
                            "luminize_def_ignore": ctx.buffs.def_ignore,
                            # RES x Vuln x Stun x Level x AnomalyBoost: the whole
                            # candidate-invariant half of the chain, as one scalar.
                            "luminize_constant_factor": (
                                (_luminize_res.res_mult / 10000)
                                * (_luminize_res.vulnerability_mult / 10000)
                                * (_luminize_res.stun_mult / 10000)
                                * (_luminize_res.level_mult / 10000)
                                * (_luminize_res.anomaly_boost_mult / 10000)
                            ),
                        },
                    )
                )
                totals["luminize"] += _luminize_res.total
                totals["total"] += _luminize_res.total
                per_agent_attribution[acting_agent_id] += _luminize_res.total

        # E-F3 (b): the two named Hold Basics clear the store AFTER their
        # Luminize resolves. Core text: "All stored Voidflares are cleared
        # when Remielle enters the Phase Flow state or after using Basic
        # Attack: Rainbow's End or Basic Attack: Fleeting Grace." Note the
        # clear is scoped to those two moves -- Assist and Ultimate also
        # trigger Luminize but do NOT clear -- so this is its own move-spec
        # flag rather than being folded into `triggers_luminize`. Without it,
        # back-to-back Luminize triggers re-fired the same Voidflares every
        # time and the store only ever grew, overcounting Luminize badly.
        if getattr(move_spec, "clears_voidflare_store", False) and (
            acting_agent_id in lumiflux_specs
        ):
            voidflare_stores[acting_agent_id] = clear_voidflare_store(
                lumiflux_specs[acting_agent_id].voidflare_cap
            )

        # Snapshot energy state for all agents at the end of this step.
        for _eid, _evalue in energy.items():
            energy_timeline.append((t, _eid, _evalue))

    # E-F1: ticks scheduled past the end of the last step still happened --
    # a Phase Flow window can outlive the authored rotation. Nothing in-run
    # can consume these, but `final_lumiflux_points` and the timeline must
    # still reflect them, exactly as the old post-pass did.
    _drain_tick_points(float("inf"))

    # F-19: resolve on-hit-gated Shock/Corruption ticks from the recorded hit
    # timeline. Each gated aura's per-proc damage, cap, and window were fixed at
    # trigger time; convert real hit timestamps within that window into ticks,
    # bucketed by the anomaly's internal cooldown so at most one tick fires per
    # bucket, capped at the anomaly's proc count.
    hit_times.sort()
    for _gated in gated_aura_instances:
        _cd = GATED_ANOMALY_CD_S.get(_gated["anomaly_type"], 1.0)
        _window_hits = [
            _ht for _ht in hit_times if _gated["applied_at"] <= _ht <= _gated["end_at"]
        ]
        _bucket_first_hit: dict[int, float] = {}
        for _ht in _window_hits:
            _bucket = int((_ht - _gated["applied_at"]) // _cd)
            if _bucket not in _bucket_first_hit:
                _bucket_first_hit[_bucket] = _ht
        _tick_times = sorted(_bucket_first_hit.values())[: _gated["procs"]]
        _gated_shares = _gated.get("per_agent_shares") or {_gated["applier_id"]: 1.0}
        for _tt in _tick_times:
            _tick_dmg = _gated["dmg_per_proc"]
            _tick_split = _split_amount_by_share(_tick_dmg, _gated_shares)
            events.append(
                TimelineEvent(
                    t=_tt,
                    kind="anomaly_tick",
                    agent_id=_gated["applier_id"],
                    element=_gated["element"],
                    damage=_tick_dmg,
                    aura_type=_gated["element"],
                    applier_agent_id=_gated["applier_id"],
                    detail={**_gated["detail"], "per_agent_attribution": _tick_split},
                )
            )
            totals["anomaly"] += _tick_dmg
            totals["total"] += _tick_dmg
            for _aid, _dmg in _tick_split.items():
                per_agent_attribution[_aid] += _dmg

    # Phase Flow (Remielle, P4, DESIGN §7.3, Task 15): deterministic
    # expected-value ticks, one synthetic Special Attack every
    # `spec.phase_flow_tick_s` per active window. A pure post-pass -- ticks
    # depend only on each window's own (start, end) and the spec's cadence,
    # never on anything the per-step loop tracked, so it needs no
    # interleaving with `t`/`active_aura`/etc. and can never perturb any
    # existing caller (empty `phase_flow_windows` is a no-op, unconditionally).
    for _pf_agent_id, _pf_windows in phase_flow_windows.items():
        _pf_build = builds.get(_pf_agent_id)
        _pf_spec = lumiflux_specs.get(_pf_agent_id)
        if _pf_build is None or _pf_spec is None:
            continue
        _ev_mv_bp = phase_flow_expected_value(_pf_spec.flight_attack_mv_bp)
        _ev_daze_bp = phase_flow_expected_value(_pf_spec.flight_attack_daze_bp)
        _ev_points = phase_flow_expected_value(_pf_spec.flight_attack_points)
        # Modifier merge uses the off-field rule regardless of the
        # energy-regen/Feathered-Fate classification split (PhaseFlowState,
        # DESIGN §7.3's table) -- same merge `_resolve_aftershock` already
        # uses for every other off-field proc.
        # E-F5(c): ticks used to resolve under a bare {ALWAYS}, so every
        # PHASE_FLOW_ACTIVE-gated buff was invisible to the very damage that
        # only exists because Phase Flow is active -- including her own
        # modifier [4] (+18% squad DMG) and hardening Task 5's M1 team
        # Attribute-Anomaly-DMG row. By construction a tick happens inside a
        # Phase Flow window, so the condition is unconditionally true here;
        # her equipper conditions come along for the same reason as E-F5(a).
        _pf_conditions = _with_equipper_conditions_for(
            ActiveConditions(active={Condition.ALWAYS, Condition.PHASE_FLOW_ACTIVE}),
            _pf_build,
        )
        _pf_offfield_snap = replace(
            _pf_build, modifiers=_resolve_offfield_modifiers(_pf_agent_id, builds)
        )
        _pf_enemy_snap = EnemySnapshot(
            level=enemy.level,
            base_def=enemy.defense,
            element_res=_get_enemy_stat(enemy, f"{_pf_build.agent_element}_res", 0),
            stun_dmg_mult=10000 + _get_enemy_stat(enemy, "stun_dmg_taken_ratio", 5000),
        )
        for _pf_start, _pf_end in _pf_windows:
            _pf_k = 1
            while True:
                _t_tick = _pf_start + _pf_k * _pf_spec.phase_flow_tick_s
                if _t_tick >= _pf_end:
                    break
                _pf_dmg = calculate_build_damage(
                    build=_pf_offfield_snap,
                    enemy=_pf_enemy_snap,
                    multiplier=_ev_mv_bp,
                    conditions=_pf_conditions,
                    attack_scope=AttackScope.SPECIAL,
                    crit_mode=CritMode.EXPECTED,
                    is_stunned=False,
                    stun_dmg_mult=_pf_enemy_snap.stun_dmg_mult,
                    with_attribution=True,
                )
                events.append(
                    TimelineEvent(
                        t=_t_tick,
                        kind="phase_flow_tick",
                        agent_id=_pf_agent_id,
                        element=_pf_build.agent_element,
                        damage=_pf_dmg.damage.total,
                        aura_type=None,
                        applier_agent_id=_pf_agent_id,
                        detail={
                            "ev_mv_bp": _ev_mv_bp,
                            "ev_daze_bp": _ev_daze_bp,
                            "ev_points": _ev_points,
                            "on_field": False,
                            "attribution": _serialize_attribution(_pf_dmg.attribution),
                            "zone_formulas": _serialize_zone_formulas(_pf_dmg.attribution),
                        },
                    )
                )
                totals["phase_flow"] += _pf_dmg.damage.total
                totals["total"] += _pf_dmg.damage.total
                per_agent_attribution[_pf_agent_id] += _pf_dmg.damage.total

                # NOTE (E-F1): the tick's point state is NOT applied here any
                # more -- it is drained inside the step loop at this same
                # timestamp, so an in-run Refringe or Prismatic gate can
                # consume it. Only the tick's damage is a post-pass quantity.
                _pf_k += 1

    # Sort events by time stamp primarily, and logical priority secondarily
    def sort_key(e: TimelineEvent) -> tuple[float, int]:
        priorities = {
            "stun_trigger": 0,
            "stun_end": 0,
            "hit": 1,
            "abloom": 2,  # Abloom fires alongside the hit
            "luminize": 2,  # Luminize also fires alongside the (Remielle) hit
            "anomaly": 3,  # Apply new anomaly first
            "disorder": 4,  # Then trigger disorder override
            "vortex": 5,  # Then trigger vortex
            "refresh": 6,  # Then refresh duration
            "anomaly_tick": 7,  # Then apply tick damage
            "phase_flow_tick": 7,  # Same tier as anomaly_tick -- both are periodic procs
            "expire": 8,  # Then expire
        }
        return (e.t, priorities.get(e.kind, 9))

    events.sort(key=sort_key)
    return SimulationResult(
        events=events,
        totals=totals,
        per_agent_attribution=per_agent_attribution,
        warnings=warnings,
        final_energy=energy,
        energy_timeline=energy_timeline,
        field_timeline=field_timeline,
        final_lumiflux_points=lumiflux_state.points if lumiflux_state is not None else 0,
        final_voidflares={aid: list(store) for aid, store in voidflare_stores.items()},
    )


def simulate_single_hit(
    build: BuildSnapshot,
    attacks: list[Any],
    enemy: EnemyProfile,
    *,
    conditions: list[str] | None = None,
    move_name: str = "degenerate_hit",
    fluxed_element: str | None = None,
) -> SimulationResult:
    """Degenerate single-step mode: one agent, one step, no buildup, no anomaly.

    This entry point enforces that no anomaly fires (attacks must have zero
    buildup). It is the mechanism Phase 4 will route standard-damage traffic
    through once the single-engine seam is in place.

    Do NOT route production traffic here yet — the stateless engine remains
    authoritative until Phase 4 completes the swap.

    ``fluxed_element`` is the resolved Attribute Flux for this build, if any
    (P-F1, hardening Task 17). ``/damage/build`` echoes the caller's
    ``fluxed_element`` as "the element actually used"; passing it here is what
    makes that description true, by routing it to the dual-tag choke point so
    the DMG%-bucket and the enemy RES row both follow it. ``None`` — the
    unfluxed case and every non-Lumiflux agent — is byte-identical to before.
    """
    for atk in attacks:
        buildup = getattr(atk, "anomaly_buildup", 0) or 0
        if buildup != 0:
            raise ValueError(
                f"simulate_single_hit requires zero anomaly_buildup on every attack; "
                f"'{getattr(atk, 'name', atk)}' has buildup={buildup}"
            )

    step = SimulatedAttackStep(
        agent_id="_solo",
        move_name=move_name,
        attacks=attacks,
        conditions=conditions or [],
    )
    return simulate(
        builds={"_solo": build},
        steps=[step],
        enemy=enemy,
        moves_db={},
        fluxed_elements=({"_solo": fluxed_element} if fluxed_element else None),
    )


class _EnemyWithStun:
    """Thin proxy that overlays is_stunned on any enemy object (DB model or frozen snapshot).

    Also handles EnemySnapshot (frozen dataclass with base_def/element_res/stun_dmg_mult)
    by translating field names to the DB model convention simulate() expects:
      base_def → defense
      element_res → {element}_res (returned for any *_res lookup)
      stun_dmg_mult → stun_dmg_taken_ratio = stun_dmg_mult - 10000
    """

    __slots__ = ("_inner", "_is_snapshot", "is_stunned")

    def __init__(self, inner: Any, is_stunned: bool) -> None:
        object.__setattr__(self, "_inner", inner)
        # Detect EnemySnapshot by the presence of base_def (not present on DB models).
        object.__setattr__(self, "_is_snapshot", hasattr(inner, "base_def"))
        object.__setattr__(self, "is_stunned", is_stunned)

    def __getattr__(self, name: str) -> Any:
        inner = object.__getattribute__(self, "_inner")
        is_snapshot = object.__getattribute__(self, "_is_snapshot")
        if is_snapshot:
            if name == "defense":
                return inner.base_def
            if name == "stun_dmg_taken_ratio":
                return max(0, (getattr(inner, "stun_dmg_mult", 15000) or 15000) - 10000)
            if name.endswith("_res"):
                # For element-specific lookups: check res_map first, else return element_res.
                element = name[: -len("_res")]
                res_map = getattr(inner, "res_map", None)
                if res_map:
                    return res_map.get(element, getattr(inner, "element_res", 0))
                return getattr(inner, "element_res", 0)
        return getattr(inner, name, 0)


def simulate_combo_steps(
    build: BuildSnapshot,
    combo_steps: list[Any],  # list[ComboStep | StunTriggerStep | StunEndStep]
    enemy: Any,
    *,
    member_snapshots: dict[str, BuildSnapshot] | None = None,
    base_conditions: list[str] | None = None,
    agent_id: str = "_dps",
    is_stunned: bool = False,
    fluxed_overrides: dict[str, str] | None = None,
) -> SimulationResult:
    """Route pre-resolved combo steps through simulate().

    Converts ComboStep value objects (with pre-resolved scope + multiplier) into
    SimulatedAttackStep entries with synthetic attacks and a matching moves_db entry
    that preserves the per-step scope and element.

    When ``member_snapshots`` is provided (Phase 5B), each step's ``agent_id``
    attribute is used to select the owning member's snapshot.  The default path
    (``member_snapshots=None``) tags every step with the constant ``agent_id``
    and is bit-for-bit identical to prior behaviour.

    Known limitations (same class as simulate_single_hit):
    - Always uses CritMode.EXPECTED.
    - stack_counts are taken from the build snapshot passed in; callers that merge
      request overrides into the snapshot (e.g. combos.py) ensure consistency.
    - stun_dmg_mult overrides are not forwarded; enemy model's default is used.

    Anomalies are **derived**, not declared. Each ``ComboStep`` carries its own
    ``anomaly_buildup`` and this function accrues it, so the simulator raises
    real ``anomaly`` / ``anomaly_tick`` events. That is only correct while the
    input list declares no anomalies of its own — see the guard below.

    Raises:
        ValueError: if ``combo_steps`` contains a pre-materialised ``AnomalyStep``.
    """
    # Double-count guard (mandatory). Deriving anomalies from buildup is only
    # sound while nothing upstream has already materialised them: a list holding
    # both would count each anomaly twice, silently and roughly doubling the
    # anomaly half of the total.
    #
    # This holds today by construction — `resolve_combo_sequence` returns only
    # ComboStep/StunTriggerStep/StunEndStep, and `team_calculator` is the sole
    # caller of this function, while `rank_pipeline` routes its AnomalyStep-bearing
    # lists to `evaluate_steps_total` instead. It is asserted rather than trusted
    # because the two paths are converging, and the failure mode is a plausible
    # wrong number rather than a crash.
    _declared = [s for s in combo_steps if type(s).__name__ == "AnomalyStep"]
    if _declared:
        msg = (
            f"simulate_combo_steps derives anomalies from each step's anomaly_buildup, "
            f"so it cannot accept a step list that already declares "
            f"{len(_declared)} AnomalyStep(s) — they would be counted twice. "
            f"Route pre-materialised anomaly steps through evaluate_steps_total instead."
        )
        raise ValueError(msg)

    # Wrap enemy to inject the initial stun state without mutating the original.
    # Supports both DB models and frozen EnemySnapshot dataclasses.
    enemy_wrapped = _EnemyWithStun(enemy, is_stunned)

    conditions = base_conditions or []
    # Single-agent fallback is always keyed by the constant agent_id.
    all_snapshots: dict[str, BuildSnapshot] = {agent_id: build}
    if member_snapshots:
        all_snapshots.update(member_snapshots)

    sim_steps: list[SimulatedAttackStep] = []
    # moves_db_by_key: agent_key (normalised name) → {move_name: _StepMoveSpec}
    moves_db_by_key: dict[str, dict[str, _StepMoveSpec]] = {}

    for idx, step in enumerate(combo_steps):
        # Detect step type by class name to avoid importing combo_types at module load.
        step_class = type(step).__name__
        # In single-agent mode every step uses the constant agent_id so the default
        # (Phase 5A) path produces identical SimulatedAttackStep sequences.
        step_aid = (
            getattr(step, "agent_id", agent_id) if member_snapshots is not None else agent_id
        )
        step_snap = all_snapshots.get(step_aid, build)

        if step_class == "StunTriggerStep":
            sim_steps.append(
                SimulatedAttackStep(
                    agent_id=step_aid,
                    move_name="stun_trigger",
                    attacks=[],
                    conditions=conditions,
                )
            )
        elif step_class == "StunEndStep":
            sim_steps.append(
                SimulatedAttackStep(
                    agent_id=step_aid,
                    move_name="stun_end",
                    attacks=[],
                    conditions=conditions,
                )
            )
        else:  # ComboStep
            move_name = f"_step_{idx}"
            synthetic = _SyntheticAttack(
                id=step.attack_id,
                name=step.attack_name,
                element=step.element,
                damage_base=step.multiplier,
                damage_growth=0,
                # Carried from the resolved step's own `Attack` row. Hardcoding 0
                # here (with `_StepMoveSpec.buildup` also defaulting to 0) is what
                # made this path emit no anomaly for any agent: the step loop's
                # DB-row fallback had nothing to sum even once the spec stopped
                # claiming an authored zero.
                anomaly_buildup=getattr(step, "anomaly_buildup", 0) or 0,
            )
            sim_steps.append(
                SimulatedAttackStep(
                    agent_id=step_aid,
                    move_name=move_name,
                    attacks=[synthetic],
                    conditions=conditions,
                )
            )
            a_key = _agent_key(step_snap.agent_name)
            _step_duration = getattr(step, "duration_s", None)
            moves_db_by_key.setdefault(a_key, {})[move_name] = _StepMoveSpec(
                scope=step.scope,
                element=step.element,
                **({"duration_s": _step_duration} if _step_duration is not None else {}),
                # Keyed by the step's real attack name, not the synthetic
                # `_step_N` move key (DESIGN §13.4).
                **_lumiflux_move_fields(step_snap.agent_name, step.attack_name),
            )

    moves_db = {k: _AgentMovesStub(v) for k, v in moves_db_by_key.items()}

    # Third and last `simulate()` call site (DESIGN §13.2). Assembled
    # unconditionally — a team with no Lumiflux agent gets empty kwargs, which
    # is byte-identical to omitting them.
    from app.services.lumiflux_assembly import assemble_lumiflux_inputs  # noqa: PLC0415

    lumiflux_inputs = assemble_lumiflux_inputs(
        all_snapshots, sim_steps, moves_db, fluxed_overrides=fluxed_overrides
    )

    return simulate(
        builds=all_snapshots,
        steps=sim_steps,
        enemy=enemy_wrapped,
        moves_db=moves_db,
        lumiflux_specs=lumiflux_inputs.specs,
        phase_flow_windows=lumiflux_inputs.phase_flow_windows,
        fluxed_elements=lumiflux_inputs.fluxed_elements,
    )
