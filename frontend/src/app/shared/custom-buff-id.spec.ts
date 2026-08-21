import { describe, expect, it } from 'vitest';

import { customBuffId, isUnaddressableLabel, slugify } from './custom-buff-id';

/**
 * Cross-language parity fixture (#64).
 *
 * Every case here is also asserted against the Python implementation in
 * `backend/tests/unit/test_custom_buff_synthesis.py` / `test_custom_buff_slug_parity.py`.
 * The two implementations exist because `disabled_buffs` ids are composed client-side
 * (the stage-buff toggle) and consumed server-side (the synthesiser) — if they disagree,
 * switching a stage buff off silently stops working, which is the one thing a toggle may
 * not do.
 */
const PARITY_CASES: readonly (readonly [string, string])[] = [
  ['DA Stage 3: Ice DMG', 'da_stage_3_ice_dmg'],
  ['DA stage 3 — ice dmg', 'da_stage_3_ice_dmg'],
  ['Stage 3 ATK', 'stage_3_atk'],
  ['stage-3-atk', 'stage_3_atk'],
  ['  leading and trailing  ', 'leading_and_trailing'],
  ['🔥 3', '3'],
  ['Shiyu 2.1 Node 2', 'shiyu_2_1_node_2'],
];

describe('slugify', () => {
  it.each(PARITY_CASES)('slugs %s to %s, exactly as the backend does', (label, expected) => {
    expect(slugify(label)).toBe(expected);
  });

  it('collapses runs of punctuation rather than emitting empty segments', () => {
    expect(slugify('a  ---  b')).toBe('a_b');
  });
});

describe('customBuffId', () => {
  it('is the `custom:` prefix plus the slug — the id disabled_buffs holds', () => {
    expect(customBuffId('DA Stage 3: Ice DMG')).toBe('custom:da_stage_3_ice_dmg');
  });

  it('is stable across calls, so a switched-off buff stays switched off', () => {
    expect(customBuffId('DA Stage 3: Ice DMG')).toBe(customBuffId('DA Stage 3: Ice DMG'));
  });

  it('is NOT agent-qualified, unlike a kit buff id', () => {
    // A stage buff belongs to the encounter, not to an agent: qualifying it would
    // switch it off for the DPS and leave it on for the supports.
    expect(customBuffId('x')).not.toMatch(/^\d+:/);
  });
});

describe('isUnaddressableLabel', () => {
  it.each(['!!!', '🔥', '   ', '---'])('flags %s, which the server 422s on', (label) => {
    expect(isUnaddressableLabel(label)).toBe(true);
  });

  it('accepts a label with a single alphanumeric — the rejection is narrow on purpose', () => {
    expect(isUnaddressableLabel('🔥 3')).toBe(false);
  });
});
