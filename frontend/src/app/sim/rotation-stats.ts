/**
 * gcsim's own result object, read into the shape a results sheet draws.
 *
 * **Nothing here computes damage.** Every number is gcsim's, produced by running the team's
 * real config — the one `POST /rotations/{id}/preview` with `runnable: true` assembles, which
 * carries every character's actual gear. That is the whole point of the parity work: Calculate
 * is not a search, so it can run the thing rather than approximate it, and the fields the gcsim
 * results page prints are already in the object it returns.
 */

/** gcsim reports every quantity as a spread, not a point. */
export interface Spread {
  mean: number;
  sd: number;
  min: number;
  max: number;
  q1?: number;
  q2?: number;
  q3?: number;
  histogram?: number[];
}

export interface NamedSpread {
  name: string;
  spread: Spread;
}

export interface CharacterStats {
  name: string;
  dps: Spread | null;
  fieldTime: Spread | null;
  endingEnergy: Spread | null;
  /** Seconds spent unable to act for want of energy. `pkg/agg/failures` divides frames by 60. */
  insufficientEnergy: number;
  actions: NamedSpread[];
  byElement: NamedSpread[];
  bySource: NamedSpread[];
}

export interface RotationStats {
  iterations: number;
  dps: Spread | null;
  eps: Spread | null;
  rps: Spread | null;
  hps: Spread | null;
  shp: Spread | null;
  duration: Spread | null;
  characters: CharacterStats[];
  reactions: NamedSpread[];
  auraUptime: NamedSpread[];
}

function spread(value: unknown): Spread | null {
  const v = value as Partial<Spread> | undefined;
  if (!v || typeof v.mean !== 'number') return null;
  return {
    mean: v.mean,
    sd: v.sd ?? 0,
    min: v.min ?? v.mean,
    max: v.max ?? v.mean,
    q1: v.q1,
    q2: v.q2,
    q3: v.q3,
    histogram: v.histogram,
  };
}

/** `{sources: {name: spread}}` and `{elements: {name: spread}}` are the same shape. */
function namedSpreads(entry: unknown, key: 'sources' | 'elements'): NamedSpread[] {
  const inner = (entry as Record<string, Record<string, unknown>> | undefined)?.[key];
  if (!inner) return [];
  const out: NamedSpread[] = [];
  for (const [name, value] of Object.entries(inner)) {
    const s = spread(value);
    if (s) out.push({ name, spread: s });
  }
  return out.sort((a, b) => b.spread.mean - a.spread.mean);
}

interface Stats {
  iterations?: number;
  dps?: unknown; eps?: unknown; rps?: unknown; hps?: unknown; shp?: unknown; duration?: unknown;
  character_dps?: unknown[];
  field_time?: unknown[];
  end_stats?: { ending_energy?: unknown }[];
  failed_actions?: { insufficient_energy?: { mean?: number } | number }[];
  character_actions?: unknown[];
  dps_by_element?: unknown[];
  source_dps?: unknown[];
  source_reactions?: unknown[];
  target_aura_uptime?: unknown[];
}

/**
 * Read a finished run.
 *
 * `names` is the display order, positional against gcsim's own character order — the same
 * pairing every per-character array uses. A caller passing them in another order would label
 * the wrong character silently, which is why `energy-delay.ts` says so too.
 */
export function parseRotationStats(raw: unknown, names: readonly string[]): RotationStats {
  // **Two entry points, two key names, one simulator.** `flush()` in the browser wasm returns
  // `{stats: …}`; the native binary's `-out` JSON returns `{statistics: …}`. Reading only one
  // produces a page of blanks and "over 0 iterations" — a plausible empty result rather than
  // an error, which is how it was found: by rendering the page, not by a failing test.
  const wrapper = raw as { statistics?: Stats; stats?: Stats } | null;
  const st = (wrapper?.statistics ?? wrapper?.stats ?? {}) as Stats;
  const count = Math.max(
    names.length,
    st.character_dps?.length ?? 0,
    st.field_time?.length ?? 0,
  );

  const characters: CharacterStats[] = [];
  for (let i = 0; i < count; i++) {
    const failed = st.failed_actions?.[i]?.insufficient_energy;
    characters.push({
      name: names[i] ?? `character ${i + 1}`,
      dps: spread(st.character_dps?.[i]),
      fieldTime: spread(st.field_time?.[i]),
      endingEnergy: spread(st.end_stats?.[i]?.ending_energy),
      insufficientEnergy: typeof failed === 'number' ? failed : failed?.mean ?? 0,
      actions: namedSpreads(st.character_actions?.[i], 'sources'),
      byElement: namedSpreads(st.dps_by_element?.[i], 'elements'),
      bySource: namedSpreads(st.source_dps?.[i], 'sources'),
    });
  }

  // Reactions and aura uptime are per *target*, not per character — one entry for one enemy.
  const reactions: NamedSpread[] = [];
  for (const entry of st.source_reactions ?? []) reactions.push(...namedSpreads(entry, 'sources'));

  return {
    iterations: st.iterations ?? 0,
    dps: spread(st.dps),
    eps: spread(st.eps),
    rps: spread(st.rps),
    hps: spread(st.hps),
    shp: spread(st.shp),
    duration: spread(st.duration),
    characters,
    reactions,
    auraUptime: (st.target_aura_uptime ?? []).flatMap((e) => namedSpreads(e, 'sources')),
  };
}

/**
 * Round an estimate to the precision its uncertainty actually supports.
 *
 * **A mean printed to more digits than its spread justifies is a claim the run cannot back.**
 * 192,580.52 ± 5,732.01 is eight digits of precision on four digits of knowledge. The
 * convention is to quote the uncertainty to one or two significant figures and round the value
 * to the same place — so this returns 192,600 ± 5,700.
 *
 * `sd === 0` is a real answer, not a missing one: a deterministic quantity (an action count
 * that never varies) is exact, and rounding it would invent doubt.
 */
export function toPrecision(mean: number, sd: number): { value: number; uncertainty: number } {
  if (!Number.isFinite(sd) || sd <= 0) return { value: mean, uncertainty: 0 };
  // Two significant figures on the uncertainty, then round the value to that same place.
  const magnitude = Math.floor(Math.log10(Math.abs(sd)));
  const place = 10 ** (magnitude - 1);
  return {
    value: Math.round(mean / place) * place,
    uncertainty: Math.round(sd / place) * place,
  };
}


/**
 * The characters a config declares, in the order gcsim will index them.
 *
 * **Every per-character array — `character_actions`, `field_time`, `failed_actions` — is
 * positional against this order, and it is not the team's roster order.** `build_config` emits
 * the subject build first and teammates after; `/rotations/options` returns a roster in its
 * own order. Passing the roster produced a warning that named Citlali for Furina's missed
 * bursts: a plausible sentence about the wrong character, which is worse than no sentence.
 *
 * The keys are gcsim's own (`kaedeharakazuha`), so `displayNames` matches them back to
 * readable ones by the same normalisation gcsim uses — lowercase, letters and digits only.
 */
export function charactersInConfig(config: string): string[] {
  const out: string[] = [];
  for (const line of config.split('\n')) {
    const match = /^\s*([a-z0-9]+)\s+char\s/.exec(line);
    if (match && !out.includes(match[1])) out.push(match[1]);
  }
  return out;
}

/** gcsim's key for a display name: lowercase, letters and digits only. */
export function gcsimKeyOf(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/**
 * Label a config's character order with readable names.
 *
 * A key with no match keeps its own spelling rather than borrowing a neighbour's — a wrong
 * name reads as right, and this is the failure mode that made it necessary.
 */
export function displayNames(keys: readonly string[], roster: readonly string[]): string[] {
  const byKey = new Map(roster.map((name) => [gcsimKeyOf(name), name]));
  return keys.map((key) => byKey.get(key) ?? key);
}
