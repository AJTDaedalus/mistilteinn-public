"""Assemble the Lumiflux arguments `simulate()` needs, from a resolved team and
a resolved rotation (DESIGN_remielle.md §13.2, Tasks 29/30).

This is **policy**: it knows about kit JSONs, agent elements, and rotations.
`lumiflux.py` is mechanism and stays agent-agnostic and ORM-free; `simulate()`'s
explicit-kwarg seam is the boundary between them and does not change. The
assembler sits outside that seam and produces its arguments.

There is exactly one of these, used by all three `simulate()` call sites, for a
blunt reason: the failure this whole phase exists to close (escalation E-5) is
"three call sites, one forgets". Three hand-rolled assemblies would re-create it
verbatim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.anomaly_simulator import _agent_key, walk_step_timeline
from app.services.lumiflux import AgentRef, resolve_fluxed_element
from app.services.lumiflux_loader import load_lumiflux_spec

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.services.anomaly_simulator import SimulatedAttackStep, StepTiming
    from app.services.build_damage_service import BuildSnapshot
    from app.services.lumiflux import LumifluxSpec

logger = logging.getLogger(__name__)

LUMIFLUX_ELEMENT = "lumiflux"

# Agents already warned about for the element/kit-data mismatch below, so the
# warning fires once per process rather than once per simulation. Same pattern
# as `modifier_loader._warned_unknown_conditions`.
_warned_element_mismatch: set[str] = set()


@dataclass(frozen=True)
class LumifluxInputs:
    """The two `simulate()` kwargs, assembled together.

    One return type rather than a bare tuple so the call sites read as
    ``simulate(..., lumiflux_specs=inputs.specs,
    phase_flow_windows=inputs.phase_flow_windows)`` — and so a future third
    Lumiflux argument is a field here, not a signature change at three sites.
    (``fluxed_elements`` was exactly that third argument, added by hardening
    Task 17, and it cost one field plus one line per call site.)
    """

    specs: dict[str, LumifluxSpec]
    phase_flow_windows: dict[str, list[tuple[float, float]]]
    # Resolved Attribute Flux per Lumiflux agent_id (P-F1, hardening Task 17).
    # `simulate()` reads this to dual-tag her hits: the fluxed element picks
    # the DMG% bucket and the enemy RES row, while `agent_element` stays
    # "lumiflux" for every identity check (DESIGN §5.2).
    fluxed_elements: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when no agent on this team is a Lumiflux agent.

        Passing an empty `LumifluxInputs` through to `simulate()` is a
        byte-identical no-op, so callers never need to branch on this — it
        exists for tests and for logging.
        """
        return not self.specs and not self.phase_flow_windows and not self.fluxed_elements


def _warn_if_lumiflux_data_without_lumiflux_element(
    agent_id: str, build: BuildSnapshot
) -> None:
    """Warn when an agent ships a `lumiflux` kit block but is not Lumiflux in the DB.

    Pipeline finding P-F3, hardening Task 16. This is not a hypothetical: it is
    the exact state production is in right now. `alembic upgrade` does not
    change an agent's element — only a re-seed does — so a deploy that runs
    migrations and skips `scripts.seed_db` leaves Remielle stored as
    `physical`, and the element predicate above then skips her silently. Every
    Lumiflux mechanic (Refringe, Voidflare capture, Luminize, Phase Flow) is
    inert, damage numbers are quietly wrong, and nothing anywhere says so.

    That silence is precisely why this has to be loud: a subsystem shipping
    inert with no signal is escalation E-5's failure mode, and the same shape
    caused it the first time.

    Cost is one `lru_cache`-backed lookup per non-Lumiflux agent per assembly
    call, and the assembler runs once per simulation -- not once per optimizer
    candidate -- so this is not on any hot path.
    """
    source_id = getattr(build, "agent_source_id", "")
    if not source_id or source_id in _warned_element_mismatch:
        return
    if load_lumiflux_spec(source_id) is None:
        return
    _warned_element_mismatch.add(source_id)
    logger.warning(
        "Agent %r (agent_id=%s, source_id=%r) ships a `lumiflux` kit block but "
        "the database records its element as %r, not %r. The whole Lumiflux "
        "subsystem is INERT for this agent -- no Refringe, no Voidflare "
        "capture, no Luminize, no Phase Flow -- and its damage numbers are "
        "wrong by however much that kit is worth. This almost always means the "
        "database was migrated but not re-seeded: run "
        "`python -m scripts.seed_db` against it. Warned once per process.",
        getattr(build, "agent_name", "?"),
        agent_id,
        source_id,
        getattr(build, "agent_element", ""),
        LUMIFLUX_ELEMENT,
    )


def assemble_lumiflux_inputs(
    builds: Mapping[str, BuildSnapshot],
    steps: Sequence[SimulatedAttackStep],
    moves_db: Mapping[str, Any],
    fluxed_overrides: Mapping[str, str] | None = None,
) -> LumifluxInputs:
    """Build `simulate()`'s Lumiflux arguments for one team and one rotation.

    Cheap enough to call unconditionally: a team with no Lumiflux agent does no
    file I/O at all (the element predicate is read straight off the snapshots),
    and a team with one pays a single cached kit-JSON read per process.

    ``specs`` is keyed by ``agent_id`` — the same key `builds` uses, which is
    what `simulate()` looks Lumiflux agents up by. The predicate is
    ``agent_element == "lumiflux"``; ``agent_source_id`` is only how the spec is
    then found (DESIGN §13.1).

    A Lumiflux-element agent whose spec cannot be found is a **loud** skip. It
    means a kit JSON is missing its `lumiflux` block, and silence on exactly
    that condition is how the subsystem shipped inert in the first place.

    ``refringe_flat_bonuses`` deliberately needs no work here: Refringe's flat,
    condition-gated terms already reach the calc through the ordinary modifier
    engine as the ``refringe_flat_bonus_bp`` combat stat, which
    `_resolve_refringe` reads. Re-resolving them here would double-count them.
    """
    specs: dict[str, LumifluxSpec] = {}
    for agent_id, build in builds.items():
        if getattr(build, "agent_element", "") != LUMIFLUX_ELEMENT:
            _warn_if_lumiflux_data_without_lumiflux_element(agent_id, build)
            continue
        source_id = getattr(build, "agent_source_id", "")
        spec = load_lumiflux_spec(source_id) if source_id else None
        if spec is None:
            logger.warning(
                "Lumiflux agent %r (agent_id=%s, source_id=%r) has no loadable "
                "`lumiflux` kit block — Refringe, Voidflare capture, Luminize and "
                "Phase Flow are all inert for this agent this run. Check "
                "app/data/modifiers/agents/ and run "
                "`python -m scripts.validate_kits --level l0`.",
                getattr(build, "agent_name", "?"),
                agent_id,
                source_id,
            )
            continue
        specs[agent_id] = spec

    windows: dict[str, list[tuple[float, float]]] = {}
    if specs and steps:
        timings = walk_step_timeline(dict(builds), steps, dict(moves_db))
        for agent_id, spec in specs.items():
            agent_windows = _phase_flow_windows_for(
                agent_id,
                timings,
                builds=builds,
                moves_db=moves_db,
                duration_s=spec.phase_flow_duration_s,
            )
            if agent_windows:
                windows[agent_id] = agent_windows

    # P-F1 (hardening Task 17): resolve each Lumiflux agent's Attribute Flux
    # here, at the one seam all three `simulate()` call sites already share.
    # The API resolved and echoed this value as "the element actually used"
    # while no caller passed it into the damage chain, so her hits were
    # computed as pure Lumiflux -- her fluxed-element DMG% discs contributed
    # nothing and the enemy's RES for that element was replaced by a neutral 0.
    #
    # Slot ORDER matters (flux is "the next slot, cyclic"), and the order used
    # is `builds`' own iteration order. Every caller builds that mapping in
    # team-slot order, and `test_assembler_flux_matches_the_primitive` pins
    # that this agrees with `resolve_fluxed_element` on the same sequence.
    #
    # An explicit per-agent override wins over the derived value (DESIGN §5.3).
    # Threading it here rather than only at the API layer is what keeps the
    # echoed `fluxed_element` and the element actually used from diverging --
    # the API resolves override-or-derived for its response, so if the
    # assembler derived independently, supplying an override would put the two
    # back out of step, which is the narrow form of the very defect P-F1 is.
    overrides = fluxed_overrides or {}
    fluxed: dict[str, str] = {}
    if specs:
        ordered = [
            AgentRef(build_id=agent_id, element=getattr(build, "agent_element", ""))
            for agent_id, build in builds.items()
        ]
        for agent_id in specs:
            override = overrides.get(agent_id)
            if override and override != LUMIFLUX_ELEMENT:
                fluxed[agent_id] = override
                continue
            subject = next(a for a in ordered if a.build_id == agent_id)
            resolved = resolve_fluxed_element(ordered, subject)
            if resolved and resolved != LUMIFLUX_ELEMENT:
                fluxed[agent_id] = resolved

    return LumifluxInputs(
        specs=specs, phase_flow_windows=windows, fluxed_elements=fluxed
    )


def _is_arming(
    timing: StepTiming,
    builds: Mapping[str, BuildSnapshot],
    moves_db: Mapping[str, Any],
) -> bool:
    """Whether this step's move carries ``phase_flow_entry``.

    Generic, like ``triggers_luminize``: the flag is authored on the move, so a
    second Lumiflux agent with a different entry move is a JSON diff.
    """
    build = builds.get(timing.agent_id)
    if build is None:
        return False
    agent_moves = moves_db.get(_agent_key(build.agent_name))
    if agent_moves is None:
        return False
    move = agent_moves.moves.get(timing.move_name)
    return bool(getattr(move, "phase_flow_entry", False))


def _phase_flow_windows_for(
    agent_id: str,
    timings: Sequence[StepTiming],
    *,
    builds: Mapping[str, BuildSnapshot],
    moves_db: Mapping[str, Any],
    duration_s: float,
) -> list[tuple[float, float]]:
    """One Lumiflux agent's Phase Flow windows over a rotation (DESIGN §13.3).

    * **Entry.** The agent uses a move flagged ``phase_flow_entry`` and then
      *ceases to be the acting agent* — an explicit ``switch`` step, or simply
      the next field-occupying step belonging to somebody else. The window opens
      at the instant she stops acting, not at the arming move: the guide's
      wording is "enter the Phase Flow state **upon switching out**" (line 88).
      Being armed survives her own later moves; only the swap-out consumes it.
    * **Exit.** ``min(entry + duration_s, the next time she acts)``. She can only
      act again by being swapped back to, which ends the state.

    Version 1 does **not** gate entry on a Floating Radiance count — FR
    arithmetic is out of scope (OQ-5), so the rotation containing the arming
    move stands in for "she had the resource". A rotation that never swaps away
    from her therefore produces no windows and Phase Flow contributes nothing;
    that is correct behaviour under this model, not a bug, and it is why the
    end-to-end tests must use a rotation that actually swaps.

    This is a modelling choice with no in-game data distinguishing it from the
    runner-up (explicit per-step annotation, rejected as pushing engine state
    into hand-authored rotations). Recorded in `docs/DECISIONS.md` and re-opened
    by DESIGN §9.4's re-baseline pass.
    """
    windows: list[tuple[float, float]] = []
    armed = False
    open_at: float | None = None
    last_end: float | None = None

    for timing in timings:
        if timing.agent_id == agent_id:
            if not timing.occupies_field:
                continue
            if open_at is not None:
                # She is back on field: the state ends the moment she is
                # swapped to, which is when `simulate()` timestamps the switch.
                # `is not None`, not truthiness — a switch at t=0.0 is real.
                back_at = timing.t_switch if timing.t_switch is not None else timing.t_start
                windows.append((open_at, min(open_at + duration_s, back_at)))
                open_at = None
            if _is_arming(timing, builds, moves_db):
                armed = True
            last_end = timing.t_end
            continue

        if not timing.occupies_field:
            continue
        if armed and open_at is None and last_end is not None:
            open_at = last_end
            armed = False

    if open_at is not None:
        windows.append((open_at, open_at + duration_s))

    _assert_well_formed(agent_id, windows)
    return windows


def _assert_well_formed(agent_id: str, windows: Sequence[tuple[float, float]]) -> None:
    """Every window has positive width, and no two overlap.

    Both are true by construction — a window closes before the next arming move
    can be acted, and an intervening field-occupying step always advances the
    clock. They are checked rather than assumed because either failure is
    silent: a zero-width window makes the tick loop emit nothing while looking
    wired, and overlapping windows double-count ticks. A raise here is
    unreachable in a healthy engine and attributable when it is not — the same
    reasoning as the modifier loader's raise on a duplicate ``source_id``.
    """
    previous_end: float | None = None
    for start, end in windows:
        if end <= start:
            raise ValueError(
                f"Phase Flow window for {agent_id!r} has non-positive width "
                f"({start}, {end}) — the tick loop would emit nothing while the "
                f"wiring looks correct"
            )
        if previous_end is not None and start < previous_end:
            raise ValueError(
                f"Phase Flow windows for {agent_id!r} overlap: window starting at "
                f"{start} begins before the previous one ended at {previous_end} — "
                f"ticks in the overlap would be counted twice"
            )
        previous_end = end
