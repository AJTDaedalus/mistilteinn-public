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
import type { EnergyCost } from './energy-delay';

export type RecipeScaling = 'atk' | 'hp' | 'def' | 'em';

/** A stat a conversion can draw from. */
export type ConversionSource = 'atk' | 'hp' | 'def';

/** ATK, HP and DEF together — every stat that has base, percentage and flat parts. */
export interface StatTriple {
  atk: number;
  hp: number;
  def: number;
}

/** Terms a conversion can land in. Each is frozen at calibration until a probe resolves it. */
export type ConversionTerm = 'flatDamage' | 'flatAtk' | 'flatHp' | 'flatDef';

/** What a resolved conversion draws from, and how much per unit of it. */
export interface ResolvedConversion {
  from: ConversionSource;
  perUnit: number;
}

/** One damage instance, decomposed. */
export interface RecipeHit {
  /** gcsim's ability name — `Soumetsu (Cutting)`, `Normal 1`. Not a label to show a user. */
  abil: string;
  /**
   * Whether this hit belongs to the character being optimized.
   *
   * **A team's damage is mostly not the optimized character's**, and only that character's
   * artifacts change during a search. Measured on the owner's Skirk/Furina/Yelan/Citlali
   * rotation: teammates are 90.9% of the damage, and applying a candidate's stats to every hit
   * put **78.4% of the gain a candidate appeared to give onto damage that cannot move** —
   * Furina's ATK% raised by Skirk's artifacts.
   *
   * `false` freezes the hit at what gcsim measured, which is what it is: a constant.
   */
  mine: boolean;
  /**
   * Which character in the config this hit belongs to, by index.
   *
   * `mine` answers the scoring question; this answers *whose*, so a result can show the damage
   * share per character — the number that made "the optimized character is 14% of their own
   * rotation" visible at all.
   */
  owner: number;
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
   * What each frozen term was converted from, once a probe calibration has identified it.
   *
   * A missing entry means **unresolved**, not "no conversion": an unresolved flat term stays
   * at the calibration's value and goes stale under any candidate whose stats differ.
   */
  conversions: Partial<Record<ConversionTerm, ResolvedConversion>>;
  /**
   * The scaling stat **as the calibration computed it** — gcsim's `total_scaling`. Used by
   * `replayHit` to check the transcription against gcsim's own answer, and **not** by the
   * evaluator, which rebuilds it from the parts below.
   */
  calibratedScaling: number;
  /**
   * The three parts of every stat, kept apart because that is how they combine.
   *
   * `total = base × (1 + percent) + flat` — gcsim's own formula, and the reason a candidate's
   * percentage must be **added to** the calibration's percentage rather than applied to its
   * total. Multiplying an already-multiplied total compounds the calibration's own buffs, and
   * the error is invisible whenever the calibration has none.
   */
  calibratedBase: StatTriple;
  calibratedPercent: StatTriple;
  /**
   * The flat ATK / HP / DEF the calibration carried, from character and weapon kits.
   *
   * A percentage does **not** multiply it. Dropping it lost Noelle's DEF-to-ATK burst
   * entirely — 33 hits, a **79.75 %** prediction error, and invisible against a fixture whose
   * character has no flat conversion.
   */
  calibratedFlat: StatTriple;
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
  term: ConversionTerm;
  /** How many hits of the recipe are affected. */
  hits: number;
  /** The share of the recipe's total damage those hits account for, 0–1. */
  damageShare: number;
}

export interface RecipeMeta {
  seed: string;
  /** Every conversion baked in that a candidate's stats would have moved. Empty is good. */
  staleConversions: StaleConversion[];
  /**
   * Abilities whose instance count varied across iterations. Empty means the rotation ran the
   * same way every time.
   *
   * **On the recipe rather than beside it, so the cache carries it.** `calibrate` returned
   * `stable` as a sibling of the recipe, and `writeRecipe`/`readRecipe` persist only the
   * recipe — so a cached recipe came back with its instability forgotten, and the page then
   * affirmatively called the ranking sound. `staleConversions` survived precisely because it
   * lives here; stability had no reason to be anywhere else.
   */
  unstable: string[];
  /**
   * The config's characters, in the order it declares them, so `RecipeHit.owner` has names.
   *
   * On the recipe rather than beside it for the same reason `unstable` is: the recipe is what
   * gets cached, and a caller reading one back from storage has no other way to learn who is
   * who. Empty is a valid state — a caller that did not supply names gets indices.
   */
  characters: string[];
  /**
   * How long each character waited on energy, in seconds, from gcsim's own `failed_actions`.
   *
   * Beside `unstable` because it is the same kind of fact: something true of the *run* that no
   * candidate's artifacts can change, and that a damage number alone cannot say. Empty when
   * the aggregate was not run — a 4-piece target does not measure it.
   */
  //
  // **Optional, because it is genuinely absent.** Only the baseline target runs the aggregate
  // that measures it, so a 4-piece recipe has none to carry — and making every caller invent
  // an empty value to satisfy a type would be the type lying about the data.
  energyCost?: EnergyCost | null;
  /**
   * The catalogue id of the 4-piece set this recipe was calibrated with, or `null` for a
   * calibration that equipped none.
   *
   * **A scorer must not add this set's bonuses again.** Equipping a set to calibrate also
   * applies its 2-piece — measured as an exact `cryo% +0.150` for `Blizzard Strayer` — and the
   * kernel adds every matching tier from its own pool, so it would land twice
   * (`docs/RESEARCH_recipe_risks.md` §2).
   *
   * Set by whoever requested the calibration; `parseSample` cannot know it, because the config
   * carries a gcsim *key* and the kernel counts sets by catalogue id.
   *
   * **Plural, because a 2+2 calibration equips two sets.** It was a single id while only
   * 4-piece states existed — a 4-piece leaves one spare piece, which grants nothing — and a
   * pair recipe bakes in *both* 2-piece bonuses. Skipping only one would add the other a
   * second time, which is the double-count this field exists to prevent, arriving by the door
   * it was built to close. Empty means no set was equipped.
   */
  calibratedSetIds: readonly number[];
  /**
   * The lowest artifact Energy Recharge at which this rotation performs as calibrated, or
   * `null` if it was never measured. See `recipe-energy.ts`.
   */
  minimumEnergyRecharge: number | null;
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
  hp_per: number;
  def_per: number;
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
  const calcEntries = entries.filter((e) => e.event === 'calc');
  const calcs = calcEntries.map((e) => e.logs as unknown as CalcLog);
  // **Whose hit this is.** gcsim puts `char_index` on the log *envelope*, not in the `calc`
  // payload — the same nesting that made an earlier count of these fields read every value as
  // absent. `owner` names the calibrated character's index; anything else is a teammate.
  const owners = calcEntries.map((e) => (e as { char_index?: number }).char_index ?? -1);

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
      // The calibrated character is the config's first, which is how `build_config` writes it
      // — the build, then its teammates. A hit with no `char_index` is treated as the
      // calibrated character's: freezing a hit that should scale understates every candidate
      // equally, while scaling one that should not is the bug this field exists to fix.
      mine: owners[i] <= 0,
      owner: Math.max(owners[i], 0),
      attackTag: d?.['attack-tag'] ?? -1,
      element: d?.ele ?? '',
      talent: c.talent,
      scaling: scalingOf(c),
      flatDamage: c.flat_dmg,
      conversions: {},
      calibratedBase: { atk: c.base_atk, hp: c.base_hp, def: c.base_def },
      calibratedPercent: { atk: c.atk_per, hp: c.hp_per, def: c.def_per },
      calibratedFlat: { atk: c.flat_atk, hp: c.flat_hp, def: c.flat_def },
      calibratedScaling: c.total_scaling,
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
  return {
    hits,
    seed,
    meta: {
      seed,
      staleConversions: staleConversionsIn(hits, calcs),
      // Filled by the caller, the only thing that knows the config's character order — a
      // sample payload carries indices and no names.
      characters: [],
      // Filled by `calibrate`, which is the only caller that has seen more than one run.
      unstable: [],
      // Both are the caller's to fill in: a sample payload says nothing about which catalogue
      // set was equipped, nor about a sweep it was not part of.
      calibratedSetIds: [],
      minimumEnergyRecharge: null,
    },
  };
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
  const reads: [ConversionTerm, (c: CalcLog) => number][] = [
    ['flatDamage', (c) => c.flat_dmg],
    ['flatAtk', (c) => c.flat_atk],
    ['flatHp', (c) => c.flat_hp],
    ['flatDef', (c) => c.flat_def],
  ];
  const out: StaleConversion[] = [];
  for (const [term, read] of reads) {
    let count = 0;
    let damage = 0;
    for (let i = 0; i < landed.length && i < hits.length; i++) {
      // **Only the calibrated character's hits.** A teammate's flat ATK is their equipped
      // gear — `furina add stats atk=311 …` in the config — not a conversion, and nothing in a
      // search can move it. Counting those reported *the whole team's* frozen stats as an
      // unresolvable conversion: on the owner's Skirk rotation that was 89.3% of the damage,
      // every point of it a teammate's, while Skirk's own hits carried no flat terms at all.
      if (hits[i].mine && read(landed[i]) !== 0) {
        count++;
        damage += hits[i].gcsimAverageDamage;
      }
    }
    if (count > 0) out.push({ term, hits: count, damageShare: total > 0 ? damage / total : 0 });
  }
  return out;
}



/**
 * Identify what a baked-in flat-damage term converts from, by comparing two calibrations.
 *
 * **Measured, not transcribed.** `TASKS_passive_port.md` planned to read each conversion out
 * of gcsim's Go and copy its coefficient. A probe calibration gets the same answer *from
 * gcsim's own numbers*, with no coefficient to mistype and no per-weapon record to maintain —
 * and it catches character kits, which no list of weapons would.
 *
 * Verified against `Redhorn Stonethresher`, whose flat damage is 40 % of DEF: probing at
 * `def%=0.5` moved it **×1.2427** while total DEF moved **×1.2427**, and probing at
 * `atk%=0.5` moved it **×1.0000**. Exact, and the source stat is unambiguous.
 *
 * Both calibrations must be the **same rotation with the same structure** — same hit count,
 * same abilities in the same order. A probe large enough to move the rotation is not a probe.
 */
/** `total = base × (1 + percent) + flat`, gcsim's own formula. */
export function totalStat(hit: RecipeHit, stat: ConversionSource): number {
  return hit.calibratedBase[stat] * (1 + hit.calibratedPercent[stat]) + hit.calibratedFlat[stat];
}

const TERMS: { term: ConversionTerm; read: (h: RecipeHit) => number }[] = [
  { term: 'flatDamage', read: (h) => h.flatDamage },
  { term: 'flatAtk', read: (h) => h.calibratedFlat.atk },
  { term: 'flatHp', read: (h) => h.calibratedFlat.hp },
  { term: 'flatDef', read: (h) => h.calibratedFlat.def },
];

/**
 * Identify what each frozen term converts from, by comparing two calibrations.
 *
 * **Measured, not transcribed.** `TASKS_passive_port.md` planned to read every conversion out
 * of gcsim's Go and copy its coefficient. A probe gets the same answer *from gcsim's own
 * numbers* — no coefficient to mistype, no per-weapon record to maintain, and it catches
 * **character kits**, which no list of weapons would. Noelle's DEF-to-ATK burst is 33 hits and
 * would not appear on any weapon list.
 *
 * Verified against `Redhorn Stonethresher`, whose flat damage is 40 % of DEF: probing at
 * `def%=0.5` moved it **×1.2427** while total DEF moved **×1.2427**, and probing at
 * `atk%=0.5` moved it **×1.0000**.
 *
 * Both calibrations must be the **same rotation with the same structure**. A probe large
 * enough to move the rotation is not a probe.
 */
export function resolveConversions(
  baseline: Recipe,
  probe: Recipe,
  tolerance = 1e-6,
): { resolved: number; unresolved: number } {
  if (baseline.hits.length !== probe.hits.length) {
    throw new Error(
      `probe changed the rotation: ${baseline.hits.length} hits against ${probe.hits.length}. ` +
        `A probe that moves the structure cannot identify a conversion.`,
    );
  }
  const sources: ConversionSource[] = ['atk', 'hp', 'def'];
  let resolved = 0;
  let unresolved = 0;

  for (let i = 0; i < baseline.hits.length; i++) {
    const b = baseline.hits[i];
    const p = probe.hits[i];
    // The probe perturbs the calibrated character's stat line and nobody else's, so a
    // teammate's hit is identical in both runs and has nothing to identify. Skipped rather
    // than counted unresolved, which is what made the warning describe the whole team.
    if (!b.mine) continue;
    for (const { term, read } of TERMS) {
      const before = read(b);
      if (before === 0) continue;
      const ratio = read(p) / before;

      // The source is the stat whose ratio matches this term's. A stat the probe did not move
      // has ratio 1 and cannot be told from any other unmoved stat, so it is a candidate only
      // when the probe actually moved it.
      const matches = sources.filter((stat) => {
        const moved = totalStat(p, stat) / totalStat(b, stat);
        return Math.abs(moved - 1) > tolerance && Math.abs(moved - ratio) <= tolerance;
      });

      // Exactly one match, or it stays unresolved. Two mean the probe moved both by the same
      // factor and cannot separate them; zero means it moved neither. **Guessing between them
      // would put a confident wrong number in every hit that carries the term.**
      if (matches.length === 1) {
        b.conversions[term] = { from: matches[0], perUnit: before / totalStat(b, matches[0]) };
        resolved++;
      } else {
        unresolved++;
      }
    }
  }

  // Only unresolved terms are still stale. A resolved one rescales with the candidate and is
  // no longer frozen — leaving it in the list would warn about something that was fixed, and
  // a warning nobody can act on is one everybody learns to ignore.
  baseline.meta.staleConversions = staleConversionsAfter(baseline);
  return { resolved, unresolved };
}

/** The conversions still frozen after a resolution pass, with their share of the damage. */
function staleConversionsAfter(recipe: Recipe): StaleConversion[] {
  const total = recipe.hits.reduce((sum, h) => sum + h.gcsimAverageDamage, 0);
  const out: StaleConversion[] = [];
  for (const { term, read } of TERMS) {
    let count = 0;
    let damage = 0;
    for (const hit of recipe.hits) {
      if (read(hit) !== 0 && hit.conversions[term] === undefined) {
        count++;
        damage += hit.gcsimAverageDamage;
      }
    }
    if (count > 0) out.push({ term, hits: count, damageShare: total > 0 ? damage / total : 0 });
  }
  return out;
}
