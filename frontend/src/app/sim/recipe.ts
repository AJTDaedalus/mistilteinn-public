/**
 * A damage recipe: gcsim's rotation, decomposed so the optimizer can replay it.
 *
 * `docs/DESIGN_gcsim_optimizer.md`. gcsim cannot be the search's inner loop —
 * `RESEARCH_gcsim_embed.md` §6 measured ~8,900× a chain combination, and
 * `RESEARCH_gcsim_speed.md` put the ceiling on making it faster at ~4×. **So gcsim runs once
 * and the loop replays its arithmetic**, at a measured **0.051 µs per hit** against ~4.9 µs of
 * stat aggregation the hits share.
 *
 * ## This is transcription, not modelling
 *
 * `sample(cfg, seed)` publishes every term of the damage calculation for every hit —
 * `talent` (the ability multiplier), `total_scaling`, `bonus_dmg`, `cr`, `cd`, `def_mod`,
 * `res_mod`, `flat_dmg`, and `use_hp`/`use_def`/`use_em`. Recomposed across all 245 hits of a
 * committed sample, every relation is exact to **0.000e+00**
 * (`RESEARCH_gcsim_calibration.md` §2).
 *
 * So no coefficient here is derived, fitted, or read off a tooltip. Every number's provenance
 * is a reproducible gcsim run at the pin — the citation rule satisfied by construction rather
 * than by discipline.
 *
 * ## Three things that read backwards, all found by getting them wrong
 *
 * 1. **`bonus_dmg` already includes `ele_per`.** The element bonus is published separately as
 *    a *component*, not an addend. Adding it double-counts and breaks 73 of 245 hits.
 * 2. **`damage_grp_mult` is not part of the pre-crit relation.** Entries with `damage: 0` are
 *    queued-but-not-landed hits; folding that factor in makes them look like formula errors.
 * 3. **Use `avg_crit_dmg`, never `is_crit`.** gcsim *rolls* crit; this repo computes it, a
 *    deliberate divergence recorded in `docs/CROSSVAL_gcsim.md`. A recipe carrying per-hit
 *    rolls would import Monte Carlo noise into a deterministic evaluator.
 */

/** Which stat an ability scales off. gcsim states this; it is not inferred. */
export type RecipeScaling = 'atk' | 'hp' | 'def' | 'em';

/** One damage instance, decomposed. */
export interface RecipeHit {
  /** gcsim's ability name — `Soumetsu (Cutting)`, `Normal 1`. Not a label to show a user. */
  abil: string;
  /**
   * gcsim's attack tag — normal, charged, skill, burst. Read from the paired `damage` event,
   * because the `calc` event does not carry it.
   */
  attackTag: number;
  /**
   * `physical`, `cryo`, … **as gcsim spells it**, from the paired `damage` event.
   *
   * The `calc` event carries `ele` as gcsim's internal *enum* (19, 14), which is meaningless
   * outside gcsim and would silently become a key nothing matches. G.4 needs this to decide
   * which of a candidate's element bonuses reach which hit, so it has to be the real name.
   */
  element: string;
  /** The ability multiplier at the talent level simulated. */
  talent: number;
  scaling: RecipeScaling;
  /** Flat damage added before bonuses — Redhorn's DEF conversion lands here. */
  flatDamage: number;
  /**
   * The scaling stat's **base**, before percentage and flat additions. A candidate's artifacts
   * modify the percentage and flat parts; this is what they modify.
   */
  scalingBase: number;
  /** Totals from the calibration run. `RecipeBaseline` says how much was artifact-borne. */
  bonusDmg: number;
  critRate: number;
  critDmg: number;
  /** DEF and RES multipliers. Functions of levels and the target, not of artifacts. */
  defMultiplier: number;
  resMultiplier: number;
  /** Amplifying (melt/vaporize) total, or 1 when none applied. */
  ampMultiplier: number;
  /** What gcsim itself computed, kept so a replay can be checked against it. */
  gcsimAverageDamage: number;
}

export interface Recipe {
  hits: RecipeHit[];
  /** The gcsim commit the sample came from, so a stale recipe is detectable. */
  seed: string;
}

/** gcsim's `calc` log payload. Only the fields this module reads are named. */
interface CalcLog {
  abil: string;
  talent: number;
  total_scaling: number;
  base_atk: number;
  atk_per: number;
  flat_atk: number;
  base_hp: number;
  base_def: number;
  flat_dmg: number;
  bonus_dmg: number;
  cr: number;
  cd: number;
  def_mod: number;
  res_mod: number;
  amp_mult_total: number;
  use_hp: boolean;
  use_def: boolean;
  use_em: boolean;
  base_dmg: number;
  pre_crit_dmg: number;
  avg_crit_dmg: number;
  damage: number;
  ele: number;
}

interface SampleEntry {
  event?: string;
  logs?: Record<string, unknown>;
}

/** gcsim's `damage` log payload. Carries what `calc` omits. */
interface DamageLog {
  abil: string;
  ele: string;
  'attack-tag': number;
}

/**
 * Crit rate is clamped into `[0, 1]` before it multiplies crit damage.
 *
 * Published `cr` can exceed 1 when buffs stack past 100 %, and can go negative under a
 * debuff. gcsim clamps; replaying without clamping diverges from it precisely where crit
 * builds are most interesting.
 */
export function effectiveCritRate(critRate: number): number {
  return Math.min(Math.max(critRate, 0), 1);
}

/**
 * The average damage of one hit, from its own terms.
 *
 * Kept separate from `RecipeHit` so it can be checked against `gcsimAverageDamage` — which is
 * what proves the transcription rather than assuming it.
 */
export function replayHit(hit: RecipeHit): number {
  const base = hit.talent * hit.scalingBase + hit.flatDamage;
  const preCrit = base * (1 + hit.bonusDmg) * hit.defMultiplier * hit.resMultiplier;
  return preCrit * (1 + effectiveCritRate(hit.critRate) * hit.critDmg) * hit.ampMultiplier;
}

function scalingOf(c: CalcLog): RecipeScaling {
  if (c.use_hp) return 'hp';
  if (c.use_def) return 'def';
  if (c.use_em) return 'em';
  return 'atk';
}

/**
 * Parse a `sample()` payload into a recipe.
 *
 * **Hits gcsim reported as landing zero damage are dropped.** They are queued actions that
 * never connected, and carrying them would put entries in the recipe whose `damage_grp_mult`
 * is 0 while every other term is populated — indistinguishable from a formula error at
 * replay.
 */
export function parseSample(payload: string | { logs?: SampleEntry[]; seed?: unknown }): Recipe {
  const parsed = typeof payload === 'string' ? JSON.parse(payload) : payload;
  const entries: SampleEntry[] = Array.isArray(parsed?.logs) ? parsed.logs : [];

  // `calc` and `damage` are emitted as a pair, in order, one per damage instance — checked
  // across 245 hits, ability matching on every one. `calc` carries the decomposition;
  // `damage` carries the element by name and the attack tag. Neither alone is enough.
  const damages = entries.filter((e) => e.event === 'damage').map((e) => e.logs as unknown as DamageLog);
  const calcs = entries.filter((e) => e.event === 'calc').map((e) => e.logs as unknown as CalcLog);

  const hits: RecipeHit[] = [];
  for (let i = 0; i < calcs.length; i++) {
    const c = calcs[i];
    if (!c || c.damage === 0) continue;
    // Pair by position, and **verify** rather than assume: a mismatch means the pairing
    // premise is wrong, and silently mislabelling every hit's element is exactly the kind of
    // wrong-but-plausible this repo keeps legislating against.
    const d = damages[i];
    if (d !== undefined && d.abil !== c.abil) {
      throw new Error(
        `sample log pairing broke at index ${i}: calc "${c.abil}" beside damage "${d.abil}". ` +
          `The recipe cannot label elements without a reliable pairing.`,
      );
    }
    hits.push({
      abil: c.abil,
      attackTag: d?.['attack-tag'] ?? -1,
      element: d?.ele ?? '',
      talent: c.talent,
      scaling: scalingOf(c),
      flatDamage: c.flat_dmg,
      scalingBase: c.total_scaling,
      bonusDmg: c.bonus_dmg,
      critRate: c.cr,
      critDmg: c.cd,
      defMultiplier: c.def_mod,
      resMultiplier: c.res_mod,
      ampMultiplier: c.amp_mult_total === 0 ? 1 : c.amp_mult_total,
      gcsimAverageDamage: c.avg_crit_dmg,
    });
  }
  return { hits, seed: String(parsed?.seed ?? '') };
}
