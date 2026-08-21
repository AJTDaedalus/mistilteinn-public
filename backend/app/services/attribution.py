"""Per-step damage attribution — "where did this number come from?".

Aggregates :class:`Contribution` rows from buff resolution + disc / agent
base / W-Engine sources into a single :class:`StepAttribution` value
object that the API surfaces to the UI for hover-style breakdowns.

The damage calculator and stat aggregator already produce the raw
totals; this module duplicates the same arithmetic but keeps every
contributing row labelled. Two paths so the calc isn't slowed down by
attribution bookkeeping it doesn't need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import TYPE_CHECKING

from app.services.buff_resolver import Contribution

if TYPE_CHECKING:
    from app.services.buff_resolver import ResolvedBuffs
    from app.services.build_damage_service import BuildSnapshot
    from app.services.damage_calculator import (
        AnomalyResult,
        DamageResult,
        DisorderResult,
        SheerDamageResult,
    )
    from app.services.stat_calculator import DiscStats, TotalStats


@dataclass(frozen=True)
class ZoneAttribution:
    """All sources contributing to one calculation zone (additive sum)."""

    contributions: list[Contribution] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Sum of contributions; must equal the calculator's matching raw value."""
        return sum(c.value for c in self.contributions)


@dataclass(frozen=True)
class ZoneFormula:
    """A zone's derivation formula: template name + substituted operands.

    Purely presentational — every value here is read off (or losslessly
    recomputed from) values the calculator already produced; this never
    reintroduces a second arithmetic path (BRIEF_explainability.md).

    ``pre_clamp_bp`` is populated only when a clamp/floor actually changed
    the zone's result (i.e. differs from ``result_bp``) — this is how the
    UI knows to show "capped from X" instead of always showing a clamp note.
    """

    template: str
    terms: dict[str, int]
    result_bp: int
    pre_clamp_bp: int | None = None


@dataclass(frozen=True)
class StepAttribution:
    """Provenance for one combo step's damage computation.

    Each field is a :class:`ZoneAttribution` listing the named sources
    that fed that zone. ``boost_bonuses`` covers the BoostArea (DMG%
    sources). ``crit_rate`` / ``crit_dmg`` cover CritArea inputs. The
    rest mirror the damage calculator's argument list. The UI walks
    these lists to render hoverable per-zone breakdowns.

    For Sheer Damage (Rupture agents), ``sheer_boost_bonuses`` is the
    SheerBoostArea (sheer_dmg_bonus pool). ``def_ignore``, ``pen_ratio``,
    and ``pen_flat`` are empty zones for Sheer — they have no effect.
    """

    atk_components: ZoneAttribution
    atk_pct_components: ZoneAttribution
    crit_rate: ZoneAttribution
    crit_dmg: ZoneAttribution
    boost_bonuses: ZoneAttribution
    pen_ratio: ZoneAttribution
    pen_flat: ZoneAttribution
    res_reduction: ZoneAttribution
    res_ignore: ZoneAttribution
    def_ignore: ZoneAttribution
    vulnerability: ZoneAttribution
    stun_bonuses: ZoneAttribution
    sheer_boost_bonuses: ZoneAttribution = field(default_factory=ZoneAttribution)
    # Components of the SheerForce scaling stat (ATK×30%, HP×N%, flat sources).
    # Non-empty only for Sheer steps (build_step_attribution called with is_sheer=True).
    sheer_force_components: ZoneAttribution = field(default_factory=ZoneAttribution)
    # Per-zone derivation formulas (DESIGN_explainability.md §2.1). Keyed by
    # zone name ("base", "boost", "crit", "def", "res", "vulnerability",
    # "stun", and — path-dependent — "anomaly_prof"/"anomaly_level"/
    # "anomaly_boost" (+ "disorder_boost" for disorder steps) or
    # "sheer_force"/"sheer_boost"). Empty unless the caller passed a
    # ``damage`` result to :func:`build_step_attribution`.
    zone_formulas: dict[str, ZoneFormula] = field(default_factory=dict)


_SHEER_ATK_RATIO = 3000  # 30% — mirrors SHEER_ATK_RATIO in build_damage_service


def build_step_attribution(  # noqa: PLR0912, PLR0915
    build: BuildSnapshot,
    stats: TotalStats,
    disc: DiscStats,
    buffs: ResolvedBuffs,
    *,
    is_sheer: bool = False,
    is_anomaly: bool = False,
    damage: DamageResult | AnomalyResult | SheerDamageResult | DisorderResult | None = None,
    multiplier: int = 0,
    enemy_res: int = 0,
) -> StepAttribution:
    """Compose a :class:`StepAttribution` from the inputs that made one step.

    ``stats`` is the post-aggregation :class:`TotalStats`; ``disc`` is the
    raw accumulation from disc main + substats; ``buffs`` is the resolved
    modifier output. The agent-base contribution is taken from the
    snapshot. Element-specific DMG bonus is folded into ``boost_bonuses``
    via the buffs' attribution + the disc's elemental_dmg main/substat.

    When ``damage`` (the calculator's own result for this step) is passed,
    also assembles ``zone_formulas`` — per-zone derivation metadata for the
    "Details" full-equation view. ``multiplier`` is the effective attack MV
    used for ``BaseDMG``; ``enemy_res`` is the enemy's raw elemental RES.
    Omit ``damage`` (the default) to skip formula assembly entirely — e.g.
    disorder/vortex callers that don't yet need it.
    """
    owner = getattr(build, "agent_name", None)

    def _base(source: str, value: int) -> Contribution:
        return Contribution(
            source=source,
            value=value,
            source_category="base",
            owner_agent_name=owner,
        )

    def _discs(source: str, value: int) -> Contribution:
        return Contribution(
            source=source,
            value=value,
            source_category="discs",
            owner_agent_name=owner,
        )

    atk_components = [_base("Agent base ATK", build.agent_base_atk)]
    if build.wengine_base_atk:
        atk_components.append(_base("W-Engine base ATK", build.wengine_base_atk))
    if disc.flat_atk:
        atk_components.append(_discs("Discs (flat ATK)", disc.flat_atk))
    atk_components.extend(buffs.stat_attributions.get("flat_atk", []))
    atk_components.extend(buffs.stat_attributions.get("final_flat_atk", []))

    atk_pct_components: list[Contribution] = []
    if disc.atk_pct:
        atk_pct_components.append(_discs("Discs (ATK%)", disc.atk_pct))
    atk_pct_components.extend(buffs.stat_attributions.get("atk_pct", []))
    atk_pct_components.extend(buffs.stat_attributions.get("final_atk_pct", []))

    crit_rate = [_base("Agent base", build.agent_crit_rate)]
    if disc.crit_rate:
        crit_rate.append(_discs("Discs", disc.crit_rate))
    crit_rate.extend(buffs.stat_attributions.get("crit_rate", []))

    crit_dmg = [_base("Agent base", build.agent_crit_dmg)]
    if disc.crit_dmg:
        crit_dmg.append(_discs("Discs", disc.crit_dmg))
    crit_dmg.extend(buffs.stat_attributions.get("crit_dmg", []))

    boost_bonuses = list(buffs.dmg_bonus_attributions)
    elem_from_disc = getattr(disc, f"{build.agent_element}_dmg", 0) if build.agent_element else 0
    if elem_from_disc:
        boost_bonuses.append(
            _discs(
                f"Discs ({build.agent_element} DMG)",
                elem_from_disc,
            )
        )
    if build.agent_element:
        # Reuse the buff-side contributions verbatim so the source labels
        # carry through exactly as authored in the modifier JSONs.
        boost_bonuses.extend(
            buffs.stat_attributions.get(f"{build.agent_element}_dmg", []),
        )
    # SheerForce breakdown (Rupture agents only — populated when is_sheer=True).
    sheer_force_components: list[Contribution] = []
    if is_sheer:
        atk_sf = floor(stats.atk * _SHEER_ATK_RATIO / 10000)
        sheer_force_components.append(_base("ATK x 30%", atk_sf))
        hp_ratio = getattr(build, "agent_sheer_force_hp_ratio", 0)
        if hp_ratio:
            pct = hp_ratio // 100
            hp_sf = floor(stats.hp * hp_ratio / 10000)
            sheer_force_components.append(
                Contribution(
                    source=f"HP x {pct}%",
                    value=hp_sf,
                    source_category="agent",
                    owner_agent_name=owner,
                )
            )
        sheer_force_components.extend(buffs.combat_attributions.get("sheer_force_flat", []))

    pen_ratio = []
    if build.agent_pen_ratio:
        pen_ratio.append(_base("Agent base", build.agent_pen_ratio))
    if disc.pen_ratio:
        pen_ratio.append(_discs("Discs", disc.pen_ratio))
    pen_ratio.extend(buffs.stat_attributions.get("pen_ratio", []))

    pen_flat = []
    if build.agent_pen_flat:
        pen_flat.append(_base("Agent base", build.agent_pen_flat))
    if disc.pen_flat:
        pen_flat.append(_discs("Discs", disc.pen_flat))
    pen_flat.extend(buffs.stat_attributions.get("pen_flat", []))

    return StepAttribution(
        atk_components=ZoneAttribution(atk_components),
        atk_pct_components=ZoneAttribution(atk_pct_components),
        crit_rate=ZoneAttribution(crit_rate),
        crit_dmg=ZoneAttribution(crit_dmg),
        boost_bonuses=ZoneAttribution(boost_bonuses),
        pen_ratio=ZoneAttribution(pen_ratio),
        pen_flat=ZoneAttribution(pen_flat),
        res_reduction=ZoneAttribution(
            list(buffs.combat_attributions.get("res_reduction", [])),
        ),
        res_ignore=ZoneAttribution(
            list(buffs.combat_attributions.get("res_ignore", [])),
        ),
        def_ignore=ZoneAttribution(
            list(buffs.combat_attributions.get("def_ignore", [])),
        ),
        vulnerability=ZoneAttribution(
            list(buffs.combat_attributions.get("vulnerability", [])),
        ),
        stun_bonuses=ZoneAttribution(
            list(buffs.combat_attributions.get("stun_dmg_mult_bonus", [])),
        ),
        sheer_boost_bonuses=ZoneAttribution(
            list(buffs.combat_attributions.get("sheer_dmg_bonus", [])),
        ),
        sheer_force_components=ZoneAttribution(sheer_force_components),
        zone_formulas=(
            _build_zone_formulas(
                build,
                stats,
                buffs,
                damage,
                is_sheer=is_sheer,
                is_anomaly=is_anomaly,
                multiplier=multiplier,
                enemy_res=enemy_res,
            )
            if damage is not None
            else {}
        ),
    )


def _pre_clamp(raw: int, result: int) -> int | None:
    """Return ``raw`` iff a clamp/floor actually moved it away from ``result``."""
    return raw if raw != result else None


def _build_zone_formulas(
    build: BuildSnapshot,
    stats: TotalStats,
    buffs: ResolvedBuffs,
    damage: DamageResult | AnomalyResult | SheerDamageResult | DisorderResult,
    *,
    is_sheer: bool,
    is_anomaly: bool,
    multiplier: int,
    enemy_res: int,
) -> dict[str, ZoneFormula]:
    """Assemble per-zone derivation formulas from an already-computed result.

    Every value here is either read directly off ``damage`` (the calculator's
    own multipliers) or losslessly recomputed from ``stats``/``buffs`` inputs
    that are never themselves clamped — e.g. the RES pre-clamp value is
    ``10000 - enemy_res + res_reduction + res_ignore``, the same sum
    :func:`res_multiplier` computes before applying its clamp. The one
    exception is DEF: the pre-floor effective DEF is genuinely lost once
    ``max(0, ...)`` bites, so the calculator exposes it directly as
    ``effective_enemy_def_pre_floor``.
    """
    # NOTE: the ``raw_*``/``*_raw`` locals below (raw_crit_mult, raw_def_mult,
    # res_raw, stun_raw) re-derive each zone's *pre-clamp* value purely to
    # drive the "capped from X" annotation via ``_pre_clamp``. The clamped
    # ``result_bp`` always comes straight off ``damage`` (the calculator's own
    # output), so a drift here only mis-labels the clamp note, never the
    # number. If a clamp/floor formula changes in
    # ``damage_calculator.py`` (crit_multiplier / def_multiplier /
    # res_multiplier / stun handling), update the matching recomputation here
    # in lockstep. The attribution-invariant suite covers result_bp, not these
    # pre-clamp derivations.
    formulas: dict[str, ZoneFormula] = {}

    if is_sheer:
        scaling_stat = damage.sheer_force
    elif is_anomaly:
        scaling_stat = stats.atk
    else:
        scaling_stat = damage.effective_atk
    formulas["base"] = ZoneFormula(
        template="base_mv_scaling",
        terms={"multiplier_bp": multiplier, "scaling_stat": scaling_stat},
        result_bp=damage.base_dmg,
    )

    formulas["boost"] = ZoneFormula(
        template="boost_sum_dmg_pct",
        terms={"sum_dmg_pct_bp": damage.boost_mult - 10000},
        result_bp=damage.boost_mult,
    )

    if not is_anomaly:
        raw_crit_mult = 10000 + stats.crit_rate * stats.crit_dmg // 10000
        formulas["crit"] = ZoneFormula(
            template="crit_rate_times_dmg",
            terms={"crit_rate_bp": stats.crit_rate, "crit_dmg_bp": stats.crit_dmg},
            result_bp=damage.crit_mult,
            pre_clamp_bp=_pre_clamp(raw_crit_mult, damage.crit_mult),
        )

    if not is_sheer:
        atk_factor = damage.level_factor_val
        pre_floor_def = damage.effective_enemy_def_pre_floor
        denom = pre_floor_def + atk_factor
        raw_def_mult = 10000 if denom == 0 else atk_factor * 10000 // denom
        formulas["def"] = ZoneFormula(
            template="def_area",
            terms={
                "level_factor_bp": atk_factor,
                "effective_enemy_def": damage.effective_enemy_def,
                "pen_ratio_bp": stats.pen_ratio,
                "pen_flat": stats.pen_flat,
                "def_ignore_bp": buffs.def_ignore,
            },
            result_bp=damage.def_mult,
            pre_clamp_bp=_pre_clamp(raw_def_mult, damage.def_mult),
        )

    res_raw = 10000 - enemy_res + buffs.res_reduction + buffs.res_ignore
    formulas["res"] = ZoneFormula(
        template="res_area",
        terms={
            "enemy_res_bp": enemy_res,
            "res_reduction_bp": buffs.res_reduction,
            "res_ignore_bp": buffs.res_ignore,
        },
        result_bp=damage.res_mult,
        pre_clamp_bp=_pre_clamp(res_raw, damage.res_mult),
    )

    formulas["vulnerability"] = ZoneFormula(
        template="vuln_sum",
        terms={"sum_vuln_bp": damage.vulnerability_mult - 10000},
        result_bp=damage.vulnerability_mult,
    )

    stun_override = buffs.stun_area_override
    stun_raw = (
        10000 + stun_override
        if stun_override > 0
        else (damage.stun_base_mult if damage.stun_base_mult else 10000)
    )
    formulas["stun"] = ZoneFormula(
        template="stun_area",
        terms={"stun_base_mult_bp": damage.stun_base_mult, "stun_area_override_bp": stun_override},
        result_bp=damage.stun_mult,
        pre_clamp_bp=_pre_clamp(stun_raw, damage.stun_mult),
    )

    # DirectDmgArea (F-11/F-23b, Windswept infusion) — separate multiplicative
    # zone, only ever present on standard (non-anomaly) hits; omitted when
    # neutral so unaffected hits don't show a no-op zone.
    direct_mult = getattr(damage, "direct_mult", None)
    if not is_anomaly and direct_mult is not None and direct_mult != 10000:  # noqa: PLR2004
        formulas["direct"] = ZoneFormula(
            template="direct_dmg_sum",
            terms={"sum_direct_dmg_pct_bp": direct_mult - 10000},
            result_bp=direct_mult,
        )

    if is_anomaly:
        # RefringeArea (Remielle, DESIGN_remielle.md §7.1) — separate
        # multiplicative zone, not folded into anomaly_dmg_bonus; omitted
        # when neutral so hits with no consumed Lumiflux point don't show a
        # no-op zone (same convention as DirectDmgArea above).
        refringe_mult = getattr(damage, "refringe_mult", None)
        if refringe_mult is not None and refringe_mult != 10000:  # noqa: PLR2004
            formulas["refringe"] = ZoneFormula(
                template="refringe_coefficient",
                terms={"refringe_coefficient_bp": refringe_mult - 10000},
                result_bp=refringe_mult,
            )

        anom_prof_raw = stats.anomaly_proficiency * 100
        formulas["anomaly_prof"] = ZoneFormula(
            template="anomaly_prof_area",
            terms={"anomaly_proficiency": stats.anomaly_proficiency},
            result_bp=damage.anomaly_prof_mult,
            pre_clamp_bp=_pre_clamp(anom_prof_raw, damage.anomaly_prof_mult),
        )
        formulas["anomaly_level"] = ZoneFormula(
            template="anomaly_level_area",
            terms={"level": build.agent_level},
            result_bp=damage.level_mult,
        )
        formulas["anomaly_boost"] = ZoneFormula(
            template="anomaly_boost_sum",
            terms={"sum_anomaly_dmg_pct_bp": damage.anomaly_boost_mult - 10000},
            result_bp=damage.anomaly_boost_mult,
        )
        # Disorder is "just another anomaly hit" plus one extra multiplicative
        # zone (DisorderBoostArea) — only DisorderResult has this field.
        disorder_boost_mult = getattr(damage, "disorder_boost_mult", None)
        if disorder_boost_mult is not None:
            formulas["disorder_boost"] = ZoneFormula(
                template="disorder_boost_sum",
                terms={"sum_disorder_dmg_pct_bp": disorder_boost_mult - 10000},
                result_bp=disorder_boost_mult,
            )

    if is_sheer:
        formulas["sheer_force"] = ZoneFormula(
            template="sheer_force_components",
            terms={
                "atk_pct_bp": _SHEER_ATK_RATIO,
                "hp_pct_bp": getattr(build, "agent_sheer_force_hp_ratio", 0),
                "flat": buffs.sheer_force_flat,
            },
            result_bp=damage.sheer_force,
        )
        formulas["sheer_boost"] = ZoneFormula(
            template="sheer_boost_sum",
            terms={"sum_sheer_dmg_pct_bp": damage.sheer_boost_mult - 10000},
            result_bp=damage.sheer_boost_mult,
        )

    return formulas
