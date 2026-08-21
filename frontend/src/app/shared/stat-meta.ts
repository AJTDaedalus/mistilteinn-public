/** In-game stat label and display unit for every stat key used in modifiers and discs. */
export const STAT_META: Record<string, { label: string; unit: 'bp' | 'raw' }> = {
  // Core stats — slot 1/2/3 main stats (full base value, not a bonus)
  hp:                        { label: 'HP',                  unit: 'raw' },
  atk:                       { label: 'ATK',                 unit: 'raw' },
  def:                       { label: 'DEF',                 unit: 'raw' },
  // Core stats — flats and percentages
  hp_pct:                    { label: 'HP %',                unit: 'bp'  },
  atk_pct:                   { label: 'ATK %',               unit: 'bp'  },
  def_pct:                   { label: 'DEF %',               unit: 'bp'  },
  flat_hp:                   { label: 'HP',                  unit: 'raw' },
  flat_atk:                  { label: 'ATK',                 unit: 'raw' },
  flat_def:                  { label: 'DEF',                 unit: 'raw' },
  atk_flat:                  { label: 'ATK',                 unit: 'raw' },

  // Crit, PEN, anomaly, impact, energy
  crit_rate:                 { label: 'CRIT Rate',           unit: 'bp'  },
  crit_dmg:                  { label: 'CRIT DMG',            unit: 'bp'  },
  pen_ratio:                 { label: 'PEN %',               unit: 'bp'  },
  pen_flat:                  { label: 'PEN',                 unit: 'raw' },
  anomaly_mastery:           { label: 'Anomaly Mastery',     unit: 'raw' },
  anomaly_proficiency:       { label: 'Anomaly Proficiency', unit: 'raw' },
  impact:                    { label: 'Impact',              unit: 'raw' },
  impact_pct:                { label: 'Impact %',            unit: 'bp'  },
  energy_regen:              { label: 'Energy Regen',        unit: 'bp'  },

  // Element DMG %
  physical_dmg:              { label: 'Physical DMG %',      unit: 'bp'  },
  fire_dmg:                  { label: 'Fire DMG %',          unit: 'bp'  },
  ice_dmg:                   { label: 'Ice DMG %',           unit: 'bp'  },
  electric_dmg:              { label: 'Electric DMG %',      unit: 'bp'  },
  ether_dmg:                 { label: 'Ether DMG %',         unit: 'bp'  },

  // Generic + per-attack DMG bonuses
  dmg_bonus:                 { label: 'DMG %',               unit: 'bp'  },
  basic_dmg_bonus:           { label: 'Basic DMG %',         unit: 'bp'  },
  dash_dmg_bonus:            { label: 'Dash DMG %',          unit: 'bp'  },
  dodge_counter_dmg_bonus:   { label: 'Dodge Counter DMG %', unit: 'bp'  },
  special_dmg_bonus:         { label: 'Special DMG %',       unit: 'bp'  },
  ex_special_dmg_bonus:      { label: 'EX Special DMG %',    unit: 'bp'  },
  chain_dmg_bonus:           { label: 'Chain DMG %',         unit: 'bp'  },
  ultimate_dmg_bonus:        { label: 'Ultimate DMG %',      unit: 'bp'  },
  assist_followup_dmg_bonus: { label: 'Assist DMG %',        unit: 'bp'  },
  anomaly_dmg_bonus:         { label: 'Anomaly DMG %',       unit: 'bp'  },

  // Combat / debuffs against the enemy
  res_reduction:             { label: 'RES Shred',           unit: 'bp'  },
  res_ignore:                { label: 'RES Ignore',          unit: 'bp'  },
  // Task 19 (Remielle M1): RES Ignore that only Luminize damage sees. Labelled
  // by the mechanic it is scoped to, because the number is meaningless without
  // that qualifier — a bare "RES Ignore" chip would read as applying to her
  // whole kit, which is the very misreading audit finding S1-A was.
  luminize_res_ignore:       { label: 'RES Ignore (Luminize)', unit: 'bp' },
  def_ignore:                { label: 'DEF Ignore',          unit: 'bp'  },
  vulnerability:             { label: 'Vulnerability',       unit: 'bp'  },

  // "Final" pre-baked stat buffs (post-scaling, already-resolved % or flat)
  final_atk_pct:             { label: 'ATK %',               unit: 'bp'  },
  final_def_pct:             { label: 'DEF %',               unit: 'bp'  },
  final_hp_pct:              { label: 'HP %',                unit: 'bp'  },
  final_flat_atk:            { label: 'ATK',                 unit: 'raw' },
  // Present in the buff resolver's vocabulary, so the stage-buff picker (#64) can
  // offer them — a key it can offer but not label renders as a raw field name, which
  // is the #62 bug in a new place.
  final_flat_hp:             { label: 'HP',                  unit: 'raw' },
  final_flat_def:            { label: 'DEF',                 unit: 'raw' },

  // Anomaly buildup rate by element
  anomaly_buildup:           { label: 'Anomaly Buildup',     unit: 'bp'  },
  electric_anomaly_buildup:  { label: 'Electric Anomaly Buildup', unit: 'bp' },
  ether_anomaly_buildup:     { label: 'Ether Anomaly Buildup',    unit: 'bp' },
  fire_anomaly_buildup:      { label: 'Fire Anomaly Buildup',     unit: 'bp' },
  ice_anomaly_buildup:       { label: 'Ice Anomaly Buildup',      unit: 'bp' },
  physical_anomaly_buildup:  { label: 'Physical Anomaly Buildup', unit: 'bp' },
  wind_anomaly_buildup:      { label: 'Wind Anomaly Buildup',     unit: 'bp' },

  // Anomaly Mastery / Proficiency (flat / pct variants)
  anomaly_mastery_flat:      { label: 'Anomaly Mastery',     unit: 'raw' },
  anomaly_mastery_pct:       { label: 'Anomaly Mastery %',   unit: 'bp'  },
  anomaly_proficiency_flat:  { label: 'Anomaly Proficiency', unit: 'raw' },

  // Anomaly-type-specific DMG bonuses
  shock_dmg_bonus:           { label: 'Shock DMG %',         unit: 'bp'  },
  disorder_dmg_bonus:        { label: 'Disorder DMG %',      unit: 'bp'  },
  disorder_duration_bonus_rate: { label: 'Disorder Duration DMG %/s', unit: 'bp' },
  vortex_dmg_bonus:          { label: 'Vortex DMG %',        unit: 'bp'  },

  // Abloom
  abloom_dmg_bonus:          { label: 'Abloom DMG %',        unit: 'bp'  },
  abloom_mv_bonus:           { label: 'Abloom MV %',         unit: 'bp'  },
  abloom_crit_rate:          { label: 'Abloom CRIT Rate',    unit: 'bp'  },
  abloom_crit_dmg:           { label: 'Abloom CRIT DMG',     unit: 'bp'  },
  // Kit-granted anomaly CRIT (#162). A pool distinct from `crit_rate`/`crit_dmg`
  // — disc CRIT never reaches anomaly damage — so it is labelled distinctly too.
  // Names match ZO's own `anom_crit_` / `anom_crit_dmg_` display strings.
  anomaly_crit_rate:         { label: 'Anomaly CRIT Rate',   unit: 'bp'  },
  anomaly_crit_dmg:          { label: 'Anomaly CRIT DMG',    unit: 'bp'  },

  // Sheer (Rupture) damage path
  sheer_dmg_bonus:           { label: 'Sheer DMG %',         unit: 'bp'  },
  sheer_force_flat:          { label: 'Sheer Force',         unit: 'raw' },

  // Stun-area / MV overrides
  stun_area_override:        { label: 'Stun DMG %',          unit: 'bp'  },
  stun_dmg_mult_bonus:       { label: 'Stun DMG %',          unit: 'bp'  },
  mv_crit_scaling:           { label: 'MV CRIT DMG Scaling', unit: 'bp'  },

  // Element DMG % (element not covered above)
  wind_dmg:                  { label: 'Wind DMG %',          unit: 'bp'  },

  // Remielle (Lumiflux, DESIGN_remielle.md §6.1/§7.1)
  refringe_flat_bonus_bp:    { label: 'Refringe Coefficient', unit: 'bp'  },

  // Fairy-internal sim markers (no ZO/display equivalent, D-KV21) — boolean
  // "set" flags, not scaled quantities; value is always 1.
  frostbite_frost_variant:   { label: 'Frostbite: Frost Variant', unit: 'raw' },
};

export function statMeta(stat: string): { label: string; unit: 'bp' | 'raw' } {
  return STAT_META[stat] ?? { label: stat, unit: 'raw' };
}

/** Format a basis-point or raw stat value for display. */
export function formatStatValue(stat: string, valueBp: number): string {
  const { unit } = statMeta(stat);
  const sign = valueBp >= 0 ? '+' : '';
  if (unit === 'bp') {
    return `${sign}${(valueBp / 100).toFixed(2)}%`;
  }
  return `${sign}${valueBp}`;
}

/** Return the in-game display label for a stat key. */
export function formatStatLabel(stat: string): string {
  return statMeta(stat).label;
}
