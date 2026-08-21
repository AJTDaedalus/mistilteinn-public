"""Loader for agent-specific move buildup and duration JSON configs."""

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

_DEFAULT_DIR = Path(__file__).parent.parent / "moves" / "agents"

# ``moves`` must be keyed by the full DB attacks.name (e.g. "Ultimate: Voidstrike"),
# because anomaly_simulator looks specs up by that name. Files keyed by scope
# instead ("ultimate", "chain", ...) never resolve, so the simulator silently
# falls back to approximate timings and drops grants_state / grants_full_charge.
# Reject those at load time rather than degrading quietly.
_RESERVED_MOVE_KEYS: frozenset[str] = frozenset(
    {
        "all",
        "assist",
        "basic",
        "chain",
        "dash",
        "dodge_counter",
        "ex_special",
        "special",
        "ultimate",
    }
)


_CHANNEL_ROLES: frozenset[str] = frozenset({"entry", "tick", "release"})
_CHANNEL_BASES: frozenset[str] = frozenset({"per_second", "whole_channel", "per_tick"})


class ChannelSpec(BaseModel):
    """A hold-to-drain move: how long it may be held, and what that length scales.

    See docs/DESIGN_channeled_moves.md §4.2-§4.5. The rows of a channeled move do three
    different jobs, and the engine cannot tell which from the row alone:

    - ``entry``   fires once at channel start,
    - ``tick``    fires once per ``tick_s`` for the held duration -- *the rows the
                  step's ``channel_s`` scales*,
    - ``release`` fires once at channel end.

    ``roles`` maps ``attacks.param_name`` -> role. Keyed by ``param_name`` rather than
    ``hit_index`` deliberately: row counts and orderings move across re-seeds (this repo's
    own move files carry notes documenting exactly that drift), while ``param_name`` is the
    stable semantic handle. It is also NULL on a DB migrated but not re-seeded from nanoka,
    which is why the binding check is a DB-backed harness level under the
    skipped-level-BLOCKS contract (LCH) rather than a best-effort here.

    Roles are authored EXPLICITLY. A ``/Per Sec/`` regex over ``param_name`` would classify
    Norma/Promeia/Pryce for free and silently miss Burnice and Nicole -- the two signals
    that identify a channel do not coincide. The regex is a *validator* (LCH rule 4)
    instead, so upstream labels police the curator rather than replace them.

    ``tick_mv_basis`` picks how a tick row's multiplier is read, and the two readings differ
    by the whole channel length:

    - ``per_second``    -- the row IS a rate; ``mv_per_tick = row_mv * tick_s``.
    - ``whole_channel`` -- the row is the total over ``nominal_s``;
      ``mv_per_tick = row_mv * tick_s / nominal_s``.
    - ``per_tick``      -- the row is what ONE occurrence does; ``mv_per_tick = row_mv``.
      For a channel counted in discrete events rather than seconds -- Trigger's Sniper Stance
      fires shots and his ``Shot DMG Multiplier`` is one shot (D-CH1a), so ``tick_s`` decides
      how MANY a hold produces and never what one is worth. ``nominal_s`` is forbidden here for
      the same reason as on ``per_second``: there is nothing to divide by.

    Which one applies is decided by *release era*, not per-move judgement (DESIGN §4.3.1,
    DECISIONS D-CH1): early channels quote whole-duration totals (Burnice 1171, Trigger
    1361, Yixuan 1371), later ones quote per-second rates and say so in ``param_name``
    (Promeia 1541, Norma 1571, Pryce 1621). LCH rule 6 enforces the boundary so a further
    convention shift fails the build instead of arriving silently.

    **The parent move's ``duration_s`` means something different here.** On every other mode it
    is the whole move's animation length; on a channel it is the **non-held tail** -- the entry
    and release animation -- because the held part is the player's to choose and cannot be
    authored as a constant. The step's clock length is ``channel_s + duration_s``
    (``anomaly_simulator._step_duration_s``), and the resolver splits that same total across the
    steps it emits. Stated here as well as in MODIFIER_AUTHORING.md because a field that quietly
    changes meaning per mode is exactly what a curator gets wrong.

    Cost keys bind into ``agent_resource_costs`` (values live in the DB, per the
    source-of-truth rule); this file carries only the binding. All three are optional as a
    set -- Promeia and Pryce channel with no resource drain at all -- but a ``drain`` with
    no ``entry`` would bill a channel as free to start, which is never the real mechanic.
    """

    min_s: float = 0.0
    max_s: float
    default_s: float
    tick_s: float
    tick_mv_basis: str = "per_second"
    # The duration a `whole_channel` row's multiplier is the total OF. Defaults to `max_s`
    # (owner ruling D-CH2: a whole-duration MV is the total at MAXIMUM hold -- holding is how
    # you collect it, and it cannot be exceeded), so authoring it is only necessary for a move
    # that genuinely disagrees. Still FORBIDDEN with `per_second`, where the row is already a
    # rate: a field that looks load-bearing but is ignored is exactly how a silent 2x hides.
    nominal_s: float | None = None
    roles: dict[str, str]
    entry_cost_key: str | None = None
    drain_cost_key: str | None = None
    release_cost_key: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "ChannelSpec":
        if self.tick_mv_basis not in _CHANNEL_BASES:
            raise ValueError(
                f"tick_mv_basis {self.tick_mv_basis!r} is not one of {sorted(_CHANNEL_BASES)}"
            )
        if self.tick_mv_basis == "whole_channel":
            if self.nominal_s is None:
                # D-CH2. Assigned rather than left None so every consumer reads one field and
                # cannot re-derive the default differently.
                object.__setattr__(self, "nominal_s", self.max_s)
            if self.nominal_s <= 0:
                raise ValueError("nominal_s must be > 0")
        elif self.nominal_s is not None:
            raise ValueError(
                f"nominal_s is meaningless with tick_mv_basis={self.tick_mv_basis!r} (the row "
                "is already a rate, or already one occurrence) and would be silently ignored "
                "-- drop it, or switch the basis if the row is really a whole-channel total."
            )
        if self.tick_s <= 0:
            raise ValueError("tick_s must be > 0")
        if self.max_s <= self.min_s:
            raise ValueError(f"max_s ({self.max_s}) must exceed min_s ({self.min_s})")
        if not self.min_s <= self.default_s <= self.max_s:
            raise ValueError(
                f"default_s ({self.default_s}) is outside [{self.min_s}, {self.max_s}]"
            )
        bad_roles = sorted({r for r in self.roles.values() if r not in _CHANNEL_ROLES})
        if bad_roles:
            raise ValueError(
                f"unknown channel roles {bad_roles}; expected one of {sorted(_CHANNEL_ROLES)}"
            )
        if "tick" not in self.roles.values():
            raise ValueError(
                "a channel needs at least one 'tick' row -- with nothing for channel_s to "
                "scale, the move is not a channel and should stay atomic/variant."
            )
        if self.drain_cost_key and not self.entry_cost_key:
            raise ValueError(
                "drain_cost_key without entry_cost_key: a channel that drains per second "
                "but costs nothing to start is not a mechanic this game has."
            )
        if self.release_cost_key and not self.entry_cost_key:
            raise ValueError("release_cost_key without entry_cost_key")
        return self


class MoveBuildupSpec(BaseModel):
    """Per-move anomaly buildup, timing, and abloom/polarity curation for one agent move."""

    buildup: int | None = None
    duration_s: float = 1.0
    hits: int = 1
    element: str | None = None
    scope: str | None = None
    consolidated: bool = False
    polarity_disorder: bool = False
    # Mindscape level at which this move gains its Polarity Assault trigger, if the
    # trigger is a Mindscape effect rather than part of the base kit. Mirrors
    # `abloom_requires_mindscape`. 0 = base kit, always eligible.
    polarity_requires_mindscape: int = 0
    polarity_additional_mv: int = 0
    # TODO: migrate to DB once EX Special is added to SKILL_TYPE_MAP in importers.
    polarity_ap_coeff_base: int = 0
    polarity_ap_coeff_growth: int = 0
    abloom_mv_by_element: dict[str, int] | None = None
    abloom_ap_scaled: bool = True
    abloom_stat: str = "anomaly_proficiency"
    abloom_stun_mv_bonus: int = 0
    abloom_requires_mindscape: int = 0
    abloom_mv_multiplier_bp: int = 10_000
    abloom_mv_multiplier_requires_mindscape: int = 0
    abloom_extra_instance_bp: int = 0
    abloom_extra_instance_requires_mindscape: int = 0
    notes: str | None = None
    # P2 per-move state/charge annotations
    grants_state: str | None = None
    state_duration_s: float | None = None
    grants_full_charge: str | None = None
    # Documented metadata, NOT a simulated gate — no per-charge-level attack row exists
    # to key against (docs/DESIGN_move_key_resolution.md OQ-1, option (a)). Records the
    # assumption that every authored step of this move is a charge-level-N release.
    # When set (>0) on a sequential move, anomaly_simulator binds this move's Abloom to
    # the FINAL hit of the sequential cycle only — `hits` doubles as the documented
    # cycle length for that check (Aria: `hits=5`, `requires_charge_level=3`).
    requires_charge_level: int = 0
    # Luminize emission (Remielle, DESIGN_remielle.md §7.2, Task 14/20). Generic
    # fields any Lumiflux agent's moves.json may set -- not Remielle-specific in
    # the engine (anomaly_simulator.py reads them via plain getattr, so an
    # agent with neither field behaves exactly as before this task).
    triggers_luminize: bool = False
    luminize_mult_bp: int = 0
    # Per-move Lumiflux Buildup Point count (P2, DESIGN §7.1) -- data only, no
    # live call site wires this into the per-hit loop yet (same status Task 9's
    # own log left it in: the point-application plumbing exists, but nothing in
    # simulate()'s step-resolution loop invokes it for a real named move today;
    # Task 15's Phase Flow EV tick is the only real caller so far, and it reads
    # LumifluxSpec.flight_attack_points, not this field).
    lumiflux_points: int = 0
    # Phase Flow arming move (P4, DESIGN_remielle.md §13.3, Task 30). Generic
    # like `triggers_luminize`: the agent uses this move and then enters Phase
    # Flow *on switching out*, so `lumiflux_assembly` opens a window at the
    # swap-out that follows a step carrying this flag. The flag marks the arming
    # move, not the entry itself — a rotation that arms and never swaps away
    # from her produces no window at all.
    phase_flow_entry: bool = False
    # Does using this move clear the equipper's Voidflare store? (E-F3,
    # hardening Task 10.) Deliberately its own flag rather than a rider on
    # `triggers_luminize`: the core text clears on Phase Flow entry "or after
    # using Basic Attack: Rainbow's End or Basic Attack: Fleeting Grace", so
    # two of the four Luminize triggers clear and two (Assist, Ultimate) do
    # not. The simulator applies it AFTER the step's Luminize resolves, so the
    # move still fires off the Voidflares it is about to discard.
    clears_voidflare_store: bool = False
    # Hold-to-drain annotation (docs/DESIGN_channeled_moves.md). Present iff the move's
    # DB rows carry hit_mode='channel'. `None` on every move that is not a channel, which
    # is all of them until Task 12 -- so every existing spec behaves exactly as before.
    channel: ChannelSpec | None = None
    # Binds a NON-channel move to its own `agent_resource_costs` row, for agents whose EX
    # has several modes at different prices. Burnice's Tossing Method costs 10 and is billed
    # 40 today, because `Agent.ex_energy_cost` can only hold one of her six figures
    # (DESIGN_channeled_moves.md 4.5). Unset on every move that has one price, which is
    # most of them -- those keep billing the scalar and are untouched. A channel carries its
    # keys inside `channel` instead; setting both here would be two prices for one press.
    cost_key: str | None = None


class AftershockSpec(BaseModel):
    """Off-field aftershock proc rules: trigger scopes, resource gating, cooldowns for an agent."""

    react_to: list[str]
    react_scopes: list[str] | None = None
    requires_off_field: bool = True
    resource: str | None = None
    cost: float = 0.0
    min_resource: float | None = None
    initial: float = 0.0
    max: float = 0.0
    cooldown_s: float = 0.0
    max_per_window: int | None = None
    window_s: float | None = None
    procs_per_trigger: int = 1
    aftershock_mv_bp: int
    element: str | None = None
    damage_path: str = "standard"
    notes: str | None = None
    # P2 state-gate + repeat-chain (Pulchra)
    requires_state: str | None = None
    # repeat_max > 0 selects the costless repeat-chain path, which bypasses the
    # cooldown/resource/window gating entirely — procs_per_trigger, cooldown_s,
    # resource/cost, and max_per_window/window_s are ignored in that mode.
    repeat_max: int = 0
    finisher_mv_bp: int | None = None
    # P2 on-field self path (S0 Anby)
    on_field_self: bool = False
    # P2 White Thunder cascade (S0 Anby)
    wt_consume_scopes: list[str] | None = None  # hit scopes on the active agent that consume 1 WT
    wt_smite_mv_bp: int | None = None  # Thunder Smite MV when tally reaches cap
    wt_boundary_mv_bp: int | None = None  # Boundary MV following Thunder Smite
    wt_tally_cap: int = 3  # tally threshold to trigger Smite + Boundary
    # P2 White Thunder vortex (S0 Anby M6): a second, independent modulus on the
    # same WT-consume event stream (does not share/reset wt_tally's counter).
    wt_vortex_mv_bp: int | None = None  # vortex MV when the vortex tally reaches cap
    wt_vortex_tally_cap: int = 6  # tally threshold to trigger the vortex
    wt_vortex_requires_mindscape: int = 0  # 0 = always eligible (once mv_bp is set)
    # P2 re-tag (S0 Anby core: Chain/Ult treated as Aftershock DMG).
    # Hit scopes re-tagged as Aftershock DMG so Aftershock DMG% bonuses apply.
    retag_as_aftershock: list[str] = Field(default_factory=list)
    # True when the retag exists only once Potential is unlocked (#90). Soldier 0 -
    # Anby is the live case: "Soldier 0 - Anby's Chain Attack and Ultimate are treated
    # as Aftershock DMG" appears ONLY in his `potential='unlocked'` core text, so a
    # locked build was being credited Aftershock DMG% bonuses on Chain and Ultimate
    # that its kit does not grant. Applied where the spec is assembled per build, so
    # the simulator never learns the variant exists.
    retag_requires_potential: bool = False


class AgentMovesSpec(BaseModel):
    """Top-level move-config document for one agent: per-move buildup specs plus aftershock.

    ``agent_id``/``agent_name`` stay optional *on the model* — dozens of unit tests build
    this class directly as an in-memory ``moves_db`` fixture for the simulator and never
    touch a file, so a model-level requirement would break them for no safety gain (they
    aren't going through ``load_agent_moves`` and its file/stem coherence check below).
    Required-and-validated is a property of *loading from a file*, enforced by
    ``_validate_agent_binding``, not of the type itself.
    """

    agent_id: str | None = None
    agent_name: str | None = None
    moves: dict[str, MoveBuildupSpec]
    aftershock: AftershockSpec | None = None


# Structural UUID check only — does the string *look like* a DB id? Whether it actually
# names a real agents.id row is a DB-backed question that belongs to validate_kits L4
# (Task 3 of docs/TASKS_move_key_resolution.md), not this loader.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _expected_stem(agent_name: str) -> str:
    """Derive the filename stem a well-formed move file should have for *agent_name*.

    Mirrors the convention already used by all 25 shipped files: drop "&", collapse
    every other run of non-alphanumeric characters to a single underscore, lowercase.
    ("Orphie & Magus" -> "orphie_magus", "Soldier 0 - Anby" -> "soldier_0_anby".)
    """
    stripped = agent_name.replace("&", "")
    return re.sub(r"[^A-Za-z0-9]+", "_", stripped).strip("_").lower()


def _validate_agent_binding(path: Path, spec: AgentMovesSpec) -> None:
    """Reject a loaded file that's missing ``agent_id``/``agent_name`` or whose stem disagrees.

    DB-free by design (see docs/DESIGN_move_key_resolution.md §3 L-A): this only checks
    internal coherence of the file, not whether ``agent_id``/``agent_name`` actually name
    a real agent — that DB-backed check is validate_kits L4. Required-ness is enforced
    here (load time), not on the model itself — see the ``AgentMovesSpec`` docstring.
    """
    if not spec.agent_id:
        raise ValueError(f"{path.name}: missing required 'agent_id'.")
    if not spec.agent_name:
        raise ValueError(f"{path.name}: missing required 'agent_name'.")
    if not _UUID_RE.match(spec.agent_id):
        raise ValueError(
            f"{path.name}: agent_id {spec.agent_id!r} is not a UUID. It must be the real "
            "agents.id for this agent, not a stale hakushin integer id or other decoration."
        )
    expected_stem = _expected_stem(spec.agent_name)
    actual_stem = path.stem.lower()
    if actual_stem != expected_stem:
        raise ValueError(
            f"{path.name}: filename stem {actual_stem!r} disagrees with agent_name "
            f"{spec.agent_name!r} (expected stem {expected_stem!r}). The loader keys "
            "specs by file stem, so a mismatch here means this file silently binds to "
            "the wrong agent (or none)."
        )


def load_agent_moves(
    directory: Path | None = None,
) -> dict[str, AgentMovesSpec]:
    """Load all agent move JSON files from *directory* (defaults to app/data/moves/agents/).

    Returns a dict keyed by lowercase filename stem (e.g. "burnice").
    """
    directory = directory or _DEFAULT_DIR
    result: dict[str, AgentMovesSpec] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            spec = AgentMovesSpec.model_validate(data)
        except Exception as e:
            raise ValueError(f"Failed to parse {path.name}: {e}") from e
        if scope_keyed := sorted(_RESERVED_MOVE_KEYS.intersection(spec.moves)):
            raise ValueError(
                f"{path.name}: move keys {scope_keyed} are attack scopes, not attack names. "
                "Key each move by its full DB attacks.name (e.g. 'Ultimate: Voidstrike') — "
                "scope-keyed entries never match and are silently ignored by the simulator."
            )
        _validate_agent_binding(path, spec)
        result[path.stem.lower()] = spec
    return result
