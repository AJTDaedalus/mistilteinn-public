import { describe, expect, it } from 'vitest';
import { formatStatValue, formatStatLabel } from './stat-format';

describe('formatStatValue', () => {
  // Basis-point percentage stats
  it('formats crit_dmg as percentage', () => {
    expect(formatStatValue('crit_dmg', 3120)).toBe('31.2%');
  });
  it('formats crit_rate as percentage', () => {
    expect(formatStatValue('crit_rate', 2400)).toBe('24.0%');
  });
  it('formats atk_pct as percentage', () => {
    expect(formatStatValue('atk_pct', 300)).toBe('3.0%');
  });
  it('formats hp_pct as percentage', () => {
    expect(formatStatValue('hp_pct', 1000)).toBe('10.0%');
  });
  it('formats def_pct as percentage', () => {
    expect(formatStatValue('def_pct', 480)).toBe('4.8%');
  });
  it('formats pen_ratio as percentage', () => {
    expect(formatStatValue('pen_ratio', 2000)).toBe('20.0%');
  });
  it('formats physical_dmg as percentage', () => {
    expect(formatStatValue('physical_dmg', 1500)).toBe('15.0%');
  });
  it('formats fire_dmg as percentage', () => {
    expect(formatStatValue('fire_dmg', 1500)).toBe('15.0%');
  });
  it('formats ice_dmg as percentage', () => {
    expect(formatStatValue('ice_dmg', 1500)).toBe('15.0%');
  });
  it('formats electric_dmg as percentage', () => {
    expect(formatStatValue('electric_dmg', 1500)).toBe('15.0%');
  });
  it('formats ether_dmg as percentage', () => {
    expect(formatStatValue('ether_dmg', 1500)).toBe('15.0%');
  });

  // Raw / flat stats
  it('formats flat_atk as integer', () => {
    expect(formatStatValue('flat_atk', 540)).toBe('540');
  });
  it('formats atk as integer', () => {
    expect(formatStatValue('atk', 900)).toBe('900');
  });
  it('formats pen_flat as integer', () => {
    expect(formatStatValue('pen_flat', 36)).toBe('36');
  });
  it('formats anomaly_proficiency as integer', () => {
    expect(formatStatValue('anomaly_proficiency', 90)).toBe('90');
  });
  it('formats anomaly_mastery as integer', () => {
    expect(formatStatValue('anomaly_mastery', 50)).toBe('50');
  });
  it('formats impact as integer', () => {
    expect(formatStatValue('impact', 120)).toBe('120');
  });

  // Unknown stat falls back to raw
  it('falls back to raw for unknown stat', () => {
    expect(formatStatValue('unknown_stat', 100)).toBe('100');
  });
});

describe('formatStatLabel', () => {
  it('returns in-game label for crit_rate', () => {
    expect(formatStatLabel('crit_rate')).toBe('CRIT Rate');
  });
  it('returns in-game label for pen_ratio', () => {
    expect(formatStatLabel('pen_ratio')).toBe('PEN %');
  });
  it('returns key unchanged for unknown stat', () => {
    expect(formatStatLabel('unknown_stat')).toBe('unknown_stat');
  });
});
