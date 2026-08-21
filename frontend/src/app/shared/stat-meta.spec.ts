import { describe, expect, it } from 'vitest';

import { STAT_KEYS_IN_USE } from './stat-keys.generated';
import { STAT_META } from './stat-meta';

/**
 * L3 — display coverage (Task 11, docs/TASKS_kit_validation.md).
 *
 * Every stat key a modifier JSON actually uses must have a STAT_META entry. A key without
 * one renders as a raw `FINAL_ATK_PCT +1000` chip instead of `ATK % +10.00%` — the visible
 * symptom of issue #62, where 25 keys were unmapped.
 *
 * The key list is GENERATED from the modifier JSONs (`stat-keys.generated.ts`, written by
 * backend/scripts/refresh_kit_refs.py), never hand-maintained here. A hardcoded list would
 * pass forever while the corpus drifted away from it, which is precisely the class of
 * silent rot this harness exists to prevent. A backend test asserts the generated file is
 * in sync with the corpus, so adding a kit JSON with a new key fails CI rather than
 * shipping a broken chip.
 */
describe('STAT_META display coverage (L3)', () => {
  it('covers every stat key used by a kit, W-Engine, or disc-set modifier', () => {
    const unmapped = STAT_KEYS_IN_USE.filter((key) => !(key in STAT_META));

    expect(
      unmapped,
      `stat keys used in modifier JSONs but missing from STAT_META — they would render as ` +
        `raw uppercase keys in the UI. Add them to stat-meta.ts using the in-game stat ` +
        `name (e.g. 'ATK %', not 'FINAL_ATK_PCT'): ${unmapped.join(', ')}`,
    ).toEqual([]);
  });

  it('gives every entry a label and a unit', () => {
    for (const [key, meta] of Object.entries(STAT_META)) {
      expect(meta.label, `${key} has no label`).toBeTruthy();
      expect(['bp', 'raw'], `${key} has an invalid unit`).toContain(meta.unit);
    }
  });

  it('labels stats with their in-game names, not their field keys', () => {
    // The convention that produced issue #62's fix: the UI speaks the game's language.
    expect(STAT_META['final_atk_pct'].label).toBe('ATK %');
    expect(STAT_META['crit_dmg'].label).toBe('CRIT DMG');
    expect(STAT_META['sheer_force_flat'].label).toBe('Sheer Force');
  });

  it('is what the generated manifest is for: an unknown key would be caught', () => {
    // Guards the guard — if STAT_KEYS_IN_USE were empty or stubbed, the coverage test
    // above would vacuously pass.
    expect(STAT_KEYS_IN_USE.length).toBeGreaterThan(40);
    expect(STAT_KEYS_IN_USE).toContain('final_atk_pct');
  });
});
