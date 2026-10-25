/**
 * Shared spec fixtures for the upgrade estimator: the real 5-star tables, in kernel quantities.
 *
 * **Test-only.** The roll ladders are the game-data values (`ReliquaryAffixExcelConfigData`, as
 * transcribed in `docs/RESEARCH_artifact_drop_model.md` §4.4), and the weights and main-stat
 * tables are the shipped `artifact_draw_model.json` rows — written out, not loaded, so a spec
 * cannot pass by comparing the file with itself.
 */

import { type Recipe, type RecipeHit } from './recipe';

export const LADDERS: Readonly<Record<string, readonly number[]>> = {
  flat_hp: [209.13, 239, 268.88, 298.75],
  flat_atk: [13.62, 15.56, 17.51, 19.45],
  flat_def: [16.2, 18.52, 20.83, 23.15],
  hp_pct: [0.0408, 0.0466, 0.0525, 0.0583],
  atk_pct: [0.0408, 0.0466, 0.0525, 0.0583],
  def_pct: [0.051, 0.0583, 0.0656, 0.0729],
  elemental_mastery: [16.32, 18.65, 20.98, 23.31],
  energy_recharge: [0.0453, 0.0518, 0.0583, 0.0648],
  crit_rate: [0.0272, 0.0311, 0.035, 0.0389],
  crit_dmg: [0.0544, 0.0622, 0.0699, 0.0777],
};

export const WEIGHTS: Readonly<Record<string, number>> = {
  flat_hp: 6, flat_atk: 6, flat_def: 6,
  hp_pct: 4, atk_pct: 4, def_pct: 4, elemental_mastery: 4, energy_recharge: 4,
  crit_rate: 3, crit_dmg: 3,
};

export const CIRCLET: Readonly<Record<string, number>> = {
  hp_pct: 0.22, def_pct: 0.22, atk_pct: 0.22, elemental_mastery: 0.04,
  crit_rate: 0.1, crit_dmg: 0.1, healing_bonus: 0.1,
};

export const FLOWER: Readonly<Record<string, number>> = { flat_hp: 1 };

export const MAIN_VALUES: Readonly<Record<string, number>> = {
  flat_hp: 4780, flat_atk: 311, hp_pct: 0.466, atk_pct: 0.466, def_pct: 0.583,
  elemental_mastery: 186.5, energy_recharge: 0.518, crit_rate: 0.311, crit_dmg: 0.622,
  healing_bonus: 0.359, hydro_dmg_bonus: 0.466,
};

/** An ATK-scaling Hydro hit, the ordinary case, as `bench-pinned-search.mjs` builds it. */
function hit(): RecipeHit {
  return {
    mine: true,
    owner: 0,
    abil: 'x', attackTag: 1, element: 'hydro', talent: 2, scaling: 'atk', flatDamage: 0,
    calibratedScaling: 1000, bonusDmg: 0, critRate: 0.05, critDmg: 0.5,
    conversions: {},
    calibratedBase: { atk: 1000, hp: 20000, def: 800 },
    calibratedPercent: { atk: 0, hp: 0, def: 0 },
    calibratedFlat: { atk: 0, hp: 0, def: 0 },
    defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900,
  };
}

/** A recipe of `hits` identical hits. Shape-correct for `evaluateRecipe`; values illustrative. */
export function syntheticRecipe(hits = 20): Recipe {
  return {
    hits: Array.from({ length: hits }, hit),
    seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [],
      calibratedSetIds: [], minimumEnergyRecharge: null,
    },
  } as unknown as Recipe;
}

/** The four other pieces of a plausible crit build — flower, plume, sands, goblet. */
export const OTHERS: readonly Readonly<Record<string, number>>[] = [
  { flat_hp: 4780, crit_rate: 0.07, crit_dmg: 0.2, atk_pct: 0.1 },
  { flat_atk: 311, crit_rate: 0.1, crit_dmg: 0.14, energy_recharge: 0.11 },
  { atk_pct: 0.466, crit_rate: 0.06, crit_dmg: 0.21 },
  { hydro_dmg_bonus: 0.466, crit_rate: 0.035, crit_dmg: 0.28 },
];
