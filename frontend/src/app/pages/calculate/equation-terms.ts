import type { components } from '../../api/api.types';
import { fmtInt, fmtMultBp, fmtPctBp } from './format-helpers';

type ComboStepResult = components['schemas']['ComboStepResultSchema'];
type StepAttribution = components['schemas']['StepAttributionSchema'];

export type EquationTermKey =
  | 'base'
  | 'atk'
  | 'crit'
  | 'anomaly_crit'
  | 'dmg'
  | 'sheer_dmg'
  | 'def'
  | 'res'
  | 'vuln'
  | 'stun'
  | 'anomaly_prof'
  | 'anomaly_level'
  | 'anomaly_bonus';

export interface EquationTerm {
  key: EquationTermKey;
  label: string;
  displayValue: string;
  rawValue: number;
  zones: readonly (keyof StepAttribution)[];
  clickable: boolean;
  /**
   * Key into `step.zone_formulas` for this chip's formula-card drill-down
   * (DESIGN_explainability.md §2.1/2.2), or null when the backend has no
   * zone_formula for this chip (e.g. anomaly_crit -- attribution.py only
   * computes a "crit" formula on the non-anomaly path).
   */
  formulaKey: string | null;
}

/**
 * Returns the ordered equation chips for a combo step.
 * Chips whose "hide when" condition is met are excluded from the result.
 * All _mult fields are basis points (10000 = 1.0×).
 */
export function equationTerms(step: ComboStepResult): EquationTerm[] {
  const attr = step.attribution;
  const terms: EquationTerm[] = [];

  // ── Base MV (always shown) ─────────────────────────────────────────────────
  terms.push({
    key: 'base',
    label: 'Base',
    displayValue: fmtPctBp(step.multiplier, false),
    rawValue: step.base_dmg,
    zones: [],
    clickable: true,
    formulaKey: 'base',
  });

  // ── ATK / SheerForce (always shown) ──────────────────────────────────────
  // Sheer path: effective_atk holds SheerForce; label and zone list change.
  const isSheer = step.sheer_force != null;
  terms.push({
    key: 'atk',
    label: isSheer ? 'SheerForce' : 'ATK',
    displayValue: fmtInt(isSheer ? step.sheer_force! : step.effective_atk),
    rawValue: isSheer ? step.sheer_force! : step.effective_atk,
    zones: isSheer ? ['sheer_force_components'] : ['atk_components', 'atk_pct_components'],
    clickable: true,
    formulaKey: isSheer ? 'sheer_force' : null,
  });

  if (step.is_anomaly) {
    // ── Anomaly factor chips ─────────────────────────────────────────────────

    // 3a — Anomaly Prof (always shown for anomaly hits)
    terms.push({
      key: 'anomaly_prof',
      label: 'Anomaly Prof',
      displayValue: fmtMultBp(step.anomaly_proficiency_mult),
      rawValue: step.anomaly_proficiency_mult,
      zones: [],
      clickable: true,
      formulaKey: 'anomaly_prof',
    });

    // 3b — Level (always shown for anomaly hits)
    terms.push({
      key: 'anomaly_level',
      label: 'Level',
      displayValue: fmtMultBp(step.anomaly_level_mult),
      rawValue: step.anomaly_level_mult,
      zones: [],
      clickable: true,
      formulaKey: 'anomaly_level',
    });

    // 3c — Anomaly Bonus (hide when mult == 10000, i.e. no bonus)
    if (step.anomaly_dmg_bonus_mult !== 10000) {
      terms.push({
        key: 'anomaly_bonus',
        label: 'Anomaly Bonus',
        displayValue: fmtMultBp(step.anomaly_dmg_bonus_mult),
        rawValue: step.anomaly_dmg_bonus_mult,
        zones: ['boost_bonuses'],
        clickable: true,
        formulaKey: 'anomaly_boost',
      });
    }

    // Anomaly-crit exception (Jane Doe etc.) — data-driven, not an allowlist.
    // If attribution shows non-zero crit zones, show an "Anomaly Crit" chip.
    // No backend zone_formula exists for this (attribution.py only builds
    // "crit" on the non-anomaly path) -- formulaKey stays null and the
    // formula-card falls back to its hand-computed anomaly-crit block.
    const critRateTotal = attr?.crit_rate?.total ?? 0;
    const critDmgTotal = attr?.crit_dmg?.total ?? 0;
    if (critRateTotal > 0 && critDmgTotal > 0) {
      terms.push({
        key: 'anomaly_crit',
        label: 'Anomaly Crit',
        displayValue: fmtMultBp(step.crit_mult),
        rawValue: step.crit_mult,
        zones: ['crit_rate', 'crit_dmg'],
        clickable: true,
        formulaKey: null,
      });
    }
  } else {
    // ── Standard hit: Crit chip ───────────────────────────────────────────────
    // Hide when both crit zones are empty (no attribution data → use crit_mult)
    const critRateTotal = attr?.crit_rate?.total ?? 0;
    const critDmgTotal = attr?.crit_dmg?.total ?? 0;
    const hasCritData = critRateTotal > 0 || critDmgTotal > 0 || step.crit_mult !== 0;
    if (hasCritData) {
      terms.push({
        key: 'crit',
        label: 'Crit',
        displayValue: fmtMultBp(step.crit_mult),
        rawValue: step.crit_mult,
        zones: ['crit_rate', 'crit_dmg'],
        clickable: true,
        formulaKey: 'crit',
      });
    }
  }

  // ── DMG% (hide when boost_bonuses.total == 0 and boost_mult == 10000) ─────
  const boostTotal = attr?.boost_bonuses?.total ?? 0;
  const boostMult = step.boost_mult;
  if (boostTotal !== 0 || boostMult !== 10000) {
    terms.push({
      key: 'dmg',
      label: 'DMG%',
      displayValue: fmtPctBp(boostMult - 10000),
      rawValue: boostMult,
      zones: ['boost_bonuses'],
      clickable: true,
      formulaKey: 'boost',
    });
  }

  // ── Sheer DMG% (Rupture only — hide when no sheer_boost bonus) ────────────
  if (isSheer) {
    const sheerBoostTotal = attr?.sheer_boost_bonuses?.total ?? 0;
    if (sheerBoostTotal !== 0) {
      terms.push({
        key: 'sheer_dmg',
        label: 'Sheer DMG%',
        displayValue: fmtPctBp(sheerBoostTotal),
        rawValue: sheerBoostTotal,
        zones: ['sheer_boost_bonuses'],
        clickable: true,
        formulaKey: 'sheer_boost',
      });
    }
  }

  // ── DEF (hidden for Sheer path — DEF zone is structurally absent) ────────
  if (!isSheer) {
    terms.push({
      key: 'def',
      label: 'DEF',
      displayValue: fmtMultBp(step.def_mult),
      rawValue: step.def_mult,
      zones: ['pen_ratio', 'pen_flat', 'def_ignore'],
      clickable: true,
      formulaKey: 'def',
    });
  }

  // ── RES (hide when res_mult == 10000) ─────────────────────────────────────
  if (step.res_mult !== 10000) {
    terms.push({
      key: 'res',
      label: 'RES',
      displayValue: fmtMultBp(step.res_mult),
      rawValue: step.res_mult,
      zones: ['res_reduction', 'res_ignore'],
      clickable: true,
      formulaKey: 'res',
    });
  }

  // ── Vuln (hide when vulnerability_mult == 10000) ──────────────────────────
  if (step.vulnerability_mult !== 10000) {
    terms.push({
      key: 'vuln',
      label: 'Vuln',
      displayValue: fmtMultBp(step.vulnerability_mult),
      rawValue: step.vulnerability_mult,
      zones: ['vulnerability'],
      clickable: true,
      formulaKey: 'vulnerability',
    });
  }

  // ── Stun (hide when stun_mult == 10000) ───────────────────────────────────
  if (step.stun_mult !== 10000) {
    terms.push({
      key: 'stun',
      label: 'Stun',
      displayValue: fmtMultBp(step.stun_mult),
      rawValue: step.stun_mult,
      zones: ['stun_bonuses'],
      clickable: true,
      formulaKey: 'stun',
    });
  }

  return terms;
}
