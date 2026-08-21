import type { components } from '../../api/api.types';

type StepAttribution = components['schemas']['StepAttributionSchema'];

export type ZoneFormatType = 'flat' | 'pct';

export const ZONE_LABELS: Record<keyof StepAttribution, string> = {
  atk_components: 'ATK Flat',
  atk_pct_components: 'ATK%',
  crit_rate: 'Crit Rate',
  crit_dmg: 'Crit DMG',
  boost_bonuses: 'DMG Bonus',
  pen_ratio: 'PEN Ratio',
  pen_flat: 'PEN Flat',
  def_ignore: 'DEF Ignore',
  res_reduction: 'RES Reduction',
  res_ignore: 'RES Ignore',
  vulnerability: 'Vulnerability',
  stun_bonuses: 'Stun Bonus',
  sheer_force_components: 'SheerForce',
  sheer_boost_bonuses: 'Sheer DMG%',
};

export const ZONE_FORMAT: Record<keyof StepAttribution, ZoneFormatType> = {
  atk_components: 'flat',
  atk_pct_components: 'pct',
  crit_rate: 'pct',
  crit_dmg: 'pct',
  boost_bonuses: 'pct',
  pen_ratio: 'pct',
  pen_flat: 'flat',
  def_ignore: 'pct',
  res_reduction: 'pct',
  res_ignore: 'pct',
  vulnerability: 'pct',
  stun_bonuses: 'pct',
  sheer_force_components: 'flat',
  sheer_boost_bonuses: 'pct',
};

/** Formats a basis-point value as signed percent string: 3000 → "+30%". */
export function fmtBasisPct(value: number): string {
  const pct = value / 100;
  const sign = value >= 0 ? '+' : '';
  const formatted = parseFloat(pct.toFixed(2)).toString();
  return `${sign}${formatted}%`;
}

/** Formats a flat integer value as signed localized string: 2450 → "+2,450". */
export function fmtFlat(value: number): string {
  const abs = Math.round(Math.abs(value)).toLocaleString();
  return value >= 0 ? `+${abs}` : `-${abs}`;
}

/** Formats a contribution value given the zone's format type. */
export function fmtContribution(value: number, format: ZoneFormatType): string {
  return format === 'flat' ? fmtFlat(value) : fmtBasisPct(value);
}

/** Converts a basis-point multiplier to a display string: 17500 → "×1.75". */
export function fmtMultBp(bp: number, precision = 2): string {
  return `×${(bp / 10000).toFixed(precision)}`;
}

/** Formats a raw (non-basis-point) integer with locale grouping: 2450 → "2,450". */
export function fmtInt(n: number): string {
  return Math.round(n).toLocaleString();
}

/**
 * Converts a basis-point value to a percent string.
 * signed=true (default): positive values get '+' prefix; zero gets no prefix.
 * signed=false: no prefix (for MV% where '+' is meaningless).
 * Examples: 3000 → "+30%", -500 → "-5%", 0 → "0%", 25000 false → "250%".
 */
export function fmtPctBp(bp: number, signed = true): string {
  if (bp === 0) return '0%';
  const pct = bp / 100;
  const sign = signed && bp > 0 ? '+' : '';
  return `${sign}${parseFloat(pct.toFixed(2))}%`;
}
