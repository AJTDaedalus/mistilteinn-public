/**
 * The oracle: generate fresh drops the way the game does, one roll at a time, and count.
 *
 * `docs/TASKS_upgrade_estimator.md` Task 5; `docs/DESIGN_upgrade_estimator.md` §5.3. **Test-only
 * — no page imports this.** `rg fresh-drop-sampler src/app/pages` must stay empty; a spec cannot
 * check it, because specs compile for the browser and have no `node:fs`.
 *
 * A Monte Carlo cannot see a probability of 10⁻⁵, which is why `upgrade-estimate.ts`
 * enumerates; this exists to check the enumeration on cases where the probability is large
 * enough to sample.
 *
 * ## Deliberately naive, and deliberately separate
 *
 * It shares **no code** with `fresh-drop.ts` or `upgrade-estimate.ts` beyond the data it is
 * handed and the evaluator. No collapsing of draw orders into sets, no roll budgets, no
 * multinomials, no bounds: the main stat, then each line drawn by weight from what is left,
 * then each upgrade either creating the fourth line or picking a line uniformly, every roll a
 * uniform tier. If the clever version and this one agree, it is not because they made the same
 * mistake in the same helper.
 */

/** Everything the sampler draws from. The same tables the estimator reads, nothing derived. */
export interface SamplerModel {
  mainStatProbabilities: Readonly<Record<string, number>>;
  mainStatValues: Readonly<Record<string, number>>;
  substatWeights: Readonly<Record<string, number>>;
  /** Roll tiers per substat, ascending — the 5-star ladders. */
  ladders: Readonly<Record<string, readonly number[]>>;
  fourLineShare: number;
}

/** mulberry32: a small seeded PRNG, so a failing run can be replayed exactly. */
export function seededRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickWeighted(entries: readonly (readonly [string, number])[], random: () => number): string {
  const total = entries.reduce((sum, [, w]) => sum + w, 0);
  let x = random() * total;
  for (const [key, w] of entries) {
    x -= w;
    if (x < 0) return key;
  }
  return entries[entries.length - 1][0];
}

/** One fully levelled 5-star for the slot, as a stat pool: main stat plus summed substats. */
export function sampleFreshDrop(model: SamplerModel, random: () => number): Record<string, number> {
  const main = pickWeighted(Object.entries(model.mainStatProbabilities), random);
  const stats: Record<string, number> = { [main]: model.mainStatValues[main] };
  const lines: string[] = [];

  const roll = (quantity: string): void => {
    const tiers = model.ladders[quantity];
    stats[quantity] = (stats[quantity] ?? 0) + tiers[Math.floor(random() * tiers.length)];
  };
  const addLine = (): void => {
    const left = Object.entries(model.substatWeights)
      .filter(([q]) => q !== main && !lines.includes(q));
    const quantity = pickWeighted(left, random);
    lines.push(quantity);
    roll(quantity);
  };

  const initial = random() < model.fourLineShare ? 4 : 3;
  for (let i = 0; i < initial; i += 1) addLine();
  for (let upgrade = 0; upgrade < 5; upgrade += 1) {
    if (lines.length < 4) addLine();
    else roll(lines[Math.floor(random() * lines.length)]);
  }
  return stats;
}

/** The sampled `P(evaluate(drop) > threshold)` and its 99.9% Wilson interval. */
export interface SampledBeat {
  p: number;
  low: number;
  high: number;
  samples: number;
}

export function sampleBeatProbability(
  model: SamplerModel,
  evaluate: (piece: Readonly<Record<string, number>>) => number,
  threshold: number,
  samples: number,
  seed: number,
): SampledBeat {
  const random = seededRandom(seed);
  let hits = 0;
  for (let i = 0; i < samples; i += 1) {
    if (evaluate(sampleFreshDrop(model, random)) > threshold) hits += 1;
  }
  const p = hits / samples;
  // Wilson score interval, z for 99.9% two-sided.
  const z = 3.2905;
  const z2 = z * z;
  const centre = (p + z2 / (2 * samples)) / (1 + z2 / samples);
  const half = (z / (1 + z2 / samples)) * Math.sqrt((p * (1 - p)) / samples + z2 / (4 * samples ** 2));
  return { p, low: Math.max(0, centre - half), high: Math.min(1, centre + half), samples };
}
