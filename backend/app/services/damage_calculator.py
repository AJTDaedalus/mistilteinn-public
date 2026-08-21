"""Damage calculation engine — 7 multiplier zones for standard and anomaly damage.

All percentage values in basis points (10000 = 100%) unless noted otherwise.
Pure functions with no side effects — easy to test and compose.

Reference:
- ZZZ-Plugin Calculator.js (production-tested implementation)
- Thereallo1026's damage guide
- Community calc sheets
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import floor


class CritMode(Enum):
    """How to factor crit into the damage calculation."""

    EXPECTED = "expected"  # Average: 1 + rate * dmg
    CRIT = "crit"  # Always crit: 1 + dmg
    NO_CRIT = "no_crit"  # Never crit: 1.0


class AnomalyType(Enum):
    """Anomaly types with their base multipliers and proc counts."""

    BURN = "burn"
    SHOCK = "shock"
    CORRUPTION = "corruption"
    SHATTER = "shatter"
    ASSAULT = "assault"
    WINDSWEPT = "windswept"


# Base anomaly multipliers (basis points of ATK) and default proc counts per 10s.
# Proc counts are CAPS over the anomaly's duration, not guarantees — Shock and
# Corruption are on-hit anomalies gated by attack cadence (1s / 0.5s internal
# CD; see RESEARCH_math_review.md F-02b), so a build without enough attacks in
# the window procs fewer times than this max. Burn ticks unconditionally.
ANOMALY_BASE: dict[AnomalyType, tuple[int, int]] = {
    AnomalyType.BURN: (5000, 20),  # 50% ATK, 20 procs/10s (unconditional 0.5s tick)
    AnomalyType.SHOCK: (12500, 10),  # 125% ATK, max 10 procs/10s (on-hit, 1s CD)
    AnomalyType.CORRUPTION: (6250, 20),  # 62.5% ATK, max 20 procs/10s (on-hit, 0.5s CD)
    AnomalyType.SHATTER: (50000, 1),  # 500% ATK, 1 proc
    AnomalyType.ASSAULT: (71300, 1),  # 713% ATK, 1 proc
    AnomalyType.WINDSWEPT: (125000, 1),  # 1250% ATK, 1 proc
}


@dataclass(frozen=True)
class DamageResult:
    """Result of a single damage calculation."""

    total: int
    base_dmg: int
    boost_mult: int  # basis points (10000 = 1.0*)
    crit_mult: int  # basis points
    def_mult: int  # basis points
    res_mult: int  # basis points
    vulnerability_mult: int  # basis points
    stun_mult: int  # basis points
    effective_atk: int = 0  # resolved ATK used as scaling stat; holds SheerForce for Sheer hits
    # DEF formula intermediates (for formula-card display; 0 when not computed)
    level_factor_val: int = 0  # attacker's level factor (LF)
    effective_enemy_def: int = 0  # enemy DEF after PEN%, DEF Ignore, PEN Flat
    # effective_enemy_def before the max(0, ...) floor — differs from
    # effective_enemy_def only when the floor actually bit (e.g. huge PEN Flat).
    effective_enemy_def_pre_floor: int = 0
    # Stun formula intermediates (0 when not stunned)
    stun_base_mult: int = 0  # raw stun_dmg_mult when stunned, else 0
    # Sheer Damage flag — True when this result was computed via the Sheer path.
    # When True: def_mult=10000 (no DEF zone), effective_atk holds SheerForce.
    is_sheer: bool = False
    # DirectDmgArea (F-11/F-23b, Windswept infusion) — separate multiplicative
    # zone from BoostArea, does NOT combine with dmg_bonus. Neutral (10000)
    # unless a caller passes direct_dmg_bonus.
    direct_mult: int = 10000


@dataclass(frozen=True)
class AnomalyResult:
    """Result of an anomaly damage calculation."""

    per_proc: int
    total: int  # per_proc * procs
    procs: int
    base_dmg: int
    boost_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int
    anomaly_prof_mult: int  # basis points
    level_mult: int  # basis points
    anomaly_boost_mult: int  # basis points
    # DEF formula intermediates (for formula-card display; 0 when not computed)
    level_factor_val: int = 0
    effective_enemy_def: int = 0
    effective_enemy_def_pre_floor: int = 0
    # Stun formula intermediates
    stun_base_mult: int = 0
    # AnomalyCritArea (issue #162) — anomaly damage does NOT crit by default, so
    # this is 10000 (neutral) for every anomaly in the game except where a kit
    # explicitly grants it. Jane's core passive is the first such grant. Fed by
    # the `anomaly_crit_rate` / `anomaly_crit_dmg` combat-bonus pool, which is
    # SEPARATE from the standard `crit_rate` / `crit_dmg` stats — disc CRIT does
    # not reach anomaly damage. Matches ZO's `anom_crit_` / `anom_crit_dmg_`
    # buckets and its `anomaly_crit_mult_` zone.
    anomaly_crit_mult: int = 10000
    # Refringe Coefficient (Remielle, guide line 68-71) — its own multiplicative
    # zone, not folded into anomaly_dmg_bonus, because it must be frozen onto
    # active_aura at trigger time for Disorder/Abloom/Vortex inheritance
    # (DESIGN_remielle.md §7.1). Neutral (10000) unless a Lumiflux point was
    # consumed on this trigger.
    refringe_mult: int = 10000
    # Luminize only (0 everywhere else): `luminize_mult_bp` already folded with
    # Remielle's live AP bonus. Returned rather than discarded so the optimizer's
    # event→step mapping can carry it without duplicating the fold formula
    # (Task 36 / E-8, docs/LOG_remielle.md).
    effective_mult_bp: int = 0


# ---------------------------------------------------------------------------
# Individual multiplier zone functions
# ---------------------------------------------------------------------------


def base_damage(scaling_stat: int, multiplier: int) -> int:
    """Zone 1: Base damage.

    Args:
        scaling_stat: The stat value the attack scales off (usually ATK).
        multiplier: Attack multiplier in basis points (e.g. 3120 = 31.20%).

    Returns:
        Base damage as an integer (floored).
    """
    return floor(scaling_stat * multiplier / 10000)


def dmg_bonus_multiplier(bonuses: list[int]) -> int:
    """Zone 2: Damage bonus (boost area).

    Sum all applicable damage bonuses and add to base 10000.

    Args:
        bonuses: List of damage bonus values in basis points.
                 Includes elemental DMG%, generic DMG%, skill-type DMG%, etc.

    Returns:
        Multiplier in basis points (10000 = 1.0*, 13000 = 1.3*).
    """
    return 10000 + sum(bonuses)


def crit_multiplier(crit_rate: int, crit_dmg: int, mode: CritMode = CritMode.EXPECTED) -> int:
    """Zone 3: Crit area.

    Args:
        crit_rate: Crit rate in basis points (e.g. 5000 = 50%). Clamped to [0, 10000].
        crit_dmg: Crit damage in basis points (e.g. 10000 = 100%).
        mode: How to calculate crit contribution.

    Returns:
        Multiplier in basis points.
    """
    if mode == CritMode.NO_CRIT:
        return 10000

    if mode == CritMode.CRIT:
        return 10000 + crit_dmg

    # Expected value: 1 + clamp(rate, 0, 1) * crit_dmg
    effective_rate = max(0, min(10000, crit_rate))
    return 10000 + effective_rate * crit_dmg // 10000


def level_factor(level: int) -> int:
    """DEF level factor from the game's level curve.

    Formula: floor(0.1551 * min(60, level)² + 3.141 * min(60, level) + 47.2039)
    Level 60 -> 794.

    Args:
        level: Character or enemy level (capped at 60 for this formula).

    Returns:
        Level factor as integer.
    """
    capped = min(60, max(1, level))
    return floor(0.1551 * capped * capped + 3.141 * capped + 47.2039)


def def_multiplier(
    attacker_level: int,
    enemy_base_def: int,
    enemy_level: int,
    *,
    pen_ratio: int = 0,
    pen_flat: int = 0,
    def_ignore: int = 0,
) -> int:
    """Zone 4: DEF area.

    Args:
        attacker_level: Attacker's level.
        enemy_base_def: Enemy's base DEF stat (raw value, not basis points).
        enemy_level: Enemy's level.
        pen_ratio: PEN Ratio in basis points (e.g. 2000 = 20%).
        pen_flat: Flat PEN value.
        def_ignore: DEF ignore in basis points (from certain abilities).

    Returns:
        Multiplier in basis points (0-10000).
    """
    atk_factor = level_factor(attacker_level)
    enemy_factor = level_factor(enemy_level)

    # Enemy DEF = (base_def / 50) * level_factor(enemy_level)
    enemy_def = enemy_base_def * enemy_factor // 50

    # Apply DEF shred: ignore first, then pen ratio, then subtract flat
    effective_def = enemy_def * (10000 - def_ignore) // 10000
    effective_def = effective_def * (10000 - pen_ratio) // 10000
    effective_def = max(0, effective_def - pen_flat)

    # DEF multiplier = atk_factor / (effective_def + atk_factor)
    if effective_def + atk_factor == 0:
        return 10000
    return atk_factor * 10000 // (effective_def + atk_factor)


def res_multiplier(
    enemy_res: int,
    *,
    res_reduction: int = 0,
    res_ignore: int = 0,
) -> int:
    """Zone 5: RES area.

    Args:
        enemy_res: Enemy elemental resistance in basis points (e.g. -2000 = -20% weakness).
        res_reduction: RES reduction/shred in basis points.
        res_ignore: RES ignore in basis points.

    Returns:
        Multiplier in basis points, clamped to [0, 20000] (0* to 2.0*).
    """
    # RES area = 1 - enemy_res + res_reduction + res_ignore
    raw = 10000 - enemy_res + res_reduction + res_ignore
    return max(0, min(20000, raw))


def dmg_taken_multiplier(vulnerability_bonuses: list[int]) -> int:
    """Zone 6: Vulnerability / damage taken area.

    Args:
        vulnerability_bonuses: List of "damage taken increase" values in basis points.

    Returns:
        Multiplier in basis points.
    """
    return 10000 + sum(vulnerability_bonuses)


def stun_multiplier(
    is_stunned: bool,
    stun_dmg_mult: int = 15000,
    stun_area_override: int = 0,
) -> int:
    """Zone 7: Stun area.

    Args:
        is_stunned: Whether the target is currently stunned.
        stun_dmg_mult: Stun damage multiplier in basis points (default 15000 = 1.5*).
                       Can vary by enemy (some have 20000 = 2.0*).
        stun_area_override: Stun area override value in basis points.

    Returns:
        Multiplier in basis points, clamped to [2000, 50000].
    """
    if stun_area_override > 0:
        return max(2000, min(50000, 10000 + stun_area_override))
    if not is_stunned:
        return 10000
    return max(2000, min(50000, stun_dmg_mult))


# ---------------------------------------------------------------------------
# Anomaly-specific zones
# ---------------------------------------------------------------------------


def anomaly_proficiency_multiplier(anomaly_proficiency: int) -> int:
    """Anomaly proficiency area.

    Args:
        anomaly_proficiency: Anomaly proficiency stat value (NOT basis points — raw value).

    Returns:
        Multiplier in basis points, clamped to [0, 100000] (0* to 10*).
    """
    # anomaly_proficiency / 100, expressed in basis points
    raw = anomaly_proficiency * 100
    return max(0, min(100000, raw))


def anomaly_level_multiplier(level: int) -> int:
    """Anomaly level area.

    Formula: 1 + (1/59) * (level - 1)
    Level 1 -> 1.0, Level 60 -> 2.0.

    Args:
        level: Attacker's level.

    Returns:
        Multiplier in basis points.
    """
    capped = max(1, min(60, level))
    return 10000 + 10000 * (capped - 1) // 59


# ---------------------------------------------------------------------------
# Composite damage calculations
# ---------------------------------------------------------------------------


def calculate_standard_damage(
    *,
    scaling_stat: int,
    multiplier: int,
    dmg_bonuses: list[int] | None = None,
    crit_rate: int = 500,
    crit_dmg: int = 5000,
    crit_mode: CritMode = CritMode.EXPECTED,
    attacker_level: int = 60,
    enemy_base_def: int = 50,
    enemy_level: int = 60,
    pen_ratio: int = 0,
    pen_flat: int = 0,
    def_ignore: int = 0,
    enemy_res: int = 0,
    res_reduction: int = 0,
    res_ignore: int = 0,
    vulnerability_bonuses: list[int] | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    stun_area_override: int = 0,
    direct_dmg_bonus: int = 0,
) -> DamageResult:
    """Calculate standard (non-anomaly) damage.

    Standard DMG = BaseDMG * BoostArea * CritArea * DEFArea * RESArea
                   * VulnerabilityArea * StunArea * DirectDmgArea

    All zone multipliers are computed independently, then chained.

    ``direct_dmg_bonus`` (basis points) is DirectDmgArea — a separate
    multiplicative zone from BoostArea (Windswept infusion, F-11/F-23b).
    Default 0 -> DirectDmgArea = 10000 (neutral), so existing callers are
    unaffected. Anomaly damage never receives this bonus (Windswept Direct
    DMG explicitly does not apply to anomaly DMG) — only wired here, not
    into calculate_anomaly_damage.
    """
    base = base_damage(scaling_stat, multiplier)
    boost = dmg_bonus_multiplier(dmg_bonuses or [])
    crit = crit_multiplier(crit_rate, crit_dmg, crit_mode)
    defense = def_multiplier(
        attacker_level,
        enemy_base_def,
        enemy_level,
        pen_ratio=pen_ratio,
        pen_flat=pen_flat,
        def_ignore=def_ignore,
    )
    res = res_multiplier(enemy_res, res_reduction=res_reduction, res_ignore=res_ignore)
    vuln = dmg_taken_multiplier(vulnerability_bonuses or [])
    stun = stun_multiplier(is_stunned, stun_dmg_mult, stun_area_override)
    direct = 10000 + direct_dmg_bonus

    # DEF formula intermediates for formula-card display.
    lf = level_factor(attacker_level)
    enemy_lf = level_factor(enemy_level)
    enemy_def_scaled = enemy_base_def * enemy_lf // 50
    eff_def = enemy_def_scaled * (10000 - def_ignore) // 10000
    eff_def = eff_def * (10000 - pen_ratio) // 10000
    eff_def_pre_floor = eff_def - pen_flat
    eff_def = max(0, eff_def_pre_floor)

    # Chain multiply, one zone at a time: `total = total * zone // 10000`.
    # Each step floors, and each floored unit is then amplified by the zones that
    # follow, so the chain is very slightly biased downward — bounded well under 0.1%
    # of a hit and not worth restructuring, but it is NOT the "defer the division to
    # the end" scheme an earlier version of this comment claimed. Corrected 2026-07-31
    # during the damage-sim audit (docs/RESEARCH_damage_sim_audit.md, MINOR-1): the
    # comment described an implementation that does not exist here.
    total = base
    total = total * boost // 10000
    total = total * crit // 10000
    total = total * defense // 10000
    total = total * res // 10000
    total = total * vuln // 10000
    total = total * stun // 10000
    total = total * direct // 10000

    return DamageResult(
        total=total,
        base_dmg=base,
        boost_mult=boost,
        crit_mult=crit,
        def_mult=defense,
        res_mult=res,
        vulnerability_mult=vuln,
        stun_mult=stun,
        effective_atk=scaling_stat,
        level_factor_val=lf,
        effective_enemy_def=eff_def,
        effective_enemy_def_pre_floor=eff_def_pre_floor,
        stun_base_mult=stun_dmg_mult if is_stunned else 0,
        direct_mult=direct,
    )


@dataclass(frozen=True)
class SheerDamageResult:
    """Result of a Sheer Damage calculation (Rupture specialty).

    Sheer Damage omits the DEF zone entirely. All other standard zones apply.
    SheerBoostArea is a separate multiplicative zone on top of BoostArea.
    """

    total: int
    base_dmg: int
    sheer_force: int  # resolved SheerForce used as scaling stat
    boost_mult: int  # BoostArea (regular dmg_bonus pool)
    crit_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int
    sheer_boost_mult: int  # SheerBoostArea (sheer_dmg_bonus pool, separate zone)
    stun_base_mult: int = 0


def calculate_sheer_damage(
    *,
    sheer_force: int,
    multiplier: int,
    dmg_bonuses: list[int] | None = None,
    sheer_dmg_bonuses: list[int] | None = None,
    crit_rate: int = 500,
    crit_dmg: int = 5000,
    crit_mode: CritMode = CritMode.EXPECTED,
    enemy_res: int = 0,
    res_reduction: int = 0,
    res_ignore: int = 0,
    vulnerability_bonuses: list[int] | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
) -> SheerDamageResult:
    """Calculate Sheer Damage for Rupture-specialty agents.

    Sheer DMG = BaseDMG × BoostArea × CritArea × RESArea
                × VulnerabilityArea × StunArea × SheerBoostArea

    The DEF zone is intentionally absent. PEN%, PEN Flat, and DEF Ignore are
    no-ops in this path — do not pass them; they are not in the signature.

    BoostArea and SheerBoostArea are independent multiplicative zones:
      BoostArea      = 1 + Σ regular dmg_bonus (same pool as standard damage)
      SheerBoostArea = 1 + Σ sheer_dmg_bonus   (separate Sheer-only pool)

    References:
      - references/ZZZ Stats and Damage Calculation Reference.html
        (Sheer Damage / Sheer Force / Sheer DMG Mod sections)
      - DESIGN_sheer_damage.md §Formula
    """
    base = base_damage(sheer_force, multiplier)
    boost = dmg_bonus_multiplier(dmg_bonuses or [])
    crit = crit_multiplier(crit_rate, crit_dmg, crit_mode)
    res = res_multiplier(enemy_res, res_reduction=res_reduction, res_ignore=res_ignore)
    vuln = dmg_taken_multiplier(vulnerability_bonuses or [])
    stun = stun_multiplier(is_stunned, stun_dmg_mult)
    sheer_boost = 10000 + sum(sheer_dmg_bonuses or [])

    total = base
    total = total * boost // 10000
    total = total * crit // 10000
    total = total * res // 10000
    total = total * vuln // 10000
    total = total * stun // 10000
    total = total * sheer_boost // 10000

    return SheerDamageResult(
        total=total,
        base_dmg=base,
        sheer_force=sheer_force,
        boost_mult=boost,
        crit_mult=crit,
        res_mult=res,
        vulnerability_mult=vuln,
        stun_mult=stun,
        sheer_boost_mult=sheer_boost,
        stun_base_mult=stun_dmg_mult if is_stunned else 0,
    )


def calculate_anomaly_damage(
    *,
    anomaly_type: AnomalyType,
    atk: int,
    anomaly_proficiency: int = 0,
    attacker_level: int = 60,
    dmg_bonuses: list[int] | None = None,
    anomaly_dmg_bonus: int = 0,
    enemy_base_def: int = 50,
    enemy_level: int = 60,
    pen_ratio: int = 0,
    pen_flat: int = 0,
    def_ignore: int = 0,
    enemy_res: int = 0,
    res_reduction: int = 0,
    res_ignore: int = 0,
    vulnerability_bonuses: list[int] | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    procs: int | None = None,
    stun_area_override: int = 0,
    refringe_mult: int = 10000,
    anomaly_crit_rate: int = 0,
    anomaly_crit_dmg: int = 0,
    crit_mode: CritMode = CritMode.EXPECTED,
) -> AnomalyResult:
    """Calculate anomaly damage.

    Anomaly DMG = BaseDMG * BoostArea * DEFArea * RESArea
                  * VulnerabilityArea * StunArea * RefringeArea
                  * AnomalyCritArea * AnomalyProfArea * LevelArea * AnomalyBoostArea

    Anomaly damage does NOT crit **by default** — ``anomaly_crit_rate`` defaults
    to 0, which makes AnomalyCritArea exactly 10000 in every crit mode, so every
    caller that does not pass it is byte-identical to the pre-#162 behaviour.

    A kit may exempt its own anomalies, and some do. Jane's core passive (DB
    ``core_skills`` level 7, verbatim): "Assault DMG has a chance to trigger a
    critical hit against enemies in the Gnawed state, with a base CRIT Rate of
    40% and CRIT DMG of 50%. Each point of Jane's Anomaly Proficiency further
    increases this CRIT Rate by 0.16%." Her M2 adds +50% to that CRIT DMG.

    The pool is **separate from the standard crit stats**, not an alias for
    them: ZO models it as `anom_crit_` / `anom_crit_dmg_` alongside, never
    inside, `crit_` / `crit_dmg_` (`libs/zzz/consts/src/common.ts`), and its
    `anomaly_crit_mult_` zone is built the same way this one is
    (`data/common/dmg.ts`). So a disc's CRIT Rate does not reach anomaly damage
    and must never be passed here.

    Args:
        anomaly_type: Which anomaly (burn, shock, etc.).
        atk: Total ATK stat.
        anomaly_proficiency: Raw anomaly proficiency stat value.
        attacker_level: Attacker's level.
        dmg_bonuses: General damage bonuses (basis points).
        anomaly_dmg_bonus: Additional anomaly-specific damage bonus (basis points).
        procs: Override number of procs (default: use anomaly type's standard count).
        refringe_mult: RefringeArea (basis points, 10000 = neutral) — Remielle's
            Refringe Coefficient, its own chain zone separate from
            anomaly_dmg_bonus (DESIGN_remielle.md §7.1). Default 10000 leaves
            every existing caller byte-identical.
    """
    base_mult, default_procs = ANOMALY_BASE[anomaly_type]
    actual_procs = procs if procs is not None else default_procs

    base = base_damage(atk, base_mult)
    boost = dmg_bonus_multiplier(dmg_bonuses or [])
    defense = def_multiplier(
        attacker_level,
        enemy_base_def,
        enemy_level,
        pen_ratio=pen_ratio,
        pen_flat=pen_flat,
        def_ignore=def_ignore,
    )
    res = res_multiplier(enemy_res, res_reduction=res_reduction, res_ignore=res_ignore)
    vuln = dmg_taken_multiplier(vulnerability_bonuses or [])
    stun = stun_multiplier(is_stunned, stun_dmg_mult, stun_area_override)
    anom_prof = anomaly_proficiency_multiplier(anomaly_proficiency)
    level_mult = anomaly_level_multiplier(attacker_level)
    anomaly_boost = 10000 + anomaly_dmg_bonus
    # AnomalyCritArea. Guarded on the RATE, not the mode: a zero rate means the
    # anomaly cannot crit at all, so `CritMode.CRIT` must not turn an ungranted
    # anomaly into a guaranteed crit the way `crit_multiplier` would (it returns
    # 10000 + crit_dmg without consulting the rate). This is what keeps "anomaly
    # damage does not crit" true by default in every mode.
    anomaly_crit = (
        crit_multiplier(anomaly_crit_rate, anomaly_crit_dmg, crit_mode)
        if anomaly_crit_rate > 0
        else 10000
    )

    # DEF formula intermediates for formula-card display.
    lf = level_factor(attacker_level)
    enemy_lf = level_factor(enemy_level)
    enemy_def_scaled = enemy_base_def * enemy_lf // 50
    eff_def = enemy_def_scaled * (10000 - def_ignore) // 10000
    eff_def = eff_def * (10000 - pen_ratio) // 10000
    eff_def_pre_floor = eff_def - pen_flat
    eff_def = max(0, eff_def_pre_floor)

    # Chain multiply. RefringeArea sits adjacent to the damage-bonus-family
    # zones (BoostArea here, AnomalyBoostArea below) and before the
    # anomaly-proficiency / level areas — an unverified-against-the-game
    # slot choice frozen per DESIGN_remielle.md §7.1; the identity default
    # (10000) makes every existing fixture unaffected regardless of slot.
    per_proc = base
    per_proc = per_proc * boost // 10000
    per_proc = per_proc * refringe_mult // 10000
    per_proc = per_proc * defense // 10000
    per_proc = per_proc * res // 10000
    per_proc = per_proc * vuln // 10000
    per_proc = per_proc * stun // 10000
    per_proc = per_proc * anomaly_crit // 10000
    per_proc = per_proc * anom_prof // 10000
    per_proc = per_proc * level_mult // 10000
    per_proc = per_proc * anomaly_boost // 10000

    return AnomalyResult(
        per_proc=per_proc,
        total=per_proc * actual_procs,
        procs=actual_procs,
        base_dmg=base,
        boost_mult=boost,
        def_mult=defense,
        res_mult=res,
        vulnerability_mult=vuln,
        stun_mult=stun,
        anomaly_prof_mult=anom_prof,
        level_mult=level_mult,
        anomaly_boost_mult=anomaly_boost,
        level_factor_val=lf,
        effective_enemy_def=eff_def,
        effective_enemy_def_pre_floor=eff_def_pre_floor,
        stun_base_mult=stun_dmg_mult if is_stunned else 0,
        refringe_mult=refringe_mult,
        anomaly_crit_mult=anomaly_crit,
    )


@dataclass(frozen=True)
class DisorderResult:
    """Result of a disorder damage calculation."""

    total: int
    base_dmg: int
    boost_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int
    anomaly_prof_mult: int
    level_mult: int
    anomaly_boost_mult: int
    disorder_boost_mult: int
    time_remaining_factor: int  # in basis points (e.g. 5000 = 50%)
    level_factor_val: int = 0
    effective_enemy_def: int = 0
    effective_enemy_def_pre_floor: int = 0
    stun_base_mult: int = 0
    flat_base_dmg: int = 0  # flat AP-scaled term added to base (e.g. Yanagi Polarity Disorder)
    refringe_mult: int = 10000


@dataclass(frozen=True)
class VortexResult:
    """Result of a vortex damage calculation."""

    total: int
    base_dmg: int
    boost_mult: int
    def_mult: int
    res_mult: int
    vulnerability_mult: int
    stun_mult: int
    anomaly_prof_mult: int
    level_mult: int
    anomaly_boost_mult: int
    vortex_boost_mult: int
    level_factor_val: int = 0
    effective_enemy_def: int = 0
    stun_base_mult: int = 0
    refringe_mult: int = 10000


def calculate_buildup(
    *,
    move_buildup: int,
    anomaly_buildup_bonus: int = 0,
    anomaly_mastery: int = 100,
    enemy_anomaly_res: int = 0,
    is_stunned: bool = False,
    stun_buildup_multiplier: int = 10000,
) -> int:
    """Calculate buildup points applied to enemy gauge per hit.

    Formula:
      buildup = move_buildup * (1 + anomaly_buildup_bonus/10000)
                * (anomaly_mastery/100) * (1 - enemy_anomaly_res/10000)
                * (stun_buildup_multiplier/10000 if is_stunned else 1.0)
    """
    val = move_buildup * (10000 + anomaly_buildup_bonus) // 10000
    val = val * anomaly_mastery // 100
    val = val * (10000 - enemy_anomaly_res) // 10000
    if is_stunned:
        val = val * stun_buildup_multiplier // 10000
    return val


def calculate_disorder_damage(
    *,
    anomaly_type: AnomalyType,
    atk: int,
    anomaly_proficiency: int = 0,
    attacker_level: int = 60,
    dmg_bonuses: list[int] | None = None,
    anomaly_dmg_bonus: int = 0,
    disorder_dmg_bonus: int = 0,
    enemy_base_def: int = 50,
    enemy_level: int = 60,
    pen_ratio: int = 0,
    pen_flat: int = 0,
    def_ignore: int = 0,
    enemy_res: int = 0,
    res_reduction: int = 0,
    res_ignore: int = 0,
    vulnerability_bonuses: list[int] | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    remaining_duration: float,
    max_duration: float = 10.0,
    additional_mv: int = 0,
    stun_area_override: int = 0,
    base_dmg_bonus_pct: int = 0,
    flat_base_dmg: int = 0,
    refringe_mult: int = 10000,
) -> DisorderResult:
    """Calculate disorder damage.

    Disorder DMG = BaseDMG(using ATK and Disorder MV) * BoostArea * DEFArea * RESArea
                   * VulnerabilityArea * StunArea
                   * AnomalyProfArea * LevelArea * AnomalyBoostArea * DisorderBoostArea

    Formulas for Disorder MV (Leifa Canonical, t = remaining_duration). Burn and
    Corruption are tick-quantized to 0.5s boundaries (Leifa's `[t / 0.5]` bracket
    notation = floor); Shock, Ice-Freeze, and Assault are continuous in t
    (unbracketed in Leifa). Arkkus states time terms are generally
    "rounded down" in whole seconds, which conflicts with Leifa's per-type
    mix of continuous and 0.5s-tick terms — we follow Leifa (see F-03 in
    RESEARCH_math_review.md and DECISIONS.md):
      - BURN: 450% + Additional MV + floor(t / 0.5) * 50%
      - SHOCK: 450% + Additional MV + t * 125% (continuous)
      - CORRUPTION: 450% + Additional MV + floor(t / 0.5) * 62.5%
      - SHATTER (Ice-Freeze): 450% + Additional MV + t * 7.5% (continuous)
      - ASSAULT: 450% + Additional MV + t * 7.5% (continuous)
      - WINDSWEPT: 100% + Additional MV
    """
    t = max(0.0, min(float(max_duration), float(remaining_duration)))

    if anomaly_type == AnomalyType.BURN:
        ticks = floor(t / 0.5)
        disorder_mv = 45000 + additional_mv + ticks * 5000
    elif anomaly_type == AnomalyType.CORRUPTION:
        ticks = floor(t / 0.5)
        disorder_mv = 45000 + additional_mv + ticks * 6250
    elif anomaly_type == AnomalyType.SHOCK:
        disorder_mv = 45000 + additional_mv + floor(t * 12500)
    elif anomaly_type == AnomalyType.SHATTER:
        # Ice-Freeze: 450% + t×7.5% (Leifa). Frost-Freeze (Miyabi 600%+t×75%) is a non-goal.
        disorder_mv = 45000 + additional_mv + floor(t * 750)
    elif anomaly_type == AnomalyType.ASSAULT:
        disorder_mv = 45000 + additional_mv + floor(t * 750)
    elif anomaly_type == AnomalyType.WINDSWEPT:
        disorder_mv = 10000 + additional_mv
    else:
        disorder_mv = 45000 + additional_mv

    base = base_damage(atk, disorder_mv) * (10000 + base_dmg_bonus_pct) // 10000 + flat_base_dmg
    boost = dmg_bonus_multiplier(dmg_bonuses or [])
    defense = def_multiplier(
        attacker_level,
        enemy_base_def,
        enemy_level,
        pen_ratio=pen_ratio,
        pen_flat=pen_flat,
        def_ignore=def_ignore,
    )
    res = res_multiplier(enemy_res, res_reduction=res_reduction, res_ignore=res_ignore)
    vuln = dmg_taken_multiplier(vulnerability_bonuses or [])
    stun = stun_multiplier(is_stunned, stun_dmg_mult, stun_area_override)
    anom_prof = anomaly_proficiency_multiplier(anomaly_proficiency)
    level_mult = anomaly_level_multiplier(attacker_level)
    anomaly_boost = 10000 + anomaly_dmg_bonus
    disorder_boost = 10000 + disorder_dmg_bonus

    # DEF intermediates
    lf = level_factor(attacker_level)
    enemy_lf = level_factor(enemy_level)
    enemy_def_scaled = enemy_base_def * enemy_lf // 50
    eff_def = enemy_def_scaled * (10000 - def_ignore) // 10000
    eff_def = eff_def * (10000 - pen_ratio) // 10000
    eff_def_pre_floor = eff_def - pen_flat
    eff_def = max(0, eff_def_pre_floor)

    time_remaining_factor = floor((t / max_duration) * 10000) if max_duration > 0 else 0

    # RefringeArea sits in the same slot as calculate_anomaly_damage's (adjacent
    # to BoostArea, before DEFArea) so a Refringed aura's Disorder reproduces the
    # same relative scaling the triggering Anomaly got (DESIGN_remielle.md §7.1).
    total = base
    total = total * boost // 10000
    total = total * refringe_mult // 10000
    total = total * defense // 10000
    total = total * res // 10000
    total = total * vuln // 10000
    total = total * stun // 10000
    total = total * anom_prof // 10000
    total = total * level_mult // 10000
    total = total * anomaly_boost // 10000
    total = total * disorder_boost // 10000

    return DisorderResult(
        total=total,
        base_dmg=base,
        boost_mult=boost,
        def_mult=defense,
        res_mult=res,
        vulnerability_mult=vuln,
        stun_mult=stun,
        anomaly_prof_mult=anom_prof,
        level_mult=level_mult,
        anomaly_boost_mult=anomaly_boost,
        disorder_boost_mult=disorder_boost,
        time_remaining_factor=time_remaining_factor,
        level_factor_val=lf,
        effective_enemy_def=eff_def,
        effective_enemy_def_pre_floor=eff_def_pre_floor,
        stun_base_mult=stun_dmg_mult if is_stunned else 0,
        flat_base_dmg=flat_base_dmg,
        refringe_mult=refringe_mult,
    )


def calculate_vortex_damage(
    *,
    vortex_kind: str,
    atk: int,
    anomaly_proficiency: int = 0,
    attacker_level: int = 60,
    dmg_bonuses: list[int] | None = None,
    anomaly_dmg_bonus: int = 0,
    vortex_dmg_bonus: int = 0,
    enemy_base_def: int = 50,
    enemy_level: int = 60,
    pen_ratio: int = 0,
    pen_flat: int = 0,
    def_ignore: int = 0,
    enemy_res: int = 0,
    res_reduction: int = 0,
    res_ignore: int = 0,
    vulnerability_bonuses: list[int] | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    remaining_duration: float,
    max_duration: float = 10.0,
    additional_mv: int = 0,
    stun_area_override: int = 0,
    refringe_mult: int = 10000,
) -> VortexResult:
    """Calculate vortex damage.

    Vortex DMG = BaseDMG(using ATK and Vortex MV) * BoostArea * DEFArea * RESArea
                 * VulnerabilityArea * StunArea
                 * AnomalyProfArea * LevelArea * AnomalyBoostArea * VortexBoostArea

    Formulas for Vortex MV (Leifa Canonical, t = remaining_duration). Burn and
    Corruption are tick-quantized to 0.5s boundaries (Leifa's `[t / 0.5]`
    bracket = floor); shock/ice_freeze/assault/frost_freeze are continuous in
    t (unbracketed in Leifa). See F-03 note on `calculate_disorder_damage`.
      - burn: 900% + Additional MV + floor(t / 0.5) * 50%
      - shock: 650% + Additional MV + t * 125% (continuous)
      - corruption: 650% + Additional MV + floor(t / 0.5) * 62.5%
      - ice_freeze: 1300% + Additional MV + t * 7.5% (continuous)
      - frost_freeze: 0% + Additional MV + t * 75% (continuous)
      - assault: 650% + Additional MV + t * 7.5% (continuous)
    """
    t = max(0.0, min(float(max_duration), float(remaining_duration)))

    if vortex_kind == "burn":
        ticks = floor(t / 0.5)
        vortex_mv = 90000 + additional_mv + ticks * 5000
    elif vortex_kind == "corruption":
        ticks = floor(t / 0.5)
        vortex_mv = 65000 + additional_mv + ticks * 6250
    elif vortex_kind == "shock":
        vortex_mv = 65000 + additional_mv + floor(t * 12500)
    elif vortex_kind == "ice_freeze":
        vortex_mv = 130000 + additional_mv + floor(t * 750)
    elif vortex_kind == "frost_freeze":
        vortex_mv = additional_mv + floor(t * 7500)
    elif vortex_kind == "assault":
        vortex_mv = 65000 + additional_mv + floor(t * 750)
    else:
        vortex_mv = 65000 + additional_mv

    base = base_damage(atk, vortex_mv)
    boost = dmg_bonus_multiplier(dmg_bonuses or [])
    defense = def_multiplier(
        attacker_level,
        enemy_base_def,
        enemy_level,
        pen_ratio=pen_ratio,
        pen_flat=pen_flat,
        def_ignore=def_ignore,
    )
    res = res_multiplier(enemy_res, res_reduction=res_reduction, res_ignore=res_ignore)
    vuln = dmg_taken_multiplier(vulnerability_bonuses or [])
    stun = stun_multiplier(is_stunned, stun_dmg_mult, stun_area_override)
    anom_prof = anomaly_proficiency_multiplier(anomaly_proficiency)
    level_mult = anomaly_level_multiplier(attacker_level)
    anomaly_boost = 10000 + anomaly_dmg_bonus
    vortex_boost = 10000 + vortex_dmg_bonus

    # DEF intermediates
    lf = level_factor(attacker_level)
    enemy_lf = level_factor(enemy_level)
    enemy_def_scaled = enemy_base_def * enemy_lf // 50
    eff_def = enemy_def_scaled * (10000 - def_ignore) // 10000
    eff_def = eff_def * (10000 - pen_ratio) // 10000
    eff_def = max(0, eff_def - pen_flat)

    # RefringeArea sits in the same slot as calculate_anomaly_damage's (adjacent
    # to BoostArea, before DEFArea) — see calculate_disorder_damage's identical
    # comment (DESIGN_remielle.md §7.1).
    total = base
    total = total * boost // 10000
    total = total * refringe_mult // 10000
    total = total * defense // 10000
    total = total * res // 10000
    total = total * vuln // 10000
    total = total * stun // 10000
    total = total * anom_prof // 10000
    total = total * level_mult // 10000
    total = total * anomaly_boost // 10000
    total = total * vortex_boost // 10000

    return VortexResult(
        total=total,
        base_dmg=base,
        boost_mult=boost,
        def_mult=defense,
        res_mult=res,
        vulnerability_mult=vuln,
        stun_mult=stun,
        anomaly_prof_mult=anom_prof,
        level_mult=level_mult,
        anomaly_boost_mult=anomaly_boost,
        vortex_boost_mult=vortex_boost,
        level_factor_val=lf,
        effective_enemy_def=eff_def,
        stun_base_mult=stun_dmg_mult if is_stunned else 0,
        refringe_mult=refringe_mult,
    )


def calculate_luminize_damage(
    *,
    voidflare_atk: int,
    voidflare_dmg_bonus_bp: int,
    voidflare_pen_ratio_bp: int,
    voidflare_pen_flat: int,
    voidflare_anomaly_proficiency: int,
    luminize_mult_bp: int,
    attacker_level: int = 60,
    remielle_anomaly_proficiency: int = 0,
    ap_bonus_per_point_bp: int = 0,
    remielle_anomaly_dmg_bonus: int = 0,
    enemy_base_def: int = 50,
    enemy_level: int = 60,
    def_ignore: int = 0,
    enemy_res: int = 0,
    res_reduction: int = 0,
    res_ignore: int = 0,
    luminize_res_ignore: int = 0,
    vulnerability_bonuses: list[int] | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    stun_area_override: int = 0,
) -> AnomalyResult:
    """Calculate one Luminize instance (Remielle, DESIGN_remielle.md §7.2).

    Luminize DMG = BaseDMG(voidflare_atk, EffectiveMult) * BoostArea(stored)
                   * DEFArea(stored PEN) * RESArea(stored element, live debuffs)
                   * VulnerabilityArea * StunArea * AnomalyProfArea(stored AP)
                   * LevelArea * AnomalyBoostArea(Remielle's own, post-storage)

    Fractions a stored Voidflare, not a live teammate — every ``voidflare_*``
    argument is that snapshot's frozen value (``lumiflux.VoidflareRecord``,
    Task 12), never re-read from the teammate live. Only the enemy's
    *current* mitigation (``enemy_res``/``res_reduction``/``res_ignore``/
    ``def_ignore``/``vulnerability_bonuses``/stun state) and Remielle's own
    *current* stats are live — matching the guide's "Voidflare immutability"
    (DESIGN §9.1 test 3).

    Takes the Voidflare's fields as flat scalars rather than a
    ``VoidflareRecord`` object so this module stays free of a dependency on
    ``app.services.lumiflux`` (Task 13's file list is this module only); the
    caller (Task 14, `anomaly_simulator.py`) unpacks the record the same way
    `build_damage_service.calculate_build_anomaly` unpacks a `BuildSnapshot`
    into `calculate_anomaly_damage`'s flat args.

    Two separately-named AP arguments (DESIGN §2 OQ-1, guide line 104's
    naming trap):

    - ``voidflare_anomaly_proficiency`` — the **stored teammate's** AP at
      capture time, feeding **only** the ``AnomalyProfArea`` zone (the same
      zone every other anomaly-type damage function has).
    - ``remielle_anomaly_proficiency`` — **Remielle's own live** AP,
      feeding **only** the effective-multiplier's AP bonus term below.
      Never the same input, never interchangeable.

    ``EffectiveMult`` is **multiplicative**, not the ``// 10000``
    fraction-of-a-stat convention used elsewhere in this file:

        effective_mult_bp = luminize_mult_bp
                             * (10000 + ap_bonus_per_point_bp * remielle_anomaly_proficiency)
                             // 10000

    Not an ``AnomalyType`` member and never routes through
    ``ANOMALY_BASE`` — always exactly one instance (``procs=1``), and
    structurally incapable of ever appearing as a Disorder/Abloom/Vortex
    trigger (DESIGN §7.2), unlike every other anomaly type this module
    computes.
    """
    effective_mult = (
        luminize_mult_bp * (10000 + ap_bonus_per_point_bp * remielle_anomaly_proficiency) // 10000
    )

    base = base_damage(voidflare_atk, effective_mult)
    boost = 10000 + voidflare_dmg_bonus_bp
    defense = def_multiplier(
        attacker_level,
        enemy_base_def,
        enemy_level,
        pen_ratio=voidflare_pen_ratio_bp,
        pen_flat=voidflare_pen_flat,
        def_ignore=def_ignore,
    )
    # Task 19: `luminize_res_ignore` is a res-ignore contribution consumed ONLY
    # here. M1 (Naive Oath) reads "When Remielle triggers Luminize to deal DMG,
    # she ignores 50% of the target's All-Attribute RES" -- scoped to a single
    # damage source, which `scopes[]` cannot express (it gates by move category,
    # and Luminize is not a move: it is a separate emission fired after a trigger
    # move). Routing it through generic `res_ignore` was audit finding S1-A: it
    # cut enemy RES for her Ultimate/Chain/EX/Phase Flow ticks too, ~1.5x on
    # damage the clause never touches.
    #
    # Additive with the generic bucket, not a replacement -- a teammate's RES
    # shred still applies to Luminize like any other damage; this only adds a
    # term no other path can see. It shares `res_multiplier`'s [0, 2.0] clamp,
    # so it is not a way around the RESArea ceiling.
    res = res_multiplier(
        enemy_res,
        res_reduction=res_reduction,
        res_ignore=res_ignore + luminize_res_ignore,
    )
    vuln = dmg_taken_multiplier(vulnerability_bonuses or [])
    stun = stun_multiplier(is_stunned, stun_dmg_mult, stun_area_override)
    anom_prof = anomaly_proficiency_multiplier(voidflare_anomaly_proficiency)
    level_mult = anomaly_level_multiplier(attacker_level)
    anomaly_boost = 10000 + remielle_anomaly_dmg_bonus

    # DEF formula intermediates for formula-card display.
    lf = level_factor(attacker_level)
    enemy_lf = level_factor(enemy_level)
    enemy_def_scaled = enemy_base_def * enemy_lf // 50
    eff_def = enemy_def_scaled * (10000 - def_ignore) // 10000
    eff_def = eff_def * (10000 - voidflare_pen_ratio_bp) // 10000
    eff_def_pre_floor = eff_def - voidflare_pen_flat
    eff_def = max(0, eff_def_pre_floor)

    per_proc = base
    per_proc = per_proc * boost // 10000
    per_proc = per_proc * defense // 10000
    per_proc = per_proc * res // 10000
    per_proc = per_proc * vuln // 10000
    per_proc = per_proc * stun // 10000
    per_proc = per_proc * anom_prof // 10000
    per_proc = per_proc * level_mult // 10000
    per_proc = per_proc * anomaly_boost // 10000

    return AnomalyResult(
        per_proc=per_proc,
        total=per_proc,
        procs=1,
        base_dmg=base,
        boost_mult=boost,
        def_mult=defense,
        res_mult=res,
        vulnerability_mult=vuln,
        stun_mult=stun,
        anomaly_prof_mult=anom_prof,
        level_mult=level_mult,
        anomaly_boost_mult=anomaly_boost,
        level_factor_val=lf,
        effective_enemy_def=eff_def,
        effective_enemy_def_pre_floor=eff_def_pre_floor,
        stun_base_mult=stun_dmg_mult if is_stunned else 0,
        effective_mult_bp=effective_mult,
    )


@dataclass(frozen=True)
class AbloomResult:
    """Result of an Abloom secondary-anomaly damage calculation."""

    total: int
    abloom_boost_mult: int  # 10000 + abloom_dmg_bonus (bp)
    crit_mult: int  # 10000 + eff_cr*crit_dmg//10000 (bp); 10000 when no crit


def calculate_abloom_damage(
    *,
    abloom_mv_bp: int,
    original_anomaly_dmg: int,
    ap: int,
    abloom_dmg_bonus: int = 0,
    abloom_ap_scaled: bool = True,
    crit_rate_bp: int = 0,
    crit_dmg_bp: int = 0,
    crit_mode: CritMode = CritMode.EXPECTED,
) -> AbloomResult:
    """Calculate Abloom secondary-anomaly damage.

    AP-scaled formula (Leifa / game text, LOG_abloom.md A1):
        AdditionalDMG = (abloom_mv_bp / 10000) × (AP / 10) × original_anomaly_dmg
                      × (1 + abloom_dmg_bonus / 10000)

    Flat formula (abloom_ap_scaled=False — Grace, Burnice):
        AdditionalDMG = (abloom_mv_bp / 10000) × original_anomaly_dmg
                      × (1 + abloom_dmg_bonus / 10000)

    Optional crit area (Aria M1 — DESIGN_abloom_c8.md §A2):
        crit_mult = 10000 + clamp(crit_rate_bp, 0, 10000) * crit_dmg_bp // 10000
        AdditionalDMG *= crit_mult / 10000

    **Why this keeps its own crit buckets** (`abloom_crit_rate` /
    `abloom_crit_dmg`) rather than reading the general anomaly-crit pool added
    for #162. C2 originally proposed merging them "so there is one mechanism";
    the two grants that actually exist are scoped on different axes and a single
    bucket cannot express both:

    * Jane's core passive is **element**-scoped — ZO registers it as
      `anom_crit_.physical`, i.e. Physical (Assault) anomaly damage.
    * Aria's M1 is **damage-source**-scoped — Abloom alone, whatever element the
      fractioned anomaly was.

    `element_scope` gates by element, so pointing Abloom at the shared pool would
    hand Jane's Assault CRIT to a Physical Abloom she has no grant over — the
    same wrong-wiring class as M1's flattened Luminize RES-ignore (D-KV6). The
    two stay separate until a scope system exists that can say "this damage
    source only"; what IS shared is the *shape*, via `crit_multiplier` and the
    zero-rate guard below, so they cannot drift.

    Abloom is NOT the standard ATK chain — no DEF/RES/level/proficiency areas.
    It fractions the already-resolved (post-mitigation) anomaly DMG instance.

    Args:
        abloom_mv_bp: Per-element MV in basis points.
        original_anomaly_dmg: Post-mitigation total of the anomaly proc being fractioned.
        ap: Triggering agent's AP (only used when abloom_ap_scaled=True).
        abloom_dmg_bonus: Abloom-specific DMG bonus in bp (e.g. Frostfall Sickle R1 = 4000).
        abloom_ap_scaled: True (default) for AP-scaled agents (Vivian, Aria); False for
            flat-MV agents whose kit text quotes a fixed percentage (Grace, Burnice).
        crit_rate_bp: Abloom crit rate in bp (0 = no crit). Clamped to [0, 10000].
        crit_dmg_bp: Abloom crit DMG in bp (only used when crit_rate_bp > 0).
    """
    abloom_boost = 10000 + abloom_dmg_bonus
    if abloom_ap_scaled:
        total = original_anomaly_dmg * abloom_mv_bp * ap // 100_000
    else:
        total = original_anomaly_dmg * abloom_mv_bp // 10_000
    total = total * abloom_boost // 10000
    # Shares `crit_multiplier` and B1a's rate-guard so the two anomaly-crit
    # exemptions cannot drift apart in shape (#162 / C2). A zero rate is a hard
    # "cannot crit" in every mode -- delegating unguarded would make
    # `CritMode.CRIT` crit an Abloom whose kit grants no crit at all.
    _crit_mult = (
        crit_multiplier(crit_rate_bp, crit_dmg_bp, crit_mode) if crit_rate_bp > 0 else 10000
    )
    total = total * _crit_mult // 10000
    return AbloomResult(total=total, abloom_boost_mult=abloom_boost, crit_mult=_crit_mult)
