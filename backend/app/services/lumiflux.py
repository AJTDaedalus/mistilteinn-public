"""Lumiflux mechanism primitives — Attribute Flux resolution and the Refringe
coefficient formula, shared by every Lumiflux-specialty agent.

Pure, ORM-free module (the design doc's mechanism/policy split): it contains
no agent-specific number. Every coefficient a Lumiflux agent's kit needs — AP
ratios, flat bonuses, Luminize multipliers, buildup-point counts, pool/store
caps, Phase Flow cadence — is authored in that agent's kit JSON's ``lumiflux``
block and loaded into a ``LumifluxSpec`` by ``lumiflux_loader``, a process-wide
cached loader keyed by agent ``source_id``. **Not** at snapshot-build time:
nothing in the spec is build-derived (live AP is read at sim time by design,
see §2.1's naming trap), so there is nothing to bake, and baking would duplicate
identical static state across every optimizer snapshot. See DESIGN §13.1 for the
ruling and what was rejected. A second agent on this element is a JSON file, not
an engine change.

All percentage-like values are basis points (10000 = 100%), matching the rest
of ``app/services`` (see ``damage_calculator.py``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.models.enums import Element


@dataclass(frozen=True)
class LumifluxSpec:
    """Per-agent Lumiflux coefficients, loaded from that agent's kit JSON.

    No field carries a default. This dataclass holds a specific agent's
    numbers only because a curation task constructs one from that agent's
    kit JSON — a default here would be a de facto hardcoded constant for
    whichever agent happens to get authored first, which is exactly the
    invariant DESIGN §3 rules out.
    """

    # Per-enemy Lumiflux Buildup Point pool ceiling (P2).
    point_cap: int
    # Voidflare store depth — "most recent kept" (P1/P3).
    voidflare_cap: int
    # Refringe coefficient's Anomaly-Proficiency term, in bp *per AP point*
    # (e.g. 2 == "0.02%/AP"). Applied by direct multiplication against AP —
    # the same convention as `luminize_ap_bonus_bp` below, not the
    # fraction-of-a-stat `ratio // 10000` convention used by e.g.
    # `atk_scale_ratio` (DESIGN §2 OQ-1).
    refringe_ap_ratio_bp: int
    # Refringe's flat, condition-gated additive terms (e.g. a team
    # composition count gate, a mindscape tier), in bp. Keys are opaque
    # condition labels this module does not interpret — the caller (kit
    # JSON authoring / buff resolution) decides which entries are active
    # for a given build and sums them into `refringe_coefficient`'s
    # `flat_bonus_bp` kwarg.
    refringe_flat_bonuses: Mapping[str, int]
    # Luminize's per-trigger DMG multiplier, in bp, at the agent's authored
    # skill level. One Luminize instance fires per stored Voidflare
    # (DESIGN §7.2 OQ-2), and each trigger move (e.g. an Assist, an
    # Ultimate, a Hold Basic, an Enhanced Hold Basic) carries its own
    # multiplier — opaque keys, same convention as `refringe_flat_bonuses`.
    luminize_multipliers: Mapping[str, int]
    # Luminize's multiplicative Anomaly-Proficiency bonus, in bp *per AP
    # point* (e.g. 20 == "0.2%/AP"), read against the agent's own *live* AP
    # — never the stored Voidflare's AP snapshot (DESIGN §2.1's naming
    # trap: these are two different AP values).
    luminize_ap_bonus_bp: int
    # Phase Flow's synthetic-attack cadence, in seconds (P4).
    phase_flow_tick_s: float
    # How long a Phase Flow window lasts once entered, in seconds. Per-agent
    # like everything else here — it is that agent's entry resource divided by
    # its drain rate, not an engine constant. Read by
    # `lumiflux_assembly.assemble_lumiflux_inputs` to close a window opened by
    # a swap-out (DESIGN §13.3); distinct from any team-buff duration a Phase
    # Flow entry also happens to grant, which is an ordinary modifier row.
    phase_flow_duration_s: float
    # Per-flight-attack Lumiflux point counts, in slot order. Used to derive
    # Phase Flow's expected-value point tick (DESIGN §7.3:
    # E[points] = mean(flight_attack_points), unless raw data shows
    # selection weights).
    flight_attack_points: tuple[int, ...]
    # Per-flight-attack damage multiplier and daze, in bp, same slot order as
    # `flight_attack_points` -- together the three tuples are the raw data
    # Task 15's EV tick averages (`phase_flow_ev`). `flight_attack_daze_bp`
    # is carried for explainability only: this codebase has no stun-buildup
    # simulation to feed it into (CLAUDE.md: buildup/decay is a deliberate
    # non-goal), so it never drives damage math, only a tick's detail dict.
    flight_attack_mv_bp: tuple[int, ...]
    flight_attack_daze_bp: tuple[int, ...]


@dataclass(frozen=True)
class AgentRef:
    """Minimal per-slot identity for Attribute Flux resolution.

    Deliberately not `team_calculator.TeamMember`: that type carries
    modifiers and the rest of the buff-resolution surface.
    `resolve_fluxed_element` only ever needs "who is in this slot, and what
    element are they" — keeping the input this thin is what keeps this
    module importable standalone (DESIGN §3).
    """

    build_id: str
    element: Element


def resolve_fluxed_element(
    ordered_agents: Sequence[AgentRef],
    subject: AgentRef,
) -> Element | None:
    """Element of the agent in the *next* team slot, cyclic (DESIGN §5.1).

    Team slot order is the literal ``teams.build1_id/build2_id/build3_id``
    ordering — never derived, never persisted back onto the agent or build.
    The guide's worked example (DESIGN §2 OQ-3): team
    ``[Jane(physical), Velina(?), subject]`` fluxes ``subject`` to Jane's
    element, because the last slot wraps back to the first.

    A 2-agent team's cyclic wrap lands back on "the other agent" — there is
    no third slot to skip past. A solo team (or an empty one) has no next
    slot at all, so the result is ``None``.

    Raises ``ValueError`` if ``subject`` is not one of ``ordered_agents`` —
    that is a caller contract violation (the subject must be a member of the
    team whose order it is asking about), not a "no flux" case.
    """
    n = len(ordered_agents)
    if n <= 1:
        return None
    for index, agent in enumerate(ordered_agents):
        if agent.build_id == subject.build_id:
            return ordered_agents[(index + 1) % n].element
    raise ValueError(
        f"subject build_id {subject.build_id!r} is not a member of ordered_agents"
    )


@dataclass
class LumifluxEnemyState:
    """Mutable per-enemy Lumiflux Buildup Point pool (P2).

    Exactly one of these exists per simulated enemy — `anomaly_simulator.py`
    holds it the same way it holds `active_aura`, `frostbite_until`, etc.:
    a single local that gets reassigned over the run ("single simulated
    enemy" convention, `anomaly_simulator.py` F-11/F-23a comment). It is
    **not** partitioned by Lumiflux agent: a second Lumiflux agent in the
    squad reads and writes the exact same pool. `owner_agent_id` is
    attribution only (who most recently contributed a point) — it never
    gates who can add to or consume from `points`, and there is no
    `(enemy, agent)` composite key anywhere in this module.

    Unlike `LumifluxSpec` (frozen — one per agent, loaded once from kit
    JSON and never mutated), this state changes over the course of a sim
    run as points are applied and consumed. It is therefore a plain
    (non-frozen) dataclass — but the *logic* that changes it
    (`apply_lumiflux_points` / `consume_lumiflux_points` below) is still
    pure: each returns a new instance rather than mutating fields in
    place, matching DESIGN §3's mechanism/policy split (arithmetic here,
    storage in the simulator). Callers hold the single "current" instance
    and replace it, the same pattern `active_aura` reassignment already
    uses.
    """

    points: int
    owner_agent_id: str | None
    last_point_at: float | None
    # When the pool most recently went from >=1 point to 0, or None if it has
    # never emptied. This — NOT `last_point_at` — is what the Prismatic linger
    # clock reads (E-F5(b), hardening Task 13). The DB text ties the 8s to
    # *removal*: "Prismatic is removed when the enemy no longer has Lumiflux
    # Buildup. After Prismatic is removed, the Anomaly Buildup Rate increase
    # persists for an additional 8s." Prismatic is present while the pool is
    # non-empty, so it is removed at the emptying instant, and the 8s runs
    # from there. Measuring from the last application instead cut the linger
    # short by however long the points sat unspent.
    emptied_at: float | None = None

    @classmethod
    def empty(cls) -> LumifluxEnemyState:
        """A freshly-encountered enemy: no points, no contributor, no history."""
        return cls(points=0, owner_agent_id=None, last_point_at=None, emptied_at=None)


def apply_lumiflux_points(
    state: LumifluxEnemyState | None,
    spec: LumifluxSpec,
    count: int,
    *,
    agent_id: str,
    at: float,
) -> LumifluxEnemyState:
    """Add ``count`` Lumiflux Buildup Points to the per-enemy pool.

    ``state=None`` means "no state recorded yet for this enemy" (equivalent
    to ``LumifluxEnemyState.empty()``) — callers do not need to special-case
    a fresh enemy.

    Caps at ``spec.point_cap`` — read from the spec, never hardcoded, so a
    second Lumiflux agent with a different cap is a JSON diff, not an engine
    change (DESIGN §3). Because the pool is shared (not keyed by agent),
    calling this with a different ``agent_id`` than the pool's current
    ``owner_agent_id`` still adds to the *same* ``points`` total — that is
    the structural guarantee behind "a second Lumiflux agent shares the
    pool" (this feature's TASKS file, Task 9).

    ``owner_agent_id`` and ``last_point_at`` update to the contributing
    agent/time whenever ``count > 0``, even if the pool was already at cap
    — attribution and the Prismatic linger clock (DESIGN §7.1's "+8s
    linger") both track "who/when a point was most recently applied," not
    "who/when a point actually changed the pool total."

    Raises ``ValueError`` for ``count < 0`` — this function only ever adds;
    use ``consume_lumiflux_points`` to remove.
    """
    if count < 0:
        raise ValueError(f"apply_lumiflux_points count must be >= 0, got {count}")
    base = state if state is not None else LumifluxEnemyState.empty()
    if count == 0:
        return base
    return LumifluxEnemyState(
        points=min(spec.point_cap, base.points + count),
        owner_agent_id=agent_id,
        last_point_at=at,
        # The pool is non-empty again, so there is no pending linger to run.
        emptied_at=None,
    )


def consume_lumiflux_points(
    state: LumifluxEnemyState | None,
    count: int = 1,
    *,
    at: float | None = None,
) -> LumifluxEnemyState:
    """Remove ``count`` Lumiflux Buildup Points from the per-enemy pool.

    Floors at 0 and never raises for an under-full pool — a Refringe
    trigger (Task 11) checking "does the enemy hold >=1 point" is the
    caller's job, not this function's. ``owner_agent_id`` and
    ``last_point_at`` are left untouched: they describe the most recent
    *application*, which consuming a point does not change.

    ``at`` is the consumption timestamp. Passing it lets this record
    ``emptied_at`` when the pool actually reaches 0, which is what the
    Prismatic linger clock reads (E-F5(b), hardening Task 13). This
    function's docstring previously argued the opposite — that the linger
    runs from the last point ever applied — which under-ran the buff by
    however long the points sat unspent before being consumed. The DB text
    ties it to removal, and the pool empties at consumption, not at
    application. ``at=None`` keeps the old ``emptied_at`` untouched, so a
    caller that does not care about the linger is unaffected.

    Raises ``ValueError`` for ``count < 0``.
    """
    if count < 0:
        raise ValueError(f"consume_lumiflux_points count must be >= 0, got {count}")
    base = state if state is not None else LumifluxEnemyState.empty()
    if count == 0:
        return base
    remaining = max(0, base.points - count)
    emptied_at = base.emptied_at
    if remaining == 0 and base.points > 0 and at is not None:
        emptied_at = at
    return LumifluxEnemyState(
        points=remaining,
        owner_agent_id=base.owner_agent_id,
        last_point_at=base.last_point_at,
        emptied_at=emptied_at,
    )


def refringe_coefficient(
    spec: LumifluxSpec,
    anomaly_proficiency: int,
    *,
    flat_bonus_bp: int,
) -> int:
    """Total Refringe coefficient, in bp, at one Anomaly Proficiency value.

    ``spec.refringe_ap_ratio_bp`` is bp *per AP point*, so the AP-derived
    term is a direct multiplication — no ``// 10000`` floor division, unlike
    a fraction-of-a-stat ratio (e.g. ``atk_scale_ratio``). That keeps the
    term exactly linear in AP, with no integer-truncation kink (DESIGN §9.1
    test 1).

    ``flat_bonus_bp`` is the caller's already-resolved sum of whichever
    entries in ``spec.refringe_flat_bonuses`` are active for the build in
    question (e.g. a team-composition count gate, a mindscape tier) — this
    function does not interpret conditions, only combines an
    already-resolved flat term with the AP-derived one.
    """
    ap_term_bp = anomaly_proficiency * spec.refringe_ap_ratio_bp
    return ap_term_bp + flat_bonus_bp


@dataclass(frozen=True)
class VoidflareRecord:
    """One captured Refringed Anomaly's stats, frozen at capture time (P1/P3,
    DESIGN §7.2 — the guide's exact enumeration, line 78).

    Immutability is the point: a teammate buffed *after* storage must not
    change an already-stored Voidflare's Luminize damage (DESIGN §9.1 test
    3). Plain ``int``/``float`` fields already make this true by value
    semantics — ``frozen=True`` additionally makes an accidental in-place
    mutation attempt raise, rather than silently succeed if a future change
    ever gave a field a mutable type.

    ``element`` is a plain ``str``, not the ``Element`` enum DESIGN's
    pseudocode names it as — every other element field in this codebase
    (``BuildSnapshot.agent_element``, attack/aura elements in
    ``anomaly_simulator.py``) is a plain string, and Luminize's own RES
    lookup (``enemy.res_map.get(voidflare.element, ...)``, Task 13) needs a
    string key. Matching the engine-wide convention here avoids an
    enum<->str round-trip with no benefit.
    """

    element: str  # the anomaly's own attribute — never the equipper's, never the fluxed one
    atk: int
    dmg_bonus_bp: int  # sum of the teammate's live dmg_bonuses at capture time
    pen_ratio_bp: int
    pen_flat: int
    anomaly_proficiency: int  # the snapshot's AP -- AnomalyProfArea only (DESIGN §2.1)
    refringe_coefficient_bp: int
    stored_at: float
    # Provenance, NOT a damage input -- must never be passed to a damage
    # function (Task 36 / escalation E-8 in the Lumiflux feature log). The store is keyed by the
    # *Lumiflux* agent and any teammate who triggers Refringe banks into it, so
    # one store can hold Voidflares captured from several different agents. The
    # optimizer has to tell them apart: one captured from the build being
    # optimized must be rescored against every candidate disc set, while one
    # captured from a support is genuinely constant. Same category as
    # ``stored_at`` -- engine bookkeeping, not part of DESIGN §7.2's enumeration
    # of what the mechanic freezes, so it does not loosen that pin.
    captured_from: str = ""


def store_voidflare(
    store: deque[VoidflareRecord] | None,
    record: VoidflareRecord,
    cap: int,
) -> deque[VoidflareRecord]:
    """Append ``record`` to the Voidflare store, creating a fresh
    ``deque(maxlen=cap)`` on first use.

    ``deque``'s own ``maxlen`` eviction *is* "most recent kept" (DESIGN
    §7.2) — appending past capacity silently drops the oldest entry from
    the opposite end. No bespoke eviction arithmetic to test separately
    from Python's own (already-tested) primitive, unlike
    `LumifluxEnemyState`'s cap/floor math.
    """
    result = store if store is not None else deque(maxlen=cap)
    result.append(record)
    return result


def clear_voidflare_store(cap: int) -> deque[VoidflareRecord]:
    """A fresh, empty store — Phase Flow entry and either Hold Basic both
    clear the equipper's stored Voidflares (DESIGN §7.2).

    Wired into the simulator by hardening Task 10 (engine finding E-F3);
    until then this had no call site at all, so back-to-back Luminize
    triggers re-fired the same Voidflares and the store only ever grew.
    Two call sites, both inside the step loop:

    * **Phase Flow entry** — driven off each window's start time through a
      min-heap of pending clears, drained as the step clock passes each one.
      That ordering is the reason this was deferred originally: a clear at
      t=5 must wipe a t=2 capture without retroactively wiping a t=10
      in-window one, which a post-pass cannot express. Draining in-loop can.
    * **Either Hold Basic** — via the move-spec flag
      ``clears_voidflare_store``, applied *after* that step's Luminize
      resolves, so the move still fires off the Voidflares it then discards.
      Kept separate from ``triggers_luminize`` because Assist and Ultimate
      trigger Luminize without clearing.
    """
    return deque(maxlen=cap)


def phase_flow_expected_value(values: tuple[int, ...]) -> int:
    """Mean of N per-flight-attack values, rounded to the nearest int
    (P4, DESIGN §7.3).

    Generic over what's being averaged — `LumifluxSpec.flight_attack_points`
    (buildup-point count), `.flight_attack_mv_bp` (damage), or
    `.flight_attack_daze_bp` (daze) all use this the same way. This is the
    deterministic expected-value substitute for RNG-selecting one of the
    three real Phase Flow flight attacks each tick (brief §11 non-goal: no
    RNG anywhere in this engine). ``E[points] = (0+1+2)/3 = 1`` is the
    guide's own worked example.
    """
    return round(sum(values) / len(values))


@dataclass(frozen=True)
class PhaseFlowState:
    """Explicit per-system on/off-field classification for Phase Flow (P4,
    DESIGN §7.3 OQ-9).

    There is no single ``is_on_field`` boolean for an agent in Phase Flow —
    different systems in this codebase already disagree about what
    "on-field" means for her: energy-regen passives (e.g. Flamemaker
    Shaker's off-field ER) should treat her as on-field (she's actively
    dealing damage via her flight attacks, even though she's nominally
    swapped out), while 4pc Feathered Fate's off-field persistence should
    treat her as off-field, and her flight-attack damage's modifier merge
    uses the off-field rule (`_resolve_offfield_modifiers`) regardless.
    Collapsing these into one flag would silently pick the wrong answer for
    at least one of them.

    ``is_on_field_for`` raises on any system name not in this table — DESIGN
    §7.3 is explicit that "any system that later asks gets an explicit row
    here... a default is a bug." A new consuming system must be added as a
    named field + a branch here, not assumed.
    """

    energy_regen_on_field: bool = True
    feathered_fate_persistence_on_field: bool = False
    modifier_merge_on_field: bool = False  # False -> `_resolve_offfield_modifiers`
    flight_attack_scope: str = "special"

    def is_on_field_for(self, system: str) -> bool:
        """Whether ``system`` should treat this agent as on-field right now.

        Raises ``ValueError`` for any ``system`` name not one of
        ``"energy_regen"``, ``"feathered_fate_persistence"``, or
        ``"modifier_merge"``.
        """
        if system == "energy_regen":
            return self.energy_regen_on_field
        if system == "feathered_fate_persistence":
            return self.feathered_fate_persistence_on_field
        if system == "modifier_merge":
            return self.modifier_merge_on_field
        raise ValueError(
            f"PhaseFlowState has no classification for system {system!r} — "
            "add a named field and a branch here, DESIGN §7.3's own rule "
            "against silently defaulting an unlisted system."
        )
