/**
 * A formula estimate in the shape a gcsim calibration has, so Optimize, Rank and Upgrade take
 * it unchanged.
 *
 * Math-fallback P1, task 8 (`docs/DESIGN_team_math_fallback.md` §2.2, §2.5). Every consumer of
 * a calibration reads one recipe per 4-piece state — `noFourPiece` and `byFourPieceSet` — and
 * trusts `meta.calibratedSetIds` to say which set's bonuses are already inside a recipe. This
 * module builds exactly that from `formula-recipe.ts`'s primitives:
 *
 * - **`noFourPiece`** carries no set bonus, like a gcsim baseline calibrated with no set. The
 *   search adds the static pools and the conditional 2-piece pools for whatever the
 *   combination holds.
 * - **`byFourPieceSet[S]`** carries S's whole bonus — its static 2- and 4-piece stats folded
 *   into each row's base, and its conditional tiers applied as formula sources — and says so in
 *   `calibratedSetIds = [S]`, which is the contract a gcsim recipe calibrated with S worn
 *   already keeps. So the search does not add S's pools a second time, and Rank and Upgrade,
 *   which score a recipe on the five pieces alone, see the same set bonus a gcsim recipe would
 *   have carried.
 *
 * `synthesizeRecipeSet` (task 5) leaves every static tier to the search's pools instead, which
 * is right for the search and wrong for ranking, whose `evaluateRecipe` adds no pools at all.
 * One shape for every consumer is why this exists rather than two.
 *
 * ## What this never does
 *
 * It never reaches gcsim, the recipe cache or the run corpus. A formula recipe is cheap to
 * rebuild (no simulation), and caching it beside gcsim recipes is the mixing D-F3's label
 * exists to prevent; `recipe-cache.ts` refuses one outright (`isFormulaRecipe`).
 */

import {
  resonanceSource,
  synthesizeRecipe,
  synthesizeRecipeSet,
  type ConditionState,
  type FormulaCondition,
  type FormulaResonance,
  type FormulaRow,
  type FormulaSetTier,
  type FormulaSource,
  type FormulaTeam,
} from './formula-recipe';
import type { Recipe } from './recipe';
import type { SetBonus } from './search';

/** The words every formula result carries, wherever it is shown (DESIGN §2.5). */
export const FORMULA_LABEL = 'Formula estimate — no simulation';

/**
 * What the score of a formula recipe is. **Never DPS**: the estimate has no time axis, so the
 * number is the damage of the sequence the user chose, and not comparable across teams.
 */
export const FORMULA_SCORE_LABEL = 'Damage for the chosen sequence';

export interface FormulaCalibrationInput {
  rows: readonly FormulaRow[];
  team: FormulaTeam;
  resonances: readonly FormulaResonance[];
  setTiers: readonly FormulaSetTier[];
  /** The kernel's static set pools, `/artifacts/set-bonuses`. */
  staticSetBonuses: readonly SetBonus[];
  /** The 4-piece states to build, by catalogue (nanoka) id. */
  fourPieceSetIds: readonly number[];
  conditionals?: ConditionState;
  characters?: string[];
}

export interface FormulaCalibration {
  noFourPiece: Recipe;
  byFourPieceSet: Map<number, Recipe>;
  /** Always empty: a 2+2 is the no-set recipe plus both sets' pools, which the search adds. */
  byPair: Map<string, Recipe>;
  /** What the search adds per combination: static pools and the conditional 2-piece pools. */
  setBonuses: SetBonus[];
  /** 4-piece states not built because their tier is stale or uncurated, with why. */
  withheld: { setId: number; reason: string }[];
  /** The baseline recipe's assumptions, for the panel. Each 4-piece recipe carries its own. */
  assumptions: string[];
}

const setSource = (tier: FormulaSetTier): FormulaSource => ({
  id: `set:${tier.set_id}:${tier.pieces}`,
  label: `${tier.set_name} ${tier.pieces}pc`,
  bonus: tier.bonus,
  citation: tier.citation,
});

const usable = (tier: FormulaSetTier): boolean =>
  tier.status !== 'stale' && tier.status !== 'uncurated';

/** A row with one set's static stats added to its base — that set worn, as gcsim would. */
function withStatics(row: FormulaRow, statics: readonly SetBonus[]): FormulaRow {
  if (!statics.length) return row;
  const base: Record<string, number> = { ...row.context.base };
  for (const tier of statics) {
    for (const [quantity, value] of Object.entries(tier.stats)) {
      base[quantity] = (base[quantity] ?? 0) + value;
    }
  }
  return { ...row, context: { ...row.context, base } };
}

/** Build every recipe a formula search, ranking or upgrade estimate needs. */
export function formulaCalibration(input: FormulaCalibrationInput): FormulaCalibration {
  const teamState = input.conditionals ?? {};
  const characters = input.characters ?? [];
  const resonances = input.resonances.map(resonanceSource);
  const tiersBySet = new Map<number, FormulaSetTier[]>();
  for (const tier of input.setTiers) {
    tiersBySet.set(tier.set_id, [...(tiersBySet.get(tier.set_id) ?? []), tier]);
  }

  const noFourPiece = synthesizeRecipe(
    input.rows, resonances, input.team, teamState, characters,
  );
  const byFourPieceSet = new Map<number, Recipe>();
  const withheld: { setId: number; reason: string }[] = [];
  for (const setId of input.fourPieceSetIds) {
    const tiers = tiersBySet.get(setId) ?? [];
    const four = tiers.find((t) => t.pieces === 4);
    if (four && !usable(four)) {
      withheld.push({ setId, reason: four.problem ?? four.status });
      continue;
    }
    const statics = input.staticSetBonuses.filter(
      (b) => b.setId === setId && b.piecesRequired <= 4 && Object.keys(b.stats).length > 0,
    );
    const conditional = tiers.filter((t) => t.pieces <= 4 && usable(t)).map(setSource);
    const recipe = synthesizeRecipe(
      input.rows.map((row) => withStatics(row, statics)),
      [...resonances, ...conditional], input.team, teamState, characters,
    );
    // The set's whole bonus is inside, so the search must not add its pools again.
    recipe.meta.calibratedSetIds = [setId];
    byFourPieceSet.set(setId, recipe);
  }

  // The conditional 2-piece pools, from task 5's own builder (no 4-piece states asked for).
  const { setBonuses: conditionalPools } = synthesizeRecipeSet({
    rows: input.rows, team: input.team, resonances: [], setTiers: input.setTiers,
    fourPieceSetIds: [], conditionals: teamState,
  });

  return {
    noFourPiece,
    byFourPieceSet,
    byPair: new Map(),
    setBonuses: [...input.staticSetBonuses, ...conditionalPools],
    withheld,
    assumptions: noFourPiece.meta.formula?.assumptions ?? [],
  };
}

/** Whether a recipe was synthesised from formulas rather than calibrated by gcsim. */
export function isFormulaRecipe(recipe: Recipe | null | undefined): boolean {
  return recipe?.meta?.formula?.kind === 'formula-estimate' || recipe?.seed === 'formula';
}

/** One source's conditions, for the assumptions panel. */
export interface ConditionGroup {
  sourceId: string;
  label: string;
  citation: string;
  conditions: FormulaCondition[];
  unmodelled: { what: string; reason: string }[];
}

/**
 * Every source a team and a set scope bring into the estimate: each active resonance and each
 * usable conditional tier of the sets named — **including the ones with nothing to set**, so
 * the panel names a static resonance like Fervent Flames as applied, with its citation, rather
 * than leaving the reader to wonder whether it was counted. Driven: a Pyro-pair team's panel
 * read "no conditional set bonus or resonance applies" while +25% ATK was in every hit.
 */
export function conditionGroups(
  resonances: readonly FormulaResonance[],
  setTiers: readonly FormulaSetTier[],
  setIds: ReadonlySet<number>,
): ConditionGroup[] {
  const sources = [
    ...resonances.map(resonanceSource),
    ...setTiers.filter((t) => setIds.has(t.set_id) && usable(t)).map(setSource),
  ];
  return sources
    .map((s) => ({
      sourceId: s.id,
      label: s.label,
      citation: s.citation,
      conditions: s.bonus.conditions,
      unmodelled: s.bonus.unmodelled,
    }));
}

/** What gcsim refused, read out of its own refusal sentence (`gcsim_keys._resolve`). */
export interface GcsimRefusal {
  kind: 'character' | 'weapon' | 'artifact set';
  name: string;
  message: string;
}

/**
 * The entry a 422 from `/calibrate` names, or `null` for any other failure.
 *
 * Matched against the sentence the backend writes (`gcsim has no <kind> key for '<name>'`),
 * which is the same text the catalogue's `gcsim.reason` carries. Anything else — a network
 * error, a validation failure — is not a refusal the estimate can answer and stays an error.
 */
export function gcsimRefusal(message: string): GcsimRefusal | null {
  const found = /gcsim has no (character|weapon|artifact set) key for '([^']+)'/.exec(message);
  if (found) {
    return { kind: found[1] as GcsimRefusal['kind'], name: found[2], message };
  }
  const traveler = /is a Traveler variant|gcsim has no '(aether|lumine)\w*'/.exec(message);
  return traveler ? { kind: 'character', name: 'the Traveler', message } : null;
}
