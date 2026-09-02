import { describe, expect, it } from 'vitest';

import { NO_STATS, evaluateHit } from './recipe-eval';
import {
  effectiveCritRate,
  parseSample,
  replayHit,
  resolveConversions,
  stabilityFrom,
  type RecipeHit,
} from './recipe';

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

/** A `damage` log entry — carries what `calc` omits. */
function dmg(over: Record<string, unknown> = {}) {
  return { event: 'damage', logs: { abil: 'Normal 1', ele: 'cryo', 'attack-tag': 1, ...over } };
}

/**
 * A `calc` log entry, with the fields the parser reads.
 *
 * `charIndex` rides on the **envelope**, where gcsim puts it — not in the payload. The parser
 * reads it from there to decide whose hit this is.
 */
function calc(over: Record<string, unknown> = {}, charIndex = 0) {
  return {
    event: 'calc',
    char_index: charIndex,
    logs: {
      abil: 'Normal 1', talent: 2, total_scaling: 1000, base_atk: 1000, atk_per: 0,
      flat_atk: 0, base_hp: 10000, base_def: 800, flat_dmg: 0, flat_hp: 0, flat_def: 0,
      bonus_dmg: 0.5,
      cr: 0.25, cd: 2, def_mod: 0.5, res_mod: 0.9, amp_mult_total: 0,
      use_hp: false, use_def: false, use_em: false,
      base_dmg: 2000, pre_crit_dmg: 1350, avg_crit_dmg: 2025, damage: 2025, ele: 19,
      ...over,
    },
  };
}

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true,
  owner: 0,
  abil: 'x', attackTag: -1, element: '19', talent: 2, scaling: 'atk', flatDamage: 0,
  conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  calibratedScaling: 1000, bonusDmg: 0.5, critRate: 0.25, critDmg: 2, defMultiplier: 0.5,
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

  it('takes element and attack tag from the paired damage event', () => {
    // `calc.ele` is gcsim's internal enum (19, 14) and is meaningless outside gcsim. G.4
    // needs the real name to decide which of a candidate's element bonuses reach which hit.
    const r = parseSample({ logs: [dmg({ ele: 'pyro', 'attack-tag': 4 }), calc()] });

    expect(r.hits[0].element).toBe('pyro');
    expect(r.hits[0].attackTag).toBe(4);
  });

  it('pairs by position across many hits', () => {
    const r = parseSample({ logs: [
      dmg({ abil: 'A', ele: 'cryo' }), calc({ abil: 'A' }),
      dmg({ abil: 'B', ele: 'geo' }), calc({ abil: 'B' }),
    ] });

    expect(r.hits.map((h) => [h.abil, h.element])).toEqual([['A', 'cryo'], ['B', 'geo']]);
  });

  it('refuses a broken pairing rather than mislabelling every element', () => {
    // Silently mislabelling is the wrong-but-plausible failure: the numbers still replay, and
    // only the bonuses G.4 matches to them would be wrong.
    expect(() => parseSample({ logs: [
      dmg({ abil: 'A' }), calc({ abil: 'B' }),
    ] })).toThrow(/pairing broke/);
  });
});


describe('stabilityFrom', () => {
  it('calls a rotation with no spread stable', () => {
    expect(stabilityFrom({ Burst: { mean: 2, sd: 0 }, Normal: { mean: 30, sd: 0 } }))
      .toEqual({ stable: true, unstable: [] });
  });

  it('names the source that varies', () => {
    // The transition band: burst count 2 or 3 depending on the seed. No single recipe
    // describes it, and RESEARCH_er_bucketing measured that band at 13.3% DPS spread.
    expect(stabilityFrom({ Burst: { mean: 2.75, sd: 0.44 }, Normal: { mean: 30, sd: 0 } }))
      .toEqual({ stable: false, unstable: ['Burst'] });
  });

  it('tolerates the timing jitter every rotation has', () => {
    // Non-burst counts wobble ~3% from timing alone; treating that as instability would call
    // every rotation unusable.
    expect(stabilityFrom({ Normal: { mean: 30, sd: 0.3 } }, 0.05).stable).toBe(true);
  });

  it('takes the tolerance as a parameter rather than burying it', () => {
    // sd/mean = 3/30 = 0.10 — unstable at a 5% threshold, stable at a 50% one.
    const sources = { Normal: { mean: 30, sd: 3 } };

    expect(stabilityFrom(sources, 0.05).stable).toBe(false);
    expect(stabilityFrom(sources, 0.5).stable).toBe(true);
  });

  it('ignores a source that never landed rather than dividing by zero', () => {
    expect(stabilityFrom({ Never: { mean: 0, sd: 0 } }).stable).toBe(true);
  });
});

describe('staleConversions', () => {
  const withFlat = (over: Record<string, unknown>) =>
    parseSample({ logs: [dmg(), calc(over)] }).meta.staleConversions;

  it('reports nothing when the calibration carries no conversion', () => {
    expect(parseSample({ logs: [dmg(), calc()] }).meta.staleConversions).toEqual([]);
  });

  it('flags flat damage, which is how Redhorn Stonethresher goes stale', () => {
    // Redhorn's flat damage is 40% of DEF, computed at calibration and frozen there. A
    // candidate with different DEF gets a number gcsim never computed for it.
    const found = withFlat({ flat_dmg: 500 });

    expect(found).toHaveLength(1);
    expect(found[0]).toMatchObject({ term: 'flatDamage', hits: 1, damageShare: 1 });
  });

  it('flags flat ATK, which is how Homa and a DEF-to-ATK burst go stale', () => {
    expect(withFlat({ flat_atk: 300 }).map((c) => c.term)).toEqual(['flatAtk']);
  });

  it('reports several terms at once', () => {
    expect(withFlat({ flat_dmg: 1, flat_atk: 2 }).map((c) => c.term))
      .toEqual(['flatDamage', 'flatAtk']);
  });

  it('reports the damage share, because a hit count alone is not actionable', () => {
    // 83 hits carrying 2% of the damage is a footnote; 5 hits carrying 40% is not.
    const r = parseSample({ logs: [
      dmg({ abil: 'A' }), calc({ abil: 'A', flat_dmg: 5, avg_crit_dmg: 100 }),
      dmg({ abil: 'B' }), calc({ abil: 'B', avg_crit_dmg: 300 }),
    ] });

    expect(r.meta.staleConversions[0].damageShare).toBeCloseTo(0.25, 9);
  });
});


describe("a teammate's hits belong to a build that is not being optimized", () => {
  /**
   * **The bug this was found by measuring**, on the owner's Skirk / Furina / Yelan / Citlali
   * rotation. Teammates were **85.9% of the damage**, and applying a candidate's stats to
   * every hit meant most of the gain a candidate appeared to give was applied to Furina's
   * damage — which no artifact of Skirk's can move.
   *
   * The config says so plainly: the calibrated character gets `add stats er=0.3`, while
   * teammates carry their whole equipped stat line.
   */
  it("freezes a teammate's hit at what gcsim measured", () => {
    const mine = hit({ mine: true, talent: 2, gcsimAverageDamage: 1000 });
    const theirs = hit({ mine: false, talent: 2, gcsimAverageDamage: 1000 });
    const buffed = { ...NO_STATS, atkPercent: 0.5, critRate: 0.3, critDmg: 1 };

    expect(evaluateHit(theirs, buffed)).toBe(1000);
    expect(evaluateHit(mine, buffed)).not.toBe(evaluateHit(mine, NO_STATS));
  });

  it('reads whose hit it is from the log envelope', () => {
    // `char_index` sits beside `event`, not inside `logs`. Reading it from the payload gives
    // `undefined` for every hit — the same nesting mistake that made an earlier count of the
    // flat fields report them all as zero.
    const parsed = parseSample({ logs: [
      dmg(), calc({}, 0), dmg(), calc({}, 2),
    ] });

    expect(parsed.hits.map((h) => h.mine)).toEqual([true, false]);
  });

  it("does not report a teammate's flat stats as an unresolved conversion", () => {
    // `furina add stats atk=311 … hp=6035 …` is her equipped gear, not a conversion. Counting
    // it reported the whole team's frozen stats as unresolvable — 89.3% of the damage on the
    // owner's rotation, every point of it a teammate's.
    const theirs = parseSample({ logs: [
      dmg(), calc({ flat_atk: 311, flat_hp: 6035, flat_def: 74 }, 1),
    ] });

    expect(theirs.meta.staleConversions).toEqual([]);
  });

  it('still reports one on the calibrated character', () => {
    // The other half: this must not silence a term that genuinely belongs to the build.
    const mine = parseSample({ logs: [
      dmg(), calc({ flat_atk: 311, flat_hp: 6035, flat_def: 74 }, 0),
    ] });

    expect(mine.meta.staleConversions.map((s) => s.term).sort())
      .toEqual(['flatAtk', 'flatDef', 'flatHp']);
  });

  it("does not try to resolve a conversion on a hit the probe cannot move", () => {
    // The probe perturbs the calibrated character's stat line and nobody else's, so a
    // teammate's hit is identical in both runs and has nothing to identify.
    const mk = (flat: number, defPct: number) =>
      parseSample({ logs: [dmg(), calc({ flat_dmg: flat, def_per: defPct }, 1)] });

    expect(resolveConversions(mk(100, 0), mk(150, 0.5)))
      .toEqual({ resolved: 0, unresolved: 0, constant: 0 });
  });
});

describe('resolveConversions', () => {
  it('calls a term the probe never moved constant, not unresolvable', () => {
    // **The matcher cannot answer this question**, which is why it is asked before the
    // matcher runs: a stat is a candidate only when the probe *moved* it, so a term with a
    // ratio of 1 matches nothing by construction and was counted unresolved for ever.
    //
    // Measured on the owner's team: 183 of the subject's 198 flat-carrying hits do not move
    // under the probe. Flat ATK that is simply flat is not an unresolvable conversion — it is
    // a constant, `resolvedTerm` returns the calibration's value, and the candidate's own flat
    // is added on top. There is nothing to warn about.
    const mk = (atkPct: number) => parseSample({ logs: [
      dmg(), calc({ flat_atk: 311, atk_per: atkPct }),
    ] });

    const baseline = mk(0);
    const out = resolveConversions(baseline, mk(0.5));

    expect(out).toEqual({ resolved: 0, unresolved: 0, constant: 1 });
    expect(baseline.hits[0].constantTerms).toContain('flatAtk');
    expect(baseline.meta.staleConversions).toEqual([]);
  });

  it("does not report a teammate's flat stats as an unresolvable conversion", () => {
    // The owner saw `flatAtk`, `flatHp` and `flatDef` each reported against 96.6 % of the
    // damage on a team whose subject carried no unresolved term at all. Every point of it was
    // a teammate's equipped gear — `furina add stats atk=311 …` in the config — which is not a
    // conversion and which no search can move.
    //
    // The rule was already stated twice: `staleConversionsIn` filters on `mine`, and the
    // resolution loop itself does `if (!b.mine) continue`. Only the reporter that runs *after*
    // the resolver was missing it, and it overwrites what the other two produced — so the
    // resolver skipped every teammate and the reporter then counted every one as unresolved.
    const sample = (flat: number) => parseSample({ logs: [
      dmg(),
      calc({ flat_atk: 0 }, 0),
      dmg(),
      calc({ flat_atk: flat }, 1),
    ] });

    const baseline = sample(311);
    resolveConversions(baseline, sample(311));

    expect(baseline.hits.some((h) => !h.mine)).toBe(true);
    expect(baseline.meta.staleConversions).toEqual([]);
  });

  const pair = (baseFlat: number, probeFlat: number, probeDefPercent: number) => {
    const mk = (flat: number, defPct: number) => parseSample({ logs: [
      dmg(), calc({ flat_dmg: flat, def_per: defPct }),
    ] });
    return [mk(baseFlat, 0), mk(probeFlat, probeDefPercent)] as const;
  };

  it('identifies the stat a frozen term was converted from', () => {
    // base DEF 800; probe at +50% → 1200, a ratio of 1.5. A flat term moving by the same 1.5
    // came from DEF, and nothing else the probe moved did.
    const [baseline, probe] = pair(100, 150, 0.5);
    const r = resolveConversions(baseline, probe);

    expect(r).toEqual({ resolved: 1, unresolved: 0, constant: 0 });
    expect(baseline.hits[0].conversions.flatDamage)
      .toEqual({ from: 'def', perUnit: 100 / 800 });
  });

  it('leaves a term unresolved when nothing the probe moved matches it', () => {
    // A snapshotted conversion looks like this: the term moves by a factor no hit-time stat
    // ratio equals, because it was computed at cast rather than at this hit.
    const [baseline, probe] = pair(100, 123, 0.5);

    expect(resolveConversions(baseline, probe)).toEqual({ resolved: 0, unresolved: 1, constant: 0 });
    expect(baseline.hits[0].conversions.flatDamage).toBeUndefined();
  });

  it('refuses to choose when the probe moved two stats by the same factor', () => {
    // Both ATK and DEF at +50%, and a flat term that also moved x1.5. Nothing in the data
    // says which it came from, and picking one would put a confident wrong number in every
    // hit that carries the term — wrong in exactly the cases where the two stats diverge.
    const mk = (flat: number, pct: number) => parseSample({ logs: [
      dmg(), calc({ flat_dmg: flat, atk_per: pct, def_per: pct }),
    ] });
    const baseline = mk(100, 0);
    const probe = mk(150, 0.5);

    expect(resolveConversions(baseline, probe)).toEqual({ resolved: 0, unresolved: 1, constant: 0 });
    expect(baseline.hits[0].conversions.flatDamage).toBeUndefined();
  });

  it('resolves an ATK conversion, which a DEF-only probe never could', () => {
    // **The reason the probe moves all three** (2026-08-31). It moved `def%` alone, so a term
    // derived from ATK had ratio 1 against the only moved stat and matched nothing — it was
    // reported as "a conversion no probe could resolve" and frozen, on every ATK scaler.
    //
    // Base ATK 1000 at +50% is 1500, a ratio of 1.5. HP and DEF move by different factors, so
    // exactly one candidate matches and the term is identified rather than refused.
    const mk = (flat: number, atkPct: number, hpPct: number, defPct: number) =>
      parseSample({ logs: [
        dmg(),
        calc({ flat_dmg: flat, atk_per: atkPct, hp_per: hpPct, def_per: defPct }),
      ] });
    const baseline = mk(100, 0, 0, 0);
    const probe = mk(150, 0.5, 0.3, 0.7);

    expect(resolveConversions(baseline, probe)).toEqual({ resolved: 1, unresolved: 0, constant: 0 });
    expect(baseline.hits[0].conversions.flatDamage)
      .toEqual({ from: 'atk', perUnit: 100 / 1000 });
  });

  it('still refuses when two of the three happen to move a term by the same ratio', () => {
    // Distinct deltas make a collision unlikely, not impossible: a stat's ratio is
    // `1 + base * delta / total`, so two stats with different deltas can still coincide.
    // That has to stay safe rather than become a guess — here `atk%` and `hp%` both move by
    // +0.5, and because each is a percentage of its own base both totals land on x1.5.
    const mk = (flat: number, atkPct: number, hpPct: number) => parseSample({ logs: [
      dmg(), calc({ flat_dmg: flat, atk_per: atkPct, hp_per: hpPct }),
    ] });
    const baseline = mk(100, 0, 0);
    const probe = mk(150, 0.5, 0.5);

    expect(resolveConversions(baseline, probe)).toEqual({ resolved: 0, unresolved: 1, constant: 0 });
    expect(baseline.hits[0].conversions.flatDamage).toBeUndefined();
  });

  it('leaves a term unresolved when the probe moved nothing', () => {
    const [baseline, probe] = pair(100, 100, 0);

    expect(resolveConversions(baseline, probe).resolved).toBe(0);
  });

  it('refuses a probe that changed the rotation', () => {
    const baseline = parseSample({ logs: [dmg(), calc()] });
    const probe = parseSample({ logs: [dmg(), calc(), dmg(), calc()] });

    expect(() => resolveConversions(baseline, probe)).toThrow(/changed the rotation/);
  });

  it('drops a resolved term from the stale list', () => {
    // A warning about something that was fixed is one everybody learns to ignore.
    const [baseline, probe] = pair(100, 150, 0.5);
    expect(baseline.meta.staleConversions).toHaveLength(1);

    resolveConversions(baseline, probe);

    expect(baseline.meta.staleConversions).toEqual([]);
  });

  it('keeps an unresolved term in the stale list', () => {
    const [baseline, probe] = pair(100, 123, 0.5);
    resolveConversions(baseline, probe);

    expect(baseline.meta.staleConversions.map((c) => c.term)).toEqual(['flatDamage']);
  });
});
