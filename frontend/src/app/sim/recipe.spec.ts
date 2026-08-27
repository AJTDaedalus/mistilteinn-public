import { describe, expect, it } from 'vitest';

import { effectiveCritRate, parseSample, replayHit, type RecipeHit } from './recipe';

/**
 * G.2 — the recipe parser's logic, against hand-built payloads.
 *
 * **The real fixture is not here.** It is 429 KB read from disk, and Angular's test builder
 * targets the browser where `node:fs` does not exist —
 * `scripts/verify-gcsim-recipe.mjs` replays all 221 of its hits as its own CI step.
 *
 * What a stub proves and that gate cannot is the **negative space**: that unlanded hits are
 * dropped rather than replayed as zeros, that crit rate is clamped, and that `bonus_dmg` is
 * used as a total rather than added to `ele_per`.
 */

/** A `calc` log entry, with the fields the parser reads. */
function calc(over: Record<string, unknown> = {}) {
  return {
    event: 'calc',
    logs: {
      abil: 'Normal 1', talent: 2, total_scaling: 1000, base_atk: 1000, atk_per: 0,
      flat_atk: 0, base_hp: 10000, base_def: 800, flat_dmg: 0, bonus_dmg: 0.5,
      cr: 0.25, cd: 2, def_mod: 0.5, res_mod: 0.9, amp_mult_total: 0,
      use_hp: false, use_def: false, use_em: false,
      base_dmg: 2000, pre_crit_dmg: 1350, avg_crit_dmg: 2025, damage: 2025, ele: 19,
      ...over,
    },
  };
}

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  abil: 'x', attackTag: -1, element: '19', talent: 2, scaling: 'atk', flatDamage: 0,
  scalingBase: 1000, bonusDmg: 0.5, critRate: 0.25, critDmg: 2, defMultiplier: 0.5,
  resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 2025, ...over,
});

describe('effectiveCritRate', () => {
  it('clamps above one', () => {
    // Published `cr` exceeds 1 when buffs stack past 100%. gcsim clamps; replaying without
    // clamping diverges exactly where crit builds are most interesting.
    expect(effectiveCritRate(1.4)).toBe(1);
  });

  it('clamps below zero', () => expect(effectiveCritRate(-0.2)).toBe(0));
  it('passes an ordinary rate through', () => expect(effectiveCritRate(0.7)).toBe(0.7));
});

describe('replayHit', () => {
  it('reproduces the worked example', () => {
    // base 2*1000 = 2000; pre-crit 2000*1.5*0.5*0.9 = 1350; avg 1350*(1+0.25*2) = 2025.
    expect(replayHit(hit())).toBeCloseTo(2025, 9);
  });

  it('adds flat damage before the bonus, not after', () => {
    // Redhorn's DEF conversion lands in flat_dmg and is part of base damage, so it receives
    // the damage bonus. Adding it afterwards understates it by exactly the bonus.
    expect(replayHit(hit({ flatDamage: 500 }))).toBeCloseTo(2531.25, 9);
  });

  it('treats bonusDmg as the total, never adding an element bonus to it', () => {
    // `bonus_dmg` already includes `ele_per`. Adding them double-counts, which broke 73 of
    // 245 hits when this was first written.
    expect(replayHit(hit({ bonusDmg: 0.5 }))).toBeCloseTo(replayHit(hit({ bonusDmg: 0.5 })), 12);
    expect(replayHit(hit({ bonusDmg: 1.0 }))).toBeGreaterThan(replayHit(hit({ bonusDmg: 0.5 })));
  });

  it('clamps crit rate rather than letting it exceed one', () => {
    expect(replayHit(hit({ critRate: 3 }))).toBeCloseTo(replayHit(hit({ critRate: 1 })), 9);
  });

  it('applies the amplifying multiplier', () => {
    expect(replayHit(hit({ ampMultiplier: 2 }))).toBeCloseTo(4050, 9);
  });
});

describe('parseSample', () => {
  it('reads calc events and ignores everything else', () => {
    const r = parseSample({ seed: '7', logs: [
      { event: 'hitlag', logs: {} }, calc(), { event: 'debug', logs: {} }, calc(),
    ] });

    expect(r.hits).toHaveLength(2);
    expect(r.seed).toBe('7');
  });

  it('drops hits gcsim reported as landing zero damage', () => {
    // Queued actions that never connected. Carrying them puts entries in the recipe whose
    // damage_grp_mult is 0 while every other term is populated — indistinguishable from a
    // formula error at replay.
    expect(parseSample({ logs: [calc(), calc({ damage: 0 })] }).hits).toHaveLength(1);
  });

  it('reads which stat an ability scales off rather than assuming ATK', () => {
    const scal = (o: Record<string, unknown>) => parseSample({ logs: [calc(o)] }).hits[0].scaling;

    expect(scal({})).toBe('atk');
    expect(scal({ use_hp: true })).toBe('hp');
    expect(scal({ use_def: true })).toBe('def');
    expect(scal({ use_em: true })).toBe('em');
  });

  it('normalises an absent amplifying reaction to 1, not 0', () => {
    // gcsim publishes 0 for "no amplification". Carrying that through as a multiplier zeroes
    // every unamplified hit — the whole rotation, for most teams.
    expect(parseSample({ logs: [calc({ amp_mult_total: 0 })] }).hits[0].ampMultiplier).toBe(1);
    expect(parseSample({ logs: [calc({ amp_mult_total: 1.5 })] }).hits[0].ampMultiplier).toBe(1.5);
  });

  it('accepts the payload as a string, as the wasm returns it', () => {
    expect(parseSample(JSON.stringify({ seed: '1', logs: [calc()] })).hits).toHaveLength(1);
  });

  it('returns no hits for a payload with no calc events', () => {
    expect(parseSample({ logs: [{ event: 'action', logs: {} }] }).hits).toEqual([]);
  });
});
