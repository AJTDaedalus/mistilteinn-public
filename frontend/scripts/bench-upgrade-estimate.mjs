/**
 * What the upgrade estimator's exact pass costs, per slot, on a realistic recipe.
 *
 *     node --import ./scripts/ts-resolve.mjs scripts/bench-upgrade-estimate.mjs
 *
 * `docs/TASKS_upgrade_estimator.md` Task 1. DESIGN §5.1 *reasoned* that brute force is ~10⁷
 * evaluations and that three reductions make it interactive; this measures it, because this
 * repo's record of inferred costs is a record of being wrong (`RESEARCH_pinned_search_cost.md`).
 * Node rather than a browser for the reason `bench-search.mjs` gives: the hot loop is plain V8
 * arithmetic with no WASM and no DOM.
 */

import { evaluateRecipe } from '../src/app/sim/recipe-eval.ts';
import { candidateStatsFrom, liveQuantitiesFor } from '../src/app/sim/recipe-search.ts';
import { newBeatCache, slotBeatProbability, weightSensitivity } from '../src/app/sim/upgrade-estimate.ts';
import { sampleBeatProbability } from '../src/app/sim/fresh-drop-sampler.ts';
import {
  CIRCLET, FLOWER, LADDERS, MAIN_VALUES, OTHERS, WEIGHTS, syntheticRecipe,
} from '../src/app/sim/upgrade-fixtures.ts';

const HITS = 245;
const recipe = syntheticRecipe(HITS);
const live = new Set(liveQuantitiesFor(recipe));

const SANDS = { hp_pct: 0.2668, atk_pct: 0.2666, def_pct: 0.2666, energy_recharge: 0.1, elemental_mastery: 0.1 };
const GOBLET = {
  hp_pct: 0.1925, def_pct: 0.19, atk_pct: 0.1925, elemental_mastery: 0.025,
  physical_dmg_bonus: 0.05, anemo_dmg_bonus: 0.05, geo_dmg_bonus: 0.05, electro_dmg_bonus: 0.05,
  hydro_dmg_bonus: 0.05, pyro_dmg_bonus: 0.05, cryo_dmg_bonus: 0.05, dendro_dmg_bonus: 0.05,
};
const values = { ...MAIN_VALUES, physical_dmg_bonus: 0.583, anemo_dmg_bonus: 0.466, geo_dmg_bonus: 0.466,
  electro_dmg_bonus: 0.466, pyro_dmg_bonus: 0.466, cryo_dmg_bonus: 0.466, dendro_dmg_bonus: 0.466 };

const MEDIOCRE_CIRCLET = { crit_dmg: 0.622, crit_rate: 0.07, atk_pct: 0.1, flat_def: 40 };
const equipped = [...OTHERS, MEDIOCRE_CIRCLET];

const cases = [
  ['flower', 0, FLOWER],
  ['sands', 2, SANDS],
  ['goblet', 3, GOBLET],
  ['circlet', 4, CIRCLET],
];

console.log(`recipe: ${HITS} hits; live: ${[...live].join(', ')}`);
for (const strength of ['as equipped', 'strong (+15% per slot)']) {
  for (const [name, slot, mains] of cases) {
    const evaluate = (piece) => {
      const pools = [...equipped];
      pools[slot] = piece;
      return evaluateRecipe(recipe, candidateStatsFrom(pools));
    };
    const reference = evaluateRecipe(recipe, candidateStatsFrom(equipped));
    const threshold = reference * 1.01 * (strength.startsWith('strong') ? 1.15 : 1);
    const input = {
      mainStatProbabilities: mains, mainStatValues: values, substatWeights: WEIGHTS,
      ladders: LADDERS, fourLineShare: 0.2, live, evaluate, threshold,
    };
    const cache = newBeatCache();
    const t0 = performance.now();
    const found = slotBeatProbability(input, cache);
    const t1 = performance.now();
    const range = weightSensitivity(input, cache);
    const t2 = performance.now();
    let mc = '';
    if (found.pBeat > 5e-3) {
      const s = sampleBeatProbability({ mainStatProbabilities: mains, mainStatValues: values,
        substatWeights: WEIGHTS, ladders: LADDERS, fourLineShare: 0.2 }, evaluate, threshold, 40_000, 1);
      mc = ` | MC ${s.p.toExponential(3)} [${s.low.toExponential(2)}, ${s.high.toExponential(2)}]`;
    }
    console.log(
      `${strength.padEnd(22)} ${name.padEnd(8)} P(beat|slot)=${found.pBeat.toExponential(3)} `
      + `questions=${found.questions} evals=${found.evaluations} ${(t1 - t0).toFixed(0)} ms; `
      + `±1 weights [${range.low.toExponential(2)}, ${range.high.toExponential(2)}] +${(t2 - t1).toFixed(0)} ms${mc}`,
    );
  }
}
