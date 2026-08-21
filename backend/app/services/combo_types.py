"""Combo step and result type definitions.

All types that represent steps in a combo sequence and their per-step
damage results.  Moved here from combo_evaluator.py (now deleted) so the
type definitions are independent of any evaluation engine.

Step types (discriminated union):
  - :class:`ComboStep` — one standard attack hit (scope, multiplier, element).
  - :class:`AnomalyStep` — one anomaly trigger (type, element, optional
    procs override). v1 treats anomalies as declarative "this rotation
    triggers a Burn/Shock/etc." entries; a future ``BuildupAnomalyStep``
    (computed from per-attack buildup rates and rotation time) can join
    the union without breaking callers.
  - :class:`LuminizeStep` — one Luminize instance, i.e. one stored Voidflare
    fractioned by a Lumiflux agent (Remielle, DESIGN §7.2). Split out from
    ``AnomalyStep`` because two different agents own the two halves of its
    damage chain.
  - :class:`StunTriggerStep` / :class:`StunEndStep` — stun window markers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from app.services.build_damage_service import resolve_build_stats
from app.services.damage_calculator import CritMode, DamageResult  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.anomaly_simulator import SimulationResult
    from app.services.attribution import StepAttribution
    from app.services.build_damage_service import BuildSnapshot
    from app.services.modifiers import ActiveConditions, AttackScope
    from app.services.stat_calculator import TotalStats


@dataclass(frozen=True)
class ComboStep:
    """One standard-attack step in a combo, ready for damage calculation."""

    label: str
    attack_id: str
    attack_name: str
    scope: AttackScope
    multiplier: int  # basis points
    element: str = "physical"
    agent_id: str = "dps"
    # Anomaly gauge this step applies, straight off the ``Attack`` row
    # (``Attack.anomaly_buildup``). Carried so ``simulate_combo_steps`` can build
    # a ``_SyntheticAttack`` that actually accrues gauge — before this existed
    # that path zeroed it, and ``/api/v1/teams/calculate`` reported zero anomaly
    # damage for *every* anomaly agent.
    #
    # Defaults to 0 so callers that build a ``ComboStep`` by hand (tests, the
    # optimizer's event→step mapping, which gets its anomalies as real
    # ``AnomalyStep`` entries instead) behave exactly as before.
    anomaly_buildup: int = 0
    # How much sim clock this one step occupies, when the resolver knows better than
    # the move's authored `duration_s`. Set only on the steps a channel expands to
    # (`tick_s` per tick, the non-held tail on the release) -- `None` everywhere else,
    # so every existing caller keeps `_StepMoveSpec`'s 1.0 default and is unaffected.
    # Without it a 2s spray costs 5s of clock, because the combo path charges 1.0s per
    # emitted step (docs/TASKS_channeled_moves.md Task 10a).
    duration_s: float | None = None
    # True when this instance is dealt while the agent is OFF-FIELD, which
    # today means a Phase Flow tick. The simulator resolves those under the
    # off-field modifier merge, but a ComboStep is otherwise scored with
    # ACTIVE-target buffs applied -- a bounded over-credit (B3). Set here so
    # the scorer can drop those rows for this step alone.
    off_field: bool = False


@dataclass(frozen=True)
class AnomalyStep:
    """One anomaly trigger in a combo.

    ``procs_override`` is **effective proc-equivalents, not a literal proc
    count** — a fractional scale factor on the element's per-proc damage, which
    is linear in proc count. ``None`` keeps the element's default (Burn=20,
    Shock=16, Corruption=20, Shatter=1, Assault=1).

    Three things ride on it, and they compose multiplicatively:

    - a rotation triggering an anomaly partway through its duration, so only
      some of its procs land;
    - Disorder / Vortex, which carry no procs of their own and are expressed as
      ``mv / base_mult`` proc-equivalents of the element they consume;
    - RefringeArea, the Lumiflux anomaly-damage multiplier
      (``optimizer_pipeline._refringe_scale``, Task 35).

    It has been fractional since Disorder landed; any display of it must be
    labelled as effective proc-equivalents rather than a proc count.
    """

    label: str
    attack_id: str
    anomaly_type: str  # "burn" | "shock" | "shatter" | "corruption" | "assault"
    element: str
    procs_override: float | None = None


@dataclass(frozen=True)
class LuminizeStep:
    """One Luminize instance — one stored Voidflare fractioned by Remielle (DESIGN §7.2).

    Not an :class:`AnomalyStep`, and the reason is Task 36's whole design
    (E-8, ``docs/LOG_remielle.md``). Luminize is computed in *Remielle's*
    context but scales off the stats of the *teammate* whose Refringed anomaly
    was captured, so the two agents own different halves of the chain::

        base(ATK, effective_mult) * BoostArea(DMG%) * DEFArea(PEN, def_ignore)
            * AnomalyProfArea(AP) * constant_factor

    ATK / DMG% / PEN / AP belong to the captured teammate and are read live from
    whichever build is being scored. Everything Remielle owns is
    candidate-invariant and rides here as two baked constants — ``def_ignore``
    separately from the rest because DEFArea subtracts it from the scored
    build's PEN rather than multiplying by it.

    ``frozen_damage`` splits the two populations one Voidflare store can hold,
    since the store is keyed by the Lumiflux agent and any teammate can bank
    into it:

    - ``None`` — captured from the build being optimized. Its four live terms
      **must** be recomputed against each candidate. Carrying the simulation's
      own number instead would score it as though that build wore no discs: the
      optimizer simulates a disc-stripped DPS (``_strip_disc_contribution``),
      so the frozen values are zero-disc values.
    - not ``None`` — captured from a support, whose build the optimizer never
      strips and never varies. The simulation's number is exact, so carry it
      verbatim. A constant cannot change ranking, but it keeps the reported
      total honest and is what DESIGN §13.5's total-match bar needs.
    """

    label: str
    attack_id: str
    voidflare_element: str  # RES bucket + which <element>_dmg is read live
    effective_mult_bp: int  # luminize_mult_bp already folded with Remielle's live AP bonus
    def_ignore: int  # Remielle's — mixes with the scored build's PEN inside DEFArea
    constant_factor: float  # RES x Vuln x Stun x Level x AnomalyBoost
    frozen_damage: float | None = None

    # --- P-F2 / hardening Task 15: the Lumiflux agent is herself the optimized DPS.
    #
    # That case inverts the ownership split above. `frozen_damage` is set (the
    # Voidflare was captured from a support, whose build is never stripped, so the
    # teammate half is exact) — but the *Remielle* half baked into it was computed
    # from HER disc-stripped snapshot, and she is the build whose discs are being
    # enumerated. Freezing it scores her own AP discs as worthless on the largest
    # part of her own damage.
    #
    # Her half enters purely multiplicatively, so it does not need recomputing —
    # only rescaling, which stays O(1) per candidate. The scored damage is
    # `frozen_damage`, multiplied by the AP fold re-evaluated at the candidate's
    # live AP (`owner_base_mult_bp` scaled by `10000 + owner_ap_bonus_bp * AP`,
    # over 10000), and divided by `effective_mult_bp` — which is that same fold
    # already evaluated at her stripped AP, and so is exactly what has to come
    # back out. Linear in AP: one registry read and a multiply-add.
    #
    # Both fields are ``None`` unless the optimized DPS is the Lumiflux agent; when
    # they are, `frozen_damage` is the rescale BASE rather than the final answer.
    owner_base_mult_bp: int | None = None  # luminize_mult_bp BEFORE the AP fold
    owner_ap_bonus_bp: int | None = None  # bp of multiplier per point of her AP
    # Her AnomalyBoostArea (10000 + her Attribute-Anomaly-DMG%) as the simulation
    # froze it, i.e. at her disc-stripped build. The SECOND Remielle-owned term
    # baked into `constant_factor`, and the one that hides Feathered Fate's 4pc
    # +15% from the optimizer. Unlike the AP fold this is not per-candidate — her
    # Anomaly DMG% varies only with the disc SET distribution, which the frame
    # already resolves — so the scorer divides it out and re-multiplies by the
    # frame's live value, once per frame rather than once per combination.
    owner_anomaly_boost_mult: int | None = None

    @property
    def is_owner_scaled(self) -> bool:
        """True when this step's Remielle-side terms must vary with the candidate."""
        return self.owner_base_mult_bp is not None and self.owner_ap_bonus_bp is not None


@dataclass(frozen=True)
class StunTriggerStep:
    """Marker — subsequent damage steps are in-stun until a StunEndStep or end of combo."""

    label: str = "Stun"


@dataclass(frozen=True)
class StunEndStep:
    """Marker — subsequent damage steps are NOT in-stun."""

    label: str = "Stun End"


@dataclass(frozen=True)
class RefringeCreditStep:
    """The scored build's attributable share of a TEAMMATE's anomaly tick (#160).

    Not the teammate's damage — the *uplift* that the scored build's Refringe
    Coefficient added to it, which would not exist without her and which scales
    with her Anomaly Proficiency. `_owns` drops the tick itself (her buildup
    share of a teammate's anomaly is 0.0), and before this step type that
    dropped the AP-driven half of her contribution with it.

    Only ever emitted when Refringe actually fired on this aura, i.e. when
    ``refringe_mult_at_stripped_ap`` exceeds the neutral 10000; a neutral tick
    has no uplift to attribute.

    The two coefficient fields are what let the credit be re-evaluated at each
    candidate's AP rather than frozen at the simulation's disc-stripped value:
    ``refringe_coefficient`` is ``ap * ratio_bp + flat_bp`` exactly, with no
    floor division, so the rebuild stays linear (see
    :func:`app.formula.zzz.damage.refringe_credit_node`).
    """

    label: str
    attack_id: str
    # The tick as the simulation computed it — teammate-scaled, and with the
    # simulation's Refringe multiplier already baked in.
    frozen_tick_damage: float
    # That baked-in multiplier, so it can be divided back out. Always > 10000.
    refringe_mult_at_stripped_ap: int
    # bp of coefficient per point of HER Anomaly Proficiency.
    refringe_ap_ratio_bp: int
    # Her already-resolved Condition-gated flat term (core +10% at 3 Anomaly
    # agents, M2 +20%), in bp.
    refringe_flat_bonus_bp: int


@dataclass(frozen=True)
class TeammateDamageStep:
    """Teammate damage the scored build's stats do NOT move (A3).

    One per step list, carrying the summed damage of every event dropped by
    ownership that no credit step claimed. Purely constant: no candidate can
    change it by a point, so it cannot affect ranking — it exists so
    ``total_damage`` can mean *team* damage rather than the target's slice of it.

    Deliberately separate from the credit steps. Those are damage the target's
    stats DO move and therefore belong to its score; this is the remainder, and
    folding the two together would make `target_attributed_damage`
    unrecoverable.
    """

    label: str
    attack_id: str
    frozen_damage: float


@dataclass(frozen=True)
class AbloomStep:
    """One Abloom instance owned by the scored build (#163).

    Abloom was the last damage-carrying event kind scored as zero. It is not a
    ComboStep — it fractions an already-resolved anomaly, so it carries no
    DEF/RES/level areas of its own and must not gain a CritArea (Aria M1's grant
    is a separate bucket, per C2).

    Only ``ap`` is the scored build's; ``original_anomaly_dmg`` belongs to the
    aura's applier and stays frozen. See
    :func:`app.formula.zzz.damage.abloom_rescaled_node`.
    """

    label: str
    attack_id: str
    # The instance as simulated, with the acting agent's disc-stripped AP baked in.
    frozen_abloom_damage: float
    # That AP, so it divides back out. Zero/absent means "not AP-scaled".
    frozen_ap: int
    # False for kits whose text quotes a fixed percentage (Grace, Burnice) — the
    # instance is then a pure constant.
    ap_scaled: bool = True


@dataclass(frozen=True)
class SquadAtkCreditStep:
    """The scored build's share of a teammate's ATK-scaled damage (#160, A4).

    Sibling of :class:`RefringeCreditStep`, for the other stat-driven team buff:
    Remielle's Additional Ability grants the squad flat ATK scaled off HER ATK
    and capped. Damage is linear in ATK, so the grant's contribution has the same
    closed form the Refringe uplift does — see
    :func:`app.formula.zzz.damage.squad_atk_credit_node`.

    One credit per teammate damage EVENT, not one per teammate: the grant reaches
    every instance they deal. Events whose scaling stat is not ATK (Sheer reads
    SheerForce; HP-scaled kits) must not produce one at all.
    """

    label: str
    attack_id: str
    # The teammate's damage as simulated — already including whatever grant the
    # target's disc-stripped build produced.
    frozen_teammate_damage: float
    # That teammate's total ATK at sim time, so the stale grant divides back out.
    teammate_atk_at_sim: int
    # ``((cap, atk_scale_ratio), …)`` for the rows active on this team. Condition
    # gating is resolved before construction, so the node stays a function of ATK.
    grant_rows: tuple[tuple[int, int], ...]


DamageStep = Union[
    "ComboStep",
    "AnomalyStep",
    "LuminizeStep",
    "RefringeCreditStep",
    "SquadAtkCreditStep",
    "AbloomStep",
    "TeammateDamageStep",
]
MarkerStep = Union["StunTriggerStep", "StunEndStep"]
Step = Union[
    "ComboStep",
    "AnomalyStep",
    "LuminizeStep",
    "RefringeCreditStep",
    "SquadAtkCreditStep",
    "AbloomStep",
    "TeammateDamageStep",
    "StunTriggerStep",
    "StunEndStep",
]


@dataclass(frozen=True)
class ComboStepResult:
    """Per-step damage for a standard :class:`ComboStep` (Fribbels-style triad)."""

    label: str
    attack_id: str
    attack_name: str
    scope: AttackScope
    element: str
    multiplier: int
    damage: DamageResult
    damage_no_crit: int
    damage_crit: int
    damage_expected: int
    attribution: StepAttribution | None = None


@dataclass(frozen=True)
class AnomalyStepResult:
    """Per-step damage for an :class:`AnomalyStep`.

    Anomaly damage cannot crit in the base path, so there is no triad.
    ``total = per_proc * procs``.
    """

    label: str
    attack_id: str
    anomaly_type: str
    element: str
    procs: int
    per_proc: int
    total: int
    base_dmg: int = 0
    boost_mult: int = 0
    def_mult: int = 0
    res_mult: int = 0
    vulnerability_mult: int = 0
    stun_mult: int = 0
    anomaly_prof_mult: int = 0
    level_mult: int = 0
    anomaly_boost_mult: int = 0
    level_factor_val: int = 0
    effective_enemy_def: int = 0
    stun_base_mult: int = 0
    attribution: StepAttribution | None = None


@dataclass(frozen=True)
class MarkerStepResult:
    """Placeholder result for a marker step — zero damage, step_type discriminator."""

    label: str
    step_type: str  # "stun_trigger" | "stun_end"
    total: int = 0


StepResult = Union["ComboStepResult", "AnomalyStepResult", "MarkerStepResult"]


@dataclass(frozen=True)
class CategoryBreakdown:
    """Aggregate damage for one attack-type or anomaly-type category."""

    category: str
    total: int
    pct: float


@dataclass(frozen=True)
class ElementBreakdown:
    """Aggregate damage for one element."""

    element: str
    total: int
    pct: float


@dataclass(frozen=True)
class ComboEvaluationResult:
    """Aggregate combo result with per-step + breakdown views."""

    steps: list[StepResult]
    total_damage: int
    standard_total: int
    anomaly_total: int
    by_category: list[CategoryBreakdown]
    by_element: list[ElementBreakdown]
    stats: TotalStats | None


def _step_category(s: ComboStepResult | AnomalyStepResult) -> str:
    if isinstance(s, AnomalyStepResult):
        return s.anomaly_type
    return s.scope.value


def _step_total(s: StepResult) -> int:
    if isinstance(s, MarkerStepResult):
        return 0
    if isinstance(s, AnomalyStepResult):
        return s.total
    return s.damage.total


def _aggregate_category(
    steps: list[StepResult],
    *,
    total: int,
) -> list[CategoryBreakdown]:
    damage_steps = [s for s in steps if not isinstance(s, MarkerStepResult)]
    return _aggregate(damage_steps, key=_step_category, total=total)


def _aggregate(
    steps: list[ComboStepResult | AnomalyStepResult],
    *,
    key: Callable[[ComboStepResult | AnomalyStepResult], str],
    total: int,
) -> list[CategoryBreakdown]:
    sums: dict[str, int] = defaultdict(int)
    for s in steps:
        sums[key(s)] += _step_total(s)
    return [
        CategoryBreakdown(
            category=cat,
            total=val,
            pct=round(val / total * 100, 2) if total > 0 else 0.0,
        )
        for cat, val in sorted(sums.items(), key=lambda kv: -kv[1])
    ]


def _aggregate_elements(
    steps: list[StepResult],
    *,
    total: int,
) -> list[ElementBreakdown]:
    sums: dict[str, int] = defaultdict(int)
    for s in steps:
        if isinstance(s, MarkerStepResult):
            continue
        sums[s.element] += _step_total(s)
    return [
        ElementBreakdown(
            element=elem,
            total=val,
            pct=round(val / total * 100, 2) if total > 0 else 0.0,
        )
        for elem, val in sorted(sums.items(), key=lambda kv: -kv[1])
    ]


# Event kinds that carry anomaly-family damage, mapped to the label prefix used
# for their step results. `anomaly` itself is the *application* event and always
# carries `damage=None` — the damage arrives as `anomaly_tick`.
_ANOMALY_DAMAGE_KINDS: dict[str, str] = {
    "anomaly_tick": "Anomaly",
    "disorder": "Disorder",
    "vortex": "Vortex",
    "abloom": "Abloom",
}


def sim_result_to_combo_evaluation(
    sim_result: SimulationResult,
    combo_steps: list[Step],
    build_snap: BuildSnapshot,
    conditions: ActiveConditions,
) -> ComboEvaluationResult:
    """Adapt a SimulationResult to ComboEvaluationResult shape.

    Maps hit/marker events back to their originating ComboStep by sequence
    position preserving the original step ordering and labels.

    Crit triad: no_crit and crit are derived from the EXPECTED total using
    crit_mult (from hit detail) and stats.crit_dmg.
    """
    stats = resolve_build_stats(build_snap, conditions)
    crit_dmg_bp: int = stats.crit_dmg if stats else 5000

    sorted_events = sorted(
        sim_result.events,
        key=lambda e: (
            e.t,
            {
                "hit": 0,
                "abloom": 2,
                "anomaly": 3,
                "disorder": 4,
                "vortex": 5,
                "refresh": 6,
                "anomaly_tick": 7,
                "expire": 8,
            }.get(e.kind, 9),
        ),
    )

    hit_events = [e for e in sorted_events if e.kind == "hit"]

    hit_ptr = 0
    step_results: list[StepResult] = []
    standard_total = 0

    for step in combo_steps:
        if isinstance(step, StunTriggerStep):
            step_results.append(MarkerStepResult(label=step.label, step_type="stun_trigger"))
        elif isinstance(step, StunEndStep):
            step_results.append(MarkerStepResult(label=step.label, step_type="stun_end"))
        else:  # ComboStep
            if hit_ptr >= len(hit_events):
                continue
            ev = hit_events[hit_ptr]
            hit_ptr += 1
            det = ev.detail or {}
            total = ev.damage or 0
            crit_mult = det.get("crit_mult", 10000)
            no_crit = total * 10000 // crit_mult if crit_mult else total
            crit = no_crit * (10000 + crit_dmg_bp) // 10000
            dmg = DamageResult(
                total=total,
                base_dmg=det.get("base_dmg", 0),
                boost_mult=det.get("boost_mult", 10000),
                crit_mult=crit_mult,
                def_mult=det.get("def_mult", 10000),
                res_mult=det.get("res_mult", 10000),
                vulnerability_mult=det.get("vulnerability_mult", 10000),
                stun_mult=det.get("stun_mult", 10000),
                effective_atk=det.get("effective_atk", 0),
                level_factor_val=det.get("level_factor", 0),
                effective_enemy_def=det.get("effective_enemy_def", 0),
                stun_base_mult=det.get("stun_base_mult", 0),
                is_sheer="sheer_force" in det,
            )
            step_results.append(
                ComboStepResult(
                    label=step.label,
                    attack_id=step.attack_id,
                    attack_name=step.attack_name,
                    scope=step.scope,
                    element=step.element,
                    multiplier=step.multiplier,
                    damage=dmg,
                    damage_no_crit=no_crit,
                    damage_crit=crit,
                    damage_expected=total,
                    attribution=ev.attribution,
                )
            )
            standard_total += total

    # Anomaly results are appended after the standard steps rather than
    # interleaved: they have no originating `ComboStep` to sit beside. An
    # anomaly fires when the gauge fills, which is a consequence of several
    # earlier steps' buildup, not of the step it happens to land on — the
    # simulator's own timeline (`sim_result.events`) is the ordered view, and
    # each result keeps its `t`-ordered position within this tail.
    #
    # `anomaly_total` was hardcoded to 0 here and documented as "always 0 in v1"
    # on the schema. That was a real scoping decision, and it is deliberately
    # being broken: every anomaly agent's team-combo evaluation understated its
    # total by its entire anomaly half.
    anomaly_total = 0
    for ev in sorted_events:
        if ev.kind not in _ANOMALY_DAMAGE_KINDS:
            continue
        dmg = ev.damage or 0
        if not dmg:
            continue
        det = ev.detail or {}
        element = ev.element or ev.aura_type or "physical"
        step_results.append(
            AnomalyStepResult(
                label=f"{_ANOMALY_DAMAGE_KINDS[ev.kind]} ({element})",
                attack_id=f"{ev.kind}_{element}_{ev.t}",
                anomaly_type=det.get("anomaly_type") or ev.kind,
                element=element,
                procs=1,
                per_proc=dmg,
                total=dmg,
                base_dmg=det.get("base_dmg", 0),
                boost_mult=det.get("boost_mult", 0),
                def_mult=det.get("def_mult", 0),
                res_mult=det.get("res_mult", 0),
                vulnerability_mult=det.get("vulnerability_mult", 0),
                stun_mult=det.get("stun_mult", 0),
                anomaly_prof_mult=det.get("anomaly_proficiency_mult", 0),
                level_mult=det.get("anomaly_level_mult", 0),
                anomaly_boost_mult=det.get("anomaly_dmg_bonus_mult", 0),
                level_factor_val=det.get("level_factor", 0),
                effective_enemy_def=det.get("effective_enemy_def", 0),
                stun_base_mult=det.get("stun_base_mult", 0),
            )
        )
        anomaly_total += dmg

    total_damage = standard_total + anomaly_total
    by_category = _aggregate_category(step_results, total=total_damage)
    by_element = _aggregate_elements(step_results, total=total_damage)

    return ComboEvaluationResult(
        steps=step_results,
        total_damage=total_damage,
        standard_total=standard_total,
        anomaly_total=anomaly_total,
        by_category=by_category,
        by_element=by_element,
        stats=stats,
    )
