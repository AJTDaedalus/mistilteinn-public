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
import type { Amplifying } from './damage';
import type { EnergyCost } from './energy-delay';
import type { EnergyObservation } from './recipe-energy';

/**
 * gcsim's attack tag for an Elemental Burst.
 *
 * `pkg/core/attacks/attack.go` at the pin: the enum starts at `AttackTagNone = iota`, so
 * `None 0, Normal 1, Extra 2, Plunge 3, ElementalArt 4, ElementalArtHold 5, **ElementalBurst
 * 6**`. Corroborated against a parsed run, where normal hits carry tag 1.
 *
 * A literal because it is pinned: `docs/CROSSVAL_gcsim.md` names the commit, and a re-pin that
 * renumbered this enum would move every tag at once — which `tests/crossval` would catch long
 * before a burst was mistaken for a plunge.
 */
export const BURST_ATTACK_TAG = 6;

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
   * Terms the probe showed do not move at all, and which are therefore **correctly** frozen.
   *
   * **A third state, because two were not enough.** The matcher asks which candidate stat moved
   * by the same factor as the term, and a term that did not move has a ratio of 1 — which no
   * *moved* stat can equal, so it always matched nothing and was filed as "a conversion no
   * probe could resolve". Measured on the owner's team: **183 of the subject's 198 flat-
   * carrying hits do not move under the probe**, so nearly every one of them was reported.
   *
   * Flat ATK that is simply flat is not an unresolvable conversion. Holding it constant is
   * exactly right — `resolvedTerm` returns the calibration's value and the candidate's own
   * flat is added on top — so there is nothing here to warn about.
   */
  constantTerms?: ConversionTerm[];
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
  // ── Formula-estimate terms (math-fallback P1) ─────────────────────────────────────────
  //
  // All optional and all absent on a gcsim recipe, whose behaviour they therefore leave
  // exactly as it was. `sim/formula-recipe.ts` sets them, because a recipe synthesised from
  // closed-form math must answer the same question the single-hit kernel answers, and three
  // of that kernel's terms move with the candidate in ways a frozen gcsim term does not.
  /**
   * Elemental Mastery the hit already carries before artifacts — character, weapon, set and
   * resonance. A hit scaling off EM, or amplifying, reads this **plus** the candidate's own.
   *
   * **Not formula-only any more.** `parseSample` sets it from gcsim's `em` (fix of 2026-11-13);
   * a recipe cached before then lacks it and `SCHEMA` 8 makes that entry recalibrate.
   */
  calibratedEm?: number;
  /**
   * The amplifying reaction, when the multiplier must follow the candidate's EM.
   *
   * `ampMultiplier` above is gcsim's frozen total and stays the replay value; when this is
   * present `evaluateHit` recomputes it through `damage.ts:amplifyingMultiplier`, the same
   * function the single-hit kernel uses, so the two cannot disagree about the EM term.
   *
   * A gcsim recipe sets it from `reaction_type`, `react_mult` and `react_bonus` when the hit
   * melted or vaporized and the pair names a reaction the chain knows; otherwise the frozen
   * total stands.
   */
  amplifying?: { reaction: Amplifying; reactionBonus: number };
  /** Which kind of move this is, so a move-scoped set bonus in the candidate's pool reaches it. */
  move?: FormulaMove;
  /**
   * DMG% converted from total Energy Recharge — Emblem of Severed Fate's 4-piece,
   * `min(cap, perUnit × ER)`. `calibratedEnergyRecharge` is the ER before artifacts.
   */
  bonusFromEnergyRecharge?: { perUnit: number; cap: number; calibratedEnergyRecharge: number };
  /**
   * DMG% per point of the hit's **own** total Elemental Mastery — calibrated plus the
   * candidate's, the same `em` the amplifying term reads. A kit buff whose giver is the
   * optimized character and reads their EM (Kazuha's A4 on Kazuha, math-fallback P2): a
   * teammate's EM is a number the server resolves, the subject's moves with every candidate.
   */
  bonusFromEm?: number;
}

/** The moves a set bonus can be scoped to. `formula_effects.MOVES` on the server. */
export type FormulaMove = 'normal' | 'charged' | 'plunge' | 'skill' | 'burst';

/**
 * Where a recipe came from, when it did not come from gcsim.
 *
 * **The label later UI must show.** A synthesised recipe and a calibrated one are the same
 * type so the search, ranking and upgrade code take either unchanged; this is what tells
 * them apart, and it carries every assumption the number rests on (`DESIGN` §2.5: a number
 * must be able to explain itself).
 */
export interface FormulaProvenance {
  kind: 'formula-estimate';
  /** The accuracy comparator for this estimate (`DECISIONS.md` §38). */
  comparator: 'genshin-optimizer';
  /** Every assumption, in words a user can check: conditions, unmodelled parts, scope gaps. */
  assumptions: string[];
  /** The rows the recipe was built from, with their counts. */
  rows: { id: string; label: string; count: number; move: FormulaMove | null }[];
  /** Citations of every bonus that contributed. */
  sources: string[];
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
   * The measured bursts-versus-ER ladder, and the burst count the calibration itself ran at.
   *
   * **Both, or neither is usable.** A ladder without the calibration's own count cannot say
   * whether a candidate is above or below where the recipe's damage was measured, and the
   * count alone cannot say what a different ER would buy.
   */
  energySweep?: EnergyObservation[];
  /** Team DPS at the ER the calibration itself ran at — what every rung is measured against. */
  calibratedEnergyDps?: number;
  /**
   * The artifact-borne ER the calibration ran at, so a ratio can be taken **against the same
   * ladder** rather than against a separately-measured number.
   *
   * `calibratedEnergyDps` is a 100-iteration aggregate; every rung is 20 iterations at a
   * different ER. Dividing one by the other meant `energyRatio` did not return 1 at the
   * calibration point — measured at **0.928** for the owner's Furina, whose 0.279 artifact ER
   * floors to the 0.20 rung (142,380) while the aggregate read 153,417. Two different
   * measurements of the same build, disagreeing by the width of a rung.
   *
   * With this, the denominator is `dpsAt(sweep, calibratedEnergyRecharge)`: same ladder, same
   * iteration count, same flooring, so the ratio is 1 at the calibration point by construction
   * and the rungs' shared noise divides out instead of accumulating.
   */
  calibratedEnergyRecharge?: number;
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
   * The weapon this recipe was calibrated with, when the search covers more than one.
   *
   * **A recipe is per weapon as much as it is per set.** A different weapon is a different
   * base ATK and a different passive, so it is a different recipe — `context_key` on the
   * server has always included the weapon, and this is the same fact where the browser can
   * see it. `undefined` on a search over the build's own weapon, which is every search until
   * the weapon picker is opened.
   *
   * Its first job is `shareEnergyMeasurement`: an energy ladder belongs to the weapon it was
   * swept on, and Favonius makes particles on crit.
   */
  weaponKey?: string;
  /**
   * The lowest artifact Energy Recharge at which this rotation performs as calibrated, or
   * `null` if it was never measured. See `recipe-energy.ts`.
   */
  minimumEnergyRecharge: number | null;
  /**
   * Present when this recipe was **synthesised from formulas** rather than calibrated from a
   * gcsim run. Absent means gcsim. `sim/formula-recipe.ts`.
   */
  formula?: FormulaProvenance;
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
  /** The snapshot EM — `atk.Snapshot.Stats[attributes.EM]`, `pkg/enemy/damage.go:144`. */
  em?: number;
  /** Whether a melt or vaporize applied. `atk.Info.Amped`. */
  melt_vape?: boolean;
  /** `"melt"` or `"vaporize"` — `info.ReactionType`, `pkg/core/info/reaction.go:13-14`. */
  reaction_type?: string;
  /** The base multiplier, 2 or 1.5 — `pkg/reactable/{melt,vaporize}.go`. */
  react_mult?: number;
  /** The character's reaction bonus (Crimson Witch and kin). `char.ReactBonus`. */
  react_bonus?: number;
  /**
   * `avg_crit_dmg` **times the amplifying multiplier** (`damage.go:177`).
   *
   * `avg_crit_dmg` is written before amplification (`damage.go:164`), so for a melt or
   * vaporize hit it is the pre-reaction average and this is the real one.
   */
  avg_crit_dmg_react?: number;
}

/**
 * gcsim's reaction type and base multiplier, as the damage chain names the reaction.
 *
 * `pkg/reactable/melt.go:24,30` — Pyro onto Cryo 2.0, Cryo onto Pyro 1.5; `vaporize.go:26,33`
 * — Pyro onto Hydro 1.5, Hydro onto Pyro 2. Anything else returns `null` and the hit keeps
 * gcsim's frozen total: naming a reaction on a guess would move a number gcsim measured.
 */
function amplifyingFrom(type: string | undefined, mult: number | undefined): Amplifying | null {
  const strong = mult === 2;
  if (!strong && mult !== 1.5) return null;
  if (type === 'melt') return strong ? 'melt' : 'reverse_melt';
  if (type === 'vaporize') return strong ? 'vaporize' : 'reverse_vaporize';
  return null;
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
    // **Elemental Mastery, read off the run like every other term.** A calibration carries no
    // artifact EM, so `em` is everything the hit has before artifacts — character, weapon, set
    // and team buffs — and a candidate's EM adds to it. Without it an EM-scaling hit was
    // scored off the candidate's EM alone, and the amplifying multiplier stayed frozen at the
    // calibration's EM, so artifact EM bought a vaporize or melt build nothing at all.
    const amplifying = c.melt_vape ? amplifyingFrom(c.reaction_type, c.react_mult) : null;
    const hit: RecipeHit = {
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
      constantTerms: [],
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
      // The amplified average when the hit amplified: `avg_crit_dmg` is the pre-reaction one,
      // so a vaporizing teammate's frozen hit — and every damage share built from it — read
      // as a fraction of what gcsim dealt, and `replayHit` could not match it.
      gcsimAverageDamage: c.melt_vape && typeof c.avg_crit_dmg_react === 'number'
        ? c.avg_crit_dmg_react
        : c.avg_crit_dmg,
    };
    if (typeof c.em === 'number') hit.calibratedEm = c.em;
    if (amplifying !== null) {
      hit.amplifying = { reaction: amplifying, reactionBonus: c.react_bonus ?? 0 };
    }
    hits.push(hit);
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
  const reads = new Map(TERMS.map((t) => [t.term, t.fromCalc]));
  // At parse time every present term is frozen — nothing has been resolved yet. Counting the
  // owner's Skirk rotation without the `mine` filter reported 89.3 % of the damage as an
  // unresolvable conversion, every point of it a teammate's, while Skirk's own hits carried
  // no flat terms at all; the filter now lives in `tallyStale` where both callers get it.
  return tallyStale(hits, (term, i) => i < landed.length && reads.get(term)!(landed[i]) !== 0);
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

/**
 * The four baked-in terms, listed **once**.
 *
 * `read` answers from a calibrated hit and `fromCalc` from the raw parse, because the two
 * callers below ask at two different moments. They were two separate arrays naming the same
 * four terms in the same order, which is a drift surface with no symptom: adding a fifth term
 * to one would have produced a list that silently never mentions it.
 */
const TERMS: {
  term: ConversionTerm;
  read: (h: RecipeHit) => number;
  fromCalc: (c: CalcLog) => number;
}[] = [
  { term: 'flatDamage', read: (h) => h.flatDamage, fromCalc: (c) => c.flat_dmg },
  { term: 'flatAtk', read: (h) => h.calibratedFlat.atk, fromCalc: (c) => c.flat_atk },
  { term: 'flatHp', read: (h) => h.calibratedFlat.hp, fromCalc: (c) => c.flat_hp },
  { term: 'flatDef', read: (h) => h.calibratedFlat.def, fromCalc: (c) => c.flat_def },
];

/**
 * The one place a stale-conversion list is assembled.
 *
 * **This exists because the rule was written out twice and drifted.** Both callers share it:
 * only the subject's own hits count, `damageShare` is measured against the *whole* run's
 * damage, and a term with no affected hits is omitted rather than reported as zero. #227
 * restored the `mine` filter to one of them — and the other, which *overwrites* its result,
 * still had it missing, so the owner saw `flatAtk`, `flatHp` and `flatDef` each reported
 * against **96.6 % of the damage** on a team whose subject carried no unresolved term at all.
 * Two functions, one fix, one of them still wrong.
 *
 * What differs between the callers is only *which terms are still frozen*, so that is the
 * parameter and everything else is here.
 */
function tallyStale(
  hits: readonly RecipeHit[],
  frozen: (term: ConversionTerm, index: number) => boolean,
): StaleConversion[] {
  const total = hits.reduce((sum, h) => sum + h.gcsimAverageDamage, 0);
  const out: StaleConversion[] = [];
  for (const { term } of TERMS) {
    let count = 0;
    let damage = 0;
    for (let i = 0; i < hits.length; i++) {
      // **Only the calibrated character's hits.** A teammate's flat ATK is their equipped
      // gear — `furina add stats atk=311 …` in the config — not a conversion, and nothing in
      // a search can move it, so warning about it is a warning nobody can act on.
      if (!hits[i].mine || !frozen(term, i)) continue;
      count++;
      damage += hits[i].gcsimAverageDamage;
    }
    if (count > 0) out.push({ term, hits: count, damageShare: total > 0 ? damage / total : 0 });
  }
  return out;
}

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
): { resolved: number; unresolved: number; constant: number } {
  if (baseline.hits.length !== probe.hits.length) {
    throw new Error(
      `probe changed the rotation: ${baseline.hits.length} hits against ${probe.hits.length}. ` +
        `A probe that moves the structure cannot identify a conversion.`,
    );
  }
  const sources: ConversionSource[] = ['atk', 'hp', 'def'];
  let resolved = 0;
  let unresolved = 0;
  let constant = 0;

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

      // **Did it move at all?** Asked first, because the matcher below cannot answer it: a
      // stat is a candidate only when the probe moved it, so a term with ratio 1 matches
      // nothing by construction and would be counted unresolved for ever.
      if (Math.abs(ratio - 1) <= tolerance) {
        // Optional on the type because a recipe cached before this existed genuinely has no
        // answer here — absent is not "no constants", and a `?? []` read says so.
        b.constantTerms = [...(b.constantTerms ?? []), term];
        constant++;
        continue;
      }

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
  return { resolved, unresolved, constant };
}

/**
 * The conversions still frozen after a resolution pass, with their share of the damage.
 *
 * **`mine` is the same rule `staleConversionsIn` states, and it was missing here.** This
 * function *overwrites* the list that one produced, so filtering teammates out upstream and
 * not downstream put them straight back: the owner saw `flatAtk`, `flatHp` and `flatDef` each
 * reported against **96.6 % of the damage**, on a team whose subject carried no unresolved
 * term at all. A teammate's flat ATK is their equipped gear — `furina add stats atk=311 …` in
 * the config — not a conversion, and no search can move it, so warning about it is a warning
 * nobody can act on.
 */
function staleConversionsAfter(recipe: Recipe): StaleConversion[] {
  const reads = new Map(TERMS.map((t) => [t.term, t.read]));
  return tallyStale(recipe.hits, (term, i) => {
    const hit = recipe.hits[i];
    // Resolved and constant terms are no longer stale: a resolved one rescales with the
    // candidate, and a constant one the probe never moved is not something a search can act on.
    return (
      reads.get(term)!(hit) !== 0
      && hit.conversions[term] === undefined
      && !(hit.constantTerms ?? []).includes(term)
    );
  });
}
