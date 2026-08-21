import type { components } from '../../api/api.types';
import { fmtInt, fmtMultBp, fmtPctBp } from './format-helpers';

type ZoneFormulaSchema = components['schemas']['ZoneFormulaSchema'];

export interface FormulaRow {
  label: string;
  /** Symbolic equation, e.g. "MV × Scaling Stat". */
  eq: string;
  /** Same equation with the actual values substituted in. */
  substituted: string;
  /** Formatted `result_bp` -- a multiplier (×N.NN) for most zones, a raw
   * integer for base_mv_scaling/sheer_force_components. */
  result: string;
  /** Present exactly when a clamp/floor changed the result (DESIGN §2.1). */
  capNote?: string;
}

function capNote(zf: ZoneFormulaSchema, formatResult: (bp: number) => string): string | undefined {
  return zf.pre_clamp_bp == null ? undefined : `capped from ${formatResult(zf.pre_clamp_bp)}`;
}

/**
 * Renders one `ZoneFormula` (DESIGN_explainability.md §2.1) into display
 * strings for the formula-card. Purely presentational -- every value comes
 * straight from the backend's already-computed `terms`/`result_bp`; this
 * never recomputes damage math.
 */
export function renderZoneFormula(zf: ZoneFormulaSchema): FormulaRow {
  const t = zf.terms;
  switch (zf.template) {
    case 'base_mv_scaling':
      return {
        label: 'Base',
        eq: 'MV × Scaling Stat',
        substituted: `${fmtPctBp(t['multiplier_bp'], false)} × ${fmtInt(t['scaling_stat'])}`,
        result: fmtInt(zf.result_bp),
      };

    case 'boost_sum_dmg_pct':
      return {
        label: 'Boost',
        eq: '1 + ΣDMG%',
        substituted: `1 + ${fmtPctBp(t['sum_dmg_pct_bp'])}`,
        result: fmtMultBp(zf.result_bp),
      };

    case 'crit_rate_times_dmg': {
      // crit_rate_bp is the raw (pre-clamp) resolved crit rate -- the damage
      // formula itself clamps crit rate to 100% before multiplying. Display
      // the clamped rate so the substituted equation is internally
      // consistent with `result_bp`; the raw/uncapped value is still
      // surfaced via `capNote` (from `pre_clamp_bp`).
      const displayedCritRate = Math.min(t['crit_rate_bp'], 10000);
      return {
        label: 'Crit',
        eq: '1 + Rate × DMG',
        substituted: `1 + ${fmtPctBp(displayedCritRate, false)} × ${fmtPctBp(t['crit_dmg_bp'], false)}`,
        result: fmtMultBp(zf.result_bp),
        capNote: capNote(zf, fmtMultBp),
      };
    }

    case 'def_area':
      // effective_enemy_def already folds in pen_ratio/pen_flat/def_ignore.
      return {
        label: 'DEF',
        eq: 'LF / (LF + Eff. DEF)',
        substituted: `${fmtInt(t['level_factor_bp'])} / (${fmtInt(t['level_factor_bp'])} + ${fmtInt(t['effective_enemy_def'])})`,
        result: fmtMultBp(zf.result_bp),
        capNote: capNote(zf, fmtMultBp),
      };

    case 'res_area':
      return {
        label: 'RES',
        eq: '1 − Enemy RES + RES Reduction + RES Ignore',
        substituted: `1 − ${fmtPctBp(t['enemy_res_bp'], false)} + ${fmtPctBp(t['res_reduction_bp'])} + ${fmtPctBp(t['res_ignore_bp'])}`,
        result: fmtMultBp(zf.result_bp),
        capNote: capNote(zf, fmtMultBp),
      };

    case 'vuln_sum':
      return {
        label: 'Vulnerability',
        eq: '1 + ΣVuln%',
        substituted: `1 + ${fmtPctBp(t['sum_vuln_bp'])}`,
        result: fmtMultBp(zf.result_bp),
      };

    case 'stun_area': {
      const override = t['stun_area_override_bp'];
      if (override > 0) {
        return {
          label: 'Stun',
          eq: '1 + Override%',
          substituted: `1 + ${fmtPctBp(override)}`,
          result: fmtMultBp(zf.result_bp),
          capNote: capNote(zf, fmtMultBp),
        };
      }
      return {
        label: 'Stun',
        eq: 'Base',
        substituted: fmtMultBp(t['stun_base_mult_bp'] || 10000),
        result: fmtMultBp(zf.result_bp),
        capNote: capNote(zf, fmtMultBp),
      };
    }

    case 'anomaly_prof_area':
      return {
        label: 'Anomaly Prof',
        eq: 'Anomaly Proficiency / 100',
        substituted: `${t['anomaly_proficiency']} / 100`,
        result: fmtMultBp(zf.result_bp),
        capNote: capNote(zf, fmtMultBp),
      };

    case 'anomaly_level_area':
      return {
        label: 'Level',
        eq: '1 + (Level − 1) / 59',
        substituted: `1 + (${t['level']} − 1) / 59`,
        result: fmtMultBp(zf.result_bp),
      };

    case 'anomaly_boost_sum':
      return {
        label: 'Anomaly Bonus',
        eq: '1 + ΣAnomaly DMG%',
        substituted: `1 + ${fmtPctBp(t['sum_anomaly_dmg_pct_bp'])}`,
        result: fmtMultBp(zf.result_bp),
      };

    case 'disorder_boost_sum':
      return {
        label: 'Disorder Bonus',
        eq: '1 + ΣDisorder DMG%',
        substituted: `1 + ${fmtPctBp(t['sum_disorder_dmg_pct_bp'])}`,
        result: fmtMultBp(zf.result_bp),
      };

    case 'sheer_force_components':
      return {
        label: 'SheerForce',
        eq: 'ATK×30% + HP×N% + Flat',
        substituted: `${fmtPctBp(t['atk_pct_bp'], false)}×ATK + ${fmtPctBp(t['hp_pct_bp'], false)}×HP + ${fmtInt(t['flat'])}`,
        result: fmtInt(zf.result_bp),
      };

    case 'sheer_boost_sum':
      return {
        label: 'Sheer Boost',
        eq: '1 + ΣSheer DMG%',
        substituted: `1 + ${fmtPctBp(t['sum_sheer_dmg_pct_bp'])}`,
        result: fmtMultBp(zf.result_bp),
      };

    case 'direct_dmg_sum':
      return {
        label: 'Direct DMG Bonus',
        eq: '1 + ΣDirect DMG%',
        substituted: `1 + ${fmtPctBp(t['sum_direct_dmg_pct_bp'])}`,
        result: fmtMultBp(zf.result_bp),
      };

    default:
      return {
        label: zf.template,
        eq: '',
        substituted: '',
        result: fmtMultBp(zf.result_bp),
      };
  }
}
