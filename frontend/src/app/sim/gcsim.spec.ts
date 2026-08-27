import { describe, expect, it, vi } from 'vitest';

import { configError, run, simulationError, type GcsimModule } from './gcsim';

/**
 * W.1 — the runner's logic, against a stub.
 *
 * **The real wasm is not here**, for the reason `damage.spec.ts` gives: it is a 41 MB artifact
 * read from disk, and Angular's test builder targets the browser where `node:fs` does not
 * exist. `scripts/verify-gcsim-runner.mjs` drives the real build through *this same module*
 * as its own CI step.
 *
 * What a stub can prove and the wasm gate cannot is the **negative space**: that a rejected
 * config throws rather than returning a plausible zero, that the iteration loop runs the
 * count it was asked for rather than the one in the config text, and that an absent result
 * block comes back null rather than 0.
 */

/** A gcsim stub. `flush` returns whatever the test wants gcsim to have said. */
function stub(out: unknown, validated: unknown = { parsed: true }): GcsimModule {
  return {
    validateConfig: vi.fn(() => validated),
    // Unused by `run`, which drives simulate/aggregate. A recipe is built from `sample`.
    sample: vi.fn(() => '{}'),
    initializeAggregator: vi.fn(),
    initializeWorker: vi.fn(),
    simulate: vi.fn(() => new Uint8Array([1, 2, 3])),
    aggregate: vi.fn(),
    flush: vi.fn(() => JSON.stringify(out)),
  };
}

const OK = { stats: { total_damage: { mean: 108.5 }, dps: { mean: 707.2, sd: 86.9 } } };

describe('configError', () => {
  it('reports null for the parsed config a successful validate returns', () => {
    // The mistake this exists to prevent: `validateConfig` returns the *parsed config* on
    // success, so a truthiness check rejects every valid config. A large truthy object is
    // what success looks like.
    expect(configError({ characters: [{ base: { key: 'ayaka' } }] })).toBeNull();
    expect(configError('{"targets":[{"level":90}]}')).toBeNull();
  });

  it('reports the complaint when gcsim embedded one', () => {
    expect(configError('{"error":"unknown character bogus"}')).toContain('bogus');
  });
});

describe('simulationError', () => {
  it('reports a string return as the failure it is', () => {
    // `simulate()` signals failure by *returning* a string where a Uint8Array was expected.
    expect(simulationError('{"error":"requested next char xiangling is not active"}'))
      .toContain('xiangling');
  });

  it('reports null for the byte array a successful run returns', () => {
    expect(simulationError(new Uint8Array([1, 2, 3]))).toBeNull();
  });
});

describe('run', () => {
  it('simulates exactly the count it was asked for, not the one in the config', () => {
    // `iteration=N` in the config text does not drive `simulate()`; the caller loops. A
    // runner that trusted the text would run once and report it as a hundred.
    const mod = stub(OK);
    run(mod, 'options iteration=100;', 7);
    expect(mod.simulate).toHaveBeenCalledTimes(7);
    expect(mod.aggregate).toHaveBeenCalledTimes(7);
    expect(mod.initializeWorker).toHaveBeenCalledTimes(1);
    expect(mod.flush).toHaveBeenCalledTimes(1);
  });

  it('reports progress once per iteration, ending at the total', () => {
    const seen: [number, number][] = [];
    run(stub(OK), 'cfg', 3, (done, total) => seen.push([done, total]));
    expect(seen).toEqual([[1, 3], [2, 3], [3, 3]]);
  });

  it('throws on a rejected config rather than returning a plausible zero', () => {
    // A comparison that swallowed this would rank every candidate at 0 and present the tie
    // as a finding.
    expect(() => run(stub(OK, '{"error":"bad"}'), 'cfg', 1)).toThrow(/rejected/);
  });

  it('does not simulate at all when the config was rejected', () => {
    const mod = stub(OK, '{"error":"bad"}');
    expect(() => run(mod, 'cfg', 1)).toThrow();
    expect(mod.simulate).not.toHaveBeenCalled();
    expect(mod.initializeWorker).not.toHaveBeenCalled();
  });

  it.each([0, -1, 1.5, Number.NaN])('refuses a nonsense iteration count: %s', (n) => {
    expect(() => run(stub(OK), 'cfg', n)).toThrow(/positive integer/);
  });

  it('reads the two numbers a comparison needs', () => {
    const got = run(stub(OK), 'cfg', 2);
    expect(got).toMatchObject({
      iterations: 2,
      totalDamage: 108.5,
      dps: { mean: 707.2, sd: 86.9 },
    });
  });

  it('reports an absent block as null, never as zero', () => {
    // Zero damage is a real answer — a rotation that never connects. Collapsing "gcsim did
    // not report this" into it hides a shape change behind a plausible number, which is how
    // a ranking comes out flat and looks deliberate.
    const got = run(stub({ stats: {} }), 'cfg', 1);
    expect(got.totalDamage).toBeNull();
    expect(got.dps).toBeNull();
  });

  it('keeps gcsim’s own result, so a caller can read what this does not model', () => {
    expect(run(stub(OK), 'cfg', 1).raw).toEqual(OK);
  });

  it('surfaces a failed simulation instead of aggregating the error string', () => {
    // The bug this replaces: passing `simulate()`'s error string to `aggregate()` aggregates
    // nothing, and `flush()` then fails with "index out of range [0] with length 0" — the
    // real cause discarded and replaced by a description of the empty aggregate. It hid
    // "requested next char X is not active and next action is not swap" for an hour.
    const mod = stub(OK);
    mod.simulate = vi.fn(() => '{"error":"requested next char xiangling is not active"}');

    expect(() => run(mod, 'cfg', 3)).toThrow(/xiangling/);
    expect(mod.aggregate).not.toHaveBeenCalled();
  });

  it('stops at the first failed iteration rather than running the rest', () => {
    const mod = stub(OK);
    let calls = 0;
    mod.simulate = vi.fn(() => (++calls === 2 ? '{"error":"boom"}' : new Uint8Array([1])));

    expect(() => run(mod, 'cfg', 10)).toThrow(/boom/);
    expect(calls).toBe(2);
  });

  it('surfaces a failed aggregate rather than reading zeros off it', () => {
    const mod = stub({ error: 'index out of range [0] with length 0' });

    expect(() => run(mod, 'cfg', 1)).toThrow(/index out of range/);
  });
});
