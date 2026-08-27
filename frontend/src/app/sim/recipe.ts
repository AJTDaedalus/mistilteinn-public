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
   * The scaling stat **as the calibration computed it** — gcsim's `total_scaling`. Used by
   * `replayHit` to check the transcription against gcsim's own answer, and **not** by the
   * evaluator, which recomputes it from `baseStat` and the candidate's own stats.
   */
  calibratedScaling: number;
  /**
   * The character's **base** ATK / HP / DEF — what a candidate's percentage stats multiply.
   *
   * Distinct from `calibratedScaling` because a candidate replaces the calibration's artifact
   * contribution rather than adding to it: at zero artifact stats the two are equal, and once
   * a candidate is applied they are not.
   */
  baseStat: number;
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

/**
 * A conversion baked into the calibration that goes **stale** under a different candidate.
 *
 * Detected from the data rather than from a list of weapons: at **zero artifact stats** a
 * non-zero flat term means something converted a stat into it. `Redhorn Stonethresher` puts
 * DEF into `flat_dmg`; Noelle's burst puts DEF into `flat_atk`; `Staff of Homa` puts max HP
 * there. All of them are computed from stats the candidate is about to change, and none of
 * them moves when the candidate does — so the recipe overstates or understates by exactly
 * that term.
 *
 * A list of weapons would need maintaining and would miss character kits entirely. The
 * numbers cannot.
 *
 * **Sound, not complete.** This finds conversions landing in a *flat* term, because those are
 * visibly non-zero at zero artifact stats. It does **not** find one landing in a percentage
 * term — `Engulfing Lightning` converts ER into ATK%, and a character has base ER regardless,
 * so a non-zero `atk_per` test would fire on every recipe. Distinguishing that needs a second
 * calibration at a perturbed ER, which is a task rather than a tweak.
 *
 * So a non-empty result can be trusted; an empty one means *"no flat-term conversions"*, not
 * *"none at all"*.
 */
export interface StaleConversion {
  /** Which term carries it. */
  term: 'flatDamage' | 'flatAtk' | 'flatHp' | 'flatDef';
  /** How many hits of the recipe are affected. */
  hits: number;
  /** The share of the recipe's total damage those hits account for, 0–1. */
  damageShare: number;
}

export interface RecipeMeta {
  seed: string;
  /** Every conversion baked in that a candidate's stats would have moved. Empty is good. */
  staleConversions: StaleConversion[];
}

export interface Recipe {
  hits: RecipeHit[];
  /** The gcsim commit the sample came from, so a stale recipe is detectable. */
  seed: string;
  meta: RecipeMeta;
}

/**
 * Whether a rotation's structure is reproducible, from an aggregate's instance counts.
 *
 * **`sd > 0` on an instance count means the rotation is not the same rotation every
 * iteration** — the build sits in a transition band, and no single recipe describes it.
 * `RESEARCH_damage_recipe.md` measured burst count going 2.00 → 2.75 → 4.00 across ER, with
 * the middle point being 2 *or* 3 depending on the seed, and `RESEARCH_er_bucketing.md`
 * measured that band at **13.3 % DPS spread, 5.9× the Monte Carlo standard error**.
 *
 * A little jitter is not the same thing: non-burst counts wobble by ~3 % from timing alone.
 * `tolerance` is the share of an instance count's mean that `sd` may reach before the
 * rotation is called unstable, and it is a **parameter** because the honest threshold depends
 * on how much of the damage that source carries.
 */
export function stabilityFrom(
  sources: Readonly<Record<string, { mean: number; sd: number }>>,
  tolerance = 0.02,
): { stable: boolean; unstable: string[] } {
  const unstable = Object.entries(sources)
    .filter(([, v]) => v.mean > 0 && v.sd / v.mean > tolerance)
    .map(([name]) => name)
    .sort();
  return { stable: unstable.length === 0, unstable };
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
  flat_hp: number;
  flat_def: number;
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
  const base = hit.talent * hit.calibratedScaling + hit.flatDamage;
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
      calibratedScaling: c.total_scaling,
      baseStat: c.use_hp ? c.base_hp : c.use_def ? c.base_def : c.base_atk,
      bonusDmg: c.bonus_dmg,
      critRate: c.cr,
      critDmg: c.cd,
      defMultiplier: c.def_mod,
      resMultiplier: c.res_mod,
      ampMultiplier: c.amp_mult_total === 0 ? 1 : c.amp_mult_total,
      gcsimAverageDamage: c.avg_crit_dmg,
    });
  }
  const seed = String(parsed?.seed ?? '');
  return { hits, seed, meta: { seed, staleConversions: staleConversionsIn(hits, calcs) } };
}

/**
 * Which baked-in conversions this recipe carries, and how much damage they touch.
 *
 * `damageShare` is reported because *"83 hits are affected"* is not actionable on its own —
 * 83 hits carrying 2 % of the damage is a footnote, and 5 hits carrying 40 % is not.
 */
function staleConversionsIn(hits: RecipeHit[], calcs: CalcLog[]): StaleConversion[] {
  const landed = calcs.filter((c) => c.damage !== 0);
  const total = hits.reduce((sum, h) => sum + h.gcsimAverageDamage, 0);
  const terms: [StaleConversion['term'], (c: CalcLog) => number][] = [
    ['flatDamage', (c) => c.flat_dmg],
    ['flatAtk', (c) => c.flat_atk],
    ['flatHp', (c) => c.flat_hp],
    ['flatDef', (c) => c.flat_def],
  ];
  const out: StaleConversion[] = [];
  for (const [term, read] of terms) {
    let count = 0;
    let damage = 0;
    for (let i = 0; i < landed.length && i < hits.length; i++) {
      if (read(landed[i]) !== 0) {
        count++;
        damage += hits[i].gcsimAverageDamage;
      }
    }
    if (count > 0) out.push({ term, hits: count, damageShare: total > 0 ? damage / total : 0 });
  }
  return out;
}
