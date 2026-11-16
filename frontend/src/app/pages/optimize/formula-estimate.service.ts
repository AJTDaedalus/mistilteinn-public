import { Injectable, inject, signal } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import type { Additive, Amplifying, ScalingStat } from '../../sim/damage';
import {
  conditionGroups,
  formulaCalibration,
  type ConditionGroup,
  type FormulaCalibration,
} from '../../sim/formula-calibration';
import {
  hitMove,
  reactionLabel,
  type ConditionState,
  type FormulaReaction,
  type ConditionValue,
  type FormulaKit,
  type FormulaProc,
  type FormulaRaisedTalent,
  type FormulaResonance,
  type FormulaRow,
  type FormulaSetTier,
} from '../../sim/formula-recipe';
import {
  particlesPerRotation,
  raidenA4Multiplier,
  type EnergyMode,
  type EnergySource,
  type FlatSource,
  type FormulaEnergy,
  type SubjectFavonius,
} from '../../sim/formula-energy';
import type { FormulaMove } from '../../sim/recipe';
import type { SearchContext as KernelContext } from '../../sim/search';
import type { BuildRead } from '../builds/builds.service';
import type { AvailableHit } from '../explain/explain.service';
import type { CalibrationResult } from './recipe-optimize.service';
import { OptimizeService, type SearchContext } from './optimize.service';

/** One row of the formula target as the user composes it: an ability and how often it lands. */
export interface TargetRow {
  id: string;
  /** The hit, named as `/search-context` takes it. */
  hit: { talent: AvailableHit['talent']; label: string; index: number };
  label: string;
  count: number;
  /** `null` is "unknown", not "none" — see `FormulaRow.move`. */
  move: FormulaMove | null;
  /** This row's overrides of the team-level conditionals (GO "frames"). */
  overrides: Record<string, ConditionValue>;
  /**
   * A reaction row (math-fallback P3): `count` instances triggered by the optimized character.
   * `hit` still names one of their abilities, only so the estimate can fetch the build's
   * context (base stats, level, target); the ability itself is not scored.
   */
  reaction?: FormulaReaction | null;
  /** Spread or aggravate on this ability's every hit (P3). */
  additive?: Additive | null;
  /**
   * A weapon proc row (owner approval 2026-11-14, `DECISIONS.md` §45): `count` instances of a
   * weapon's own damage instance. `hit` only fetches the build's context, as a reaction row's.
   */
  proc?: { source: string; key: string } | null;
}

/** A weapon proc the panel can offer as a row: which weapon, which proc. */
export interface ProcChoice {
  source: string;
  key: string;
  label: string;
  weapon: string;
}

/**
 * A candidate weapon for the subject (owner approval 2026-11-14, §45): its catalogue id and the
 * refinement to read its passive at. Absent refinement is the build's own, as the gcsim weapon
 * comparison rules.
 */
export interface WeaponChoice {
  id: string;
  refinement?: number;
}

/** Everything a formula estimate needs to know about who is being estimated, and where. */
export interface FormulaRequest {
  buildId: string;
  /** The optimized build, for its element, weapon class and name. */
  build: BuildRead;
  /** Every member's build, the optimized one included — for resonance and team counts. */
  team: readonly BuildRead[];
  channel: string;
  scope: string;
  enemyLevel: number;
  /** The 4-piece states to build, by catalogue (nanoka) id. */
  fourPieceSetIds: readonly number[];
  /** A candidate weapon in place of the equipped one (§45); absent is the equipped weapon. */
  weapon?: WeaponChoice;
}

/** Every member's kit for one optimized build, and the members with none. */
export interface TeamKits {
  sources: FormulaKit[];
  missing: string[];
  /** The subject's rows at the levels a kit's talent-level raise reaches (`DECISIONS.md` §42). */
  raisedTalents?: FormulaRaisedTalent[];
  /**
   * Members' weapons with no passive data (task 12), `<weapon> (<wielder>)`: "no weapon passive
   * modelled". A weapon with data is one of `sources`, `kind: 'weapon'`.
   */
  missingWeapons?: string[];
  /**
   * The optimized character's weapon in this resolution (the equipped one, or the candidate
   * asked for): its name, refinement and passive status — `no_passive_data` is "passive not
   * modelled", and the weapon competes on base ATK and substat alone.
   */
  subjectWeapon?: {
    name: string | null; refinement: number | null; status: string;
    /** Its source among `sources` (`weapon:<slug>`), or null with no passive data. */
    sourceId?: string | null;
  };
  /** The subject's weapon's own damage instances, each a proc row the panel can offer. */
  procs?: ProcChoice[];
}

/** A calibration and the formula's own reporting, side by side. */
export interface FormulaEstimate {
  calibration: CalibrationResult;
  formula: FormulaCalibration;
  /** The kit resolution it was built from: the subject's weapon and its passive status. */
  kits: TeamKits;
}

/** The kit cache's key: subject, team and the weapon (#240: a key without it ranks flat). */
export function kitKey(
  subjectBuildId: string, memberIds: readonly string[], weapon?: WeaponChoice,
): string {
  return `${subjectBuildId}|${memberIds.join(',')}|${weapon?.id ?? 'equipped'}`
    + `|${weapon?.refinement ?? ''}`;
}

/** `/formula/energy`: each member's burst cost, cooldown and cited skill particles (task 14). */
export type TeamEnergyData = components['schemas']['FormulaTeamEnergyRead'];

/**
 * The energy model's assumptions, every one the user's to change (task 14, DESIGN §2.11).
 * An absent key takes its default, said in the panel.
 */
export interface EnergySettings {
  /**
   * `wait`, the default (owner, 2026-11-15, DECISIONS §48): every row scaled by
   * rotation ÷ (rotation + wait), the drip paying the shortfall — and `skip` when the drip is
   * off. `skip` and `off` (report only, ER worth nothing) are the other choices.
   */
  mode: EnergyMode;
  /** Seconds; `null` is the subject's burst cooldown (game data). */
  rotationSeconds: number | null;
  /** Skill casts per rotation by member build id; absent is 1 (KQM's "1 E per Q" baseline). */
  casts: Record<string, number>;
  /** Particles per cast (or per interval) by source key, replacing the table's: a hold. */
  particles: Record<string, number>;
  /** The share of a source the subject catches on field, 0..1, by source key. */
  onField: Record<string, number>;
  /** Particles per rotation for a member with no curated count, by build id. */
  manual: Record<string, number>;
  /** Bursts per rotation by member build id; absent is 1 (one burst a rotation). */
  bursts: Record<string, number>;
  /**
   * A Favonius holder's crits-eligible hits on field per rotation, by build id. Absent: the
   * optimized character's own direct-hit rows, a teammate's skill casts (one hit a cast).
   */
  favoniusHits: Record<string, number>;
  /** A refund's triggers per burst or cast, by refund key, replacing the table's (0: off). */
  refundCounts: Record<string, number>;
  /** Energy per rotation ER does not multiply. */
  flatEnergy: number;
  /** Whether the enemy-particle drip (gcsim's `ENERGY_DRIP`) counts. */
  drip: boolean;
  /**
   * Whether the optimized character is on field (owner ruling 2026-11-15, DECISIONS §49).
   * `null`: from the rows — on field when one is a normal, charged or plunging attack
   * (`subjectOnFieldOf`). On field, every `active` generator's particles default to 100 %
   * caught on field.
   */
  subjectOnField: boolean | null;
  /**
   * Electro resonance's procs per rotation, bounded by its cooldown. `null`: the rate gcsim's
   * committed samples show (3 a 25 s rotation, owner ruling 2026-11-15, DECISIONS §50) times
   * the rotation, when a member can react with Electro; none otherwise.
   */
  resonanceProcs: number | null;
  /**
   * An `assumption` refund switched on, by refund key (DECISIONS §50). Absent: off — it
   * depends on the fight, and its stated assumption is the user's to accept.
   */
  refundToggles: Record<string, boolean>;
  /**
   * The element Venti's burst absorbed, by refund key (`'none'`: no absorption). Absent: the
   * first of gcsim's order (Pyro, Hydro, Electro, Cryo) a teammate carries.
   */
  absorbed: Record<string, string>;
}

export const DEFAULT_ENERGY: EnergySettings = {
  mode: 'wait', rotationSeconds: null, casts: {}, particles: {}, onField: {}, manual: {},
  bursts: {}, favoniusHits: {}, refundCounts: {}, flatEnergy: 0, drip: true,
  subjectOnField: null, resonanceProcs: null, refundToggles: {}, absorbed: {},
};

/** The team's Electro resonance as `/formula/energy` serves it. */
type TeamResonanceEnergy = NonNullable<TeamEnergyData['resonance']>;

/** Electro resonance's source key. */
export const RESONANCE_KEY = 'resonance:electro';

/**
 * Electro resonance's procs per rotation: the user's count, else — when a member can react
 * with Electro — the rate gcsim's committed samples show times the rotation (owner ruling
 * 2026-11-15, DECISIONS §50: both Raiden-team samples proc 3 times a 25 s rotation, so 0.12
 * a second, served as `default_procs_per_second`), and either way at most
 * `rotation ÷ cooldown` (gcsim `setup.go:185`, 300 frames; KQM "CD: 5s").
 */
export function resonanceProcs(
  resonance: TeamResonanceEnergy, settings: EnergySettings, rotationSeconds: number,
): number {
  const ceiling = rotationSeconds / resonance.cooldown_seconds;
  const rate = resonance.default_procs_per_second * rotationSeconds;
  const asked = settings.resonanceProcs ?? (resonance.team_can_trigger ? rate : 0);
  return Math.max(0, Math.min(ceiling, asked));
}

/**
 * A normal, charged or plunging attack, whichever talent's table publishes it: the move the
 * row declares, or a label that names one — Raiden's Musou Isshin attacks are burst-talent rows
 * labelled `1-Hit DMG`, `Charged Attack DMG`, `Plunge DMG`.
 */
const ATTACK_LABEL = /^(\d+-hit dmg|charged attack|plunge dmg|low\/high plunge dmg|normal attack)/i;

/**
 * Whether the optimized character is on field, from the rows: a normal, charged or plunging
 * attack is made by the character on field (gcsim acts only for the active character), so a
 * row of one says so. Reaction and proc rows are not the subject's attacks. A sequence of skills
 * and bursts alone — Xiangling's Guoba and Pyronado — reads as off field: cast and left.
 */
export function subjectOnFieldOf(
  rows: readonly Pick<FormulaRow, 'move' | 'hit' | 'reaction' | 'proc'>[],
): boolean {
  return rows.some((r) => !r.reaction && !r.proc && (
    r.move === 'normal' || r.move === 'charged' || r.move === 'plunge'
    || ATTACK_LABEL.test(r.hit?.label ?? '')));
}

/** A refund's key in `EnergySettings`: the giver's build and its position. */
export const refundKey = (buildId: string, index: number): string => `${buildId}:refund:${index}`;

/** A Favonius holder's source key. */
export const favoniusKey = (buildId: string): string => `${buildId}:favonius`;

type EnergyMember = TeamEnergyData['members'][number];

/**
 * Favonius procs per rotation: `min(rotation ÷ cooldown, crits × chance)`, crits being the
 * holder's on-field hits × their crit rate. The cooldown bounds it from above (gcsim
 * `favonius.go:47`, the proc's ICD); below it, each crit procs with the refinement's chance
 * (`:50`). An upper bound on the expectation — a crit landing during the cooldown is spent.
 */
export function favoniusProcs(
  member: EnergyMember, hits: number, rotationSeconds: number,
): number {
  const fav = member.favonius;
  if (!fav) return 0;
  const crits = hits * Math.min(1, Math.max(0, member.crit_rate ?? 0));
  return Math.min(rotationSeconds / fav.cooldown_seconds, crits * fav.chance);
}

/** The default on-field hits for a Favonius holder: the subject's rows, a teammate's casts. */
export function defaultFavoniusHits(
  member: EnergyMember, settings: EnergySettings, subjectHits: number,
): number {
  return member.is_subject ? subjectHits : settings.casts[member.build_id] ?? 1;
}

type EnergyRefund = NonNullable<EnergyMember['refunds']>[number];

/** What a refund reads beyond its giver: the team, whether the subject is on field, the rotation. */
export interface RefundContext {
  members: readonly EnergyMember[];
  subjectOnField: boolean;
  rotationSeconds: number;
}

/**
 * The element Venti's burst absorbed (DECISIONS §50), or `null` for none: the user's, else
 * the first of gcsim's absorption order (`venti/burst.go:102`: Pyro, Hydro, Electro, Cryo)
 * that a member other than the giver carries — the assumption being that an enemy carries the
 * aura the team puts on it.
 */
export function absorbedElement(
  giver: EnergyMember, refund: EnergyRefund, settings: EnergySettings,
  members: readonly EnergyMember[], index?: number,
): string | null {
  const key = refundKey(giver.build_id, index ?? (giver.refunds ?? []).indexOf(refund));
  const chosen = settings.absorbed[key];
  if (chosen !== undefined) return chosen === 'none' ? null : chosen;
  const carried = new Set(members.filter((m) => m.build_id !== giver.build_id)
    .map((m) => m.element));
  return (refund.absorbs ?? []).find((e) => carried.has(e)) ?? null;
}

/** The default on-field share of an `active` refund: the subject on field catches it. */
export function refundOnField(
  member: EnergyMember, index: number, settings: EnergySettings, subjectOnField: boolean,
): number {
  return settings.onField[refundKey(member.build_id, index)] ?? (subjectOnField ? 1 : 0);
}

/**
 * A refund over one rotation as the subject receives it, or `null` when it does not reach
 * them or is not counted.
 *
 * - **Who**: `self` the giver alone, `others` everyone but the giver, `team` everyone,
 *   `active` whoever is on field when it lands (the subject's on-field share of it), and
 *   `absorbed` every member of the element Venti's burst absorbed (`absorbedElement`).
 * - **Whether**: `unavailable` (an ascension the build lacks) never; a `fight` refund never —
 *   it is listed with its reason; an `assumption` refund only when switched on
 *   (`refundToggles`). A constellation the giver lacks is never served at all.
 * - **How often**: per burst or cast, `count` times; `second`: `count` every `interval`
 *   seconds of the rotation, capped at `max_seconds` a trigger, per burst or cast (`on`).
 */
export function refundSource(
  member: EnergyMember, index: number, settings: EnergySettings,
  ctx: RefundContext = { members: [member], subjectOnField: false,
    rotationSeconds: member.burst_cooldown ?? 20 },
): FlatSource | null {
  const refund = member.refunds?.[index];
  if (!refund || refund.amount === null || refund.amount === undefined || refund.unavailable) {
    return null;
  }
  const key = refundKey(member.build_id, index);
  const basis = refund.basis ?? 'kit';
  if (basis === 'fight' || (basis === 'assumption' && !settings.refundToggles[key])) return null;
  let share = 1;
  switch (refund.recipients) {
    case 'self': if (!member.is_subject) return null; break;
    case 'others': if (member.is_subject) return null; break;
    case 'active': share = refundOnField(member, index, settings, ctx.subjectOnField); break;
    case 'absorbed': {
      const subject = ctx.members.find((m) => m.is_subject) ?? (member.is_subject ? member : null);
      const element = absorbedElement(member, refund, settings, ctx.members, index);
      if (!subject || element === null || subject.element !== element) return null;
      break;
    }
    case 'team': break;
  }
  if (share <= 0) return null;
  const bursts = settings.bursts[member.build_id] ?? 1;
  const casts = settings.casts[member.build_id] ?? 1;
  const triggers = refund.per === 'burst' ? bursts
    : refund.per === 'cast' ? casts
      : (refund.on === 'skill' ? casts : refund.on === 'rotation' ? 1 : bursts)
        * Math.min(ctx.rotationSeconds, refund.max_seconds ?? Infinity) / (refund.interval ?? Infinity);
  const energy = refund.amount * (settings.refundCounts[key] ?? refund.count) * triggers * share;
  if (member.is_subject) {
    return { key, label: `${member.name}: ${refund.label}`, energy,
      scaling: refund.scaling, citation: refund.citation };
  }
  // A teammate's ER is their build's: applied here, a constant to the search.
  const er = member.energy_recharge ?? 1;
  const scaled = refund.scaling === 'per_er' ? energy * er
    : refund.scaling === 'raiden_a4' ? energy * raidenA4Multiplier(er) : energy;
  return { key, label: `${member.name}: ${refund.label}`, energy: scaled, scaling: 'none',
    citation: refund.citation };
}

/**
 * The optimized character's crit-eligible hits per rotation: the count of every direct-hit row
 * (a transformative reaction or a weapon proc row does not crit through Favonius's check —
 * it is not the wielder's crit, or does not crit at all). The default Favonius hit count.
 */
export function subjectHitsOf(
  rows: readonly { count: number; reaction?: unknown; proc?: unknown }[],
): number {
  return rows.filter((r) => !r.reaction && !r.proc).reduce((sum, r) => sum + r.count, 0);
}

/** A source's key in `EnergySettings`: the member's build and its position. */
export const sourceKey = (buildId: string, index: number): string => `${buildId}:${index}`;

/**
 * The default on-field share of a skill source.
 *
 * - The subject's own `caster` particles: 1 — caught while still casting.
 * - An `active` generator — an off-field summon whose particles land on whoever is on field:
 *   Guoba, Furina's Salon, Nahida's Tri-Karma, Raiden's Eye, Oz, Kuki's ring, Kokomi's
 *   jellyfish, Zhongli's stele, Yae's totems — **1 when the subject is on field** (owner ruling
 *   2026-11-15, DECISIONS §49), whoever's it is; 0 otherwise. The gcsim sample's on-field Raiden
 *   caught all 24 of Oz's particles and 28 of her own Eye's 36 on field: 100 % is the default,
 *   the rest of the rotation's swaps are the user's to enter.
 * - A teammate's `caster` particles: 0 — they land while that teammate is on field.
 */
export function defaultOnField(
  member: TeamEnergyData['members'][number], source: { collector: string },
  subjectOnField = false,
): number {
  if (source.collector === 'active') return subjectOnField ? 1 : 0;
  return member.is_subject && source.collector === 'caster' ? 1 : 0;
}

/** The rotation length in force: the user's, else the subject's burst cooldown, else 20 s. */
export function rotationSecondsOf(data: TeamEnergyData, settings: EnergySettings): number {
  const subject = data.members.find((m) => m.is_subject);
  return settings.rotationSeconds ?? subject?.burst_cooldown ?? 20;
}

/**
 * The energy model's team-level inputs from the server's data and the user's settings, or
 * `null` when the subject has no burst cost to fund (nothing to price).
 */
export function energyInput(
  data: TeamEnergyData, settings: EnergySettings, subjectHits = 0, rowsOnField = false,
): Omit<FormulaEnergy, 'baseEnergyRecharge'> | null {
  const subject = data.members.find((m) => m.is_subject);
  if (!subject?.burst_energy_cost || !subject.element) return null;
  const seconds = rotationSecondsOf(data, settings);
  const onField = settings.subjectOnField ?? rowsOnField;
  const sources: EnergySource[] = [];
  const flatSources: FlatSource[] = [];
  const refundCtx: RefundContext = {
    members: data.members, subjectOnField: onField, rotationSeconds: seconds,
  };
  let subjectFavonius: SubjectFavonius | undefined;
  for (const member of data.members) {
    const casts = settings.casts[member.build_id] ?? 1;
    const bursts = settings.bursts[member.build_id] ?? 1;
    (member.refunds ?? []).forEach((_, i) => {
      const flat = refundSource(member, i, settings, refundCtx);
      if (flat && flat.energy > 0) flatSources.push(flat);
    });
    if (member.favonius) {
      // gcsim `favonius.go:44`: a proc needs the holder active, so the subject catches its
      // own on field and a teammate's off field (each landing 100 frames later: editable).
      const key = favoniusKey(member.build_id);
      const hits = settings.favoniusHits[member.build_id]
        ?? defaultFavoniusHits(member, settings, subjectHits);
      const procs = favoniusProcs(member, hits, seconds);
      if (member.is_subject) {
        // The optimized character's own: priced from each candidate's crit (DECISIONS §49).
        // `baseCritRate` is the build's here; the calibration replaces it with the recipe's
        // own pre-artifact crit.
        const crit = member.crit_rate ?? 0;
        subjectFavonius = {
          key, label: `${member.name}: ${member.favonius.weapon} R${member.favonius.refinement}`,
          hits, chance: member.favonius.chance, cooldownSeconds: member.favonius.cooldown_seconds,
          particles: member.favonius.particles, onFieldShare: settings.onField[key] ?? 1,
          citation: member.favonius.citation, baseCritRate: crit, buildCritRate: crit,
        };
      } else if (procs > 0) {
        sources.push({
          key, label: `${member.name}: ${member.favonius.weapon} R${member.favonius.refinement}`,
          element: null, particles: procs * member.favonius.particles,
          onFieldShare: settings.onField[key] ?? 0,
          citation: member.favonius.citation,
        });
      }
    }
    if (member.status === 'no_particle_data') {
      const manual = settings.manual[member.build_id] ?? 0;
      if (manual > 0) {
        const key = `${member.build_id}:manual`;
        sources.push({
          key, label: `${member.name} (entered)`, element: member.element ?? null,
          particles: manual, onFieldShare: settings.onField[key] ?? 0,
          citation: 'entered by the user',
        });
      }
      continue;
    }
    member.sources.forEach((source, i) => {
      const key = sourceKey(member.build_id, i);
      const each = settings.particles[key] ?? source.particles;
      sources.push({
        key, label: `${member.name}: ${source.label}`, element: member.element ?? null,
        particles: particlesPerRotation(
          { ...source, particles: each }, source.on === 'burst' ? bursts : casts, seconds),
        onFieldShare: settings.onField[key] ?? defaultOnField(member, source, onField),
        citation: source.citation,
      });
    });
  }
  if (data.resonance) {
    // Electro resonance (DECISIONS §49): one Electro particle a proc, distributed at once to
    // whoever is on field — an on-field subject's by default — at most one per cooldown.
    const procs = resonanceProcs(data.resonance, settings, seconds);
    if (procs > 0) {
      sources.push({
        key: RESONANCE_KEY, label: `Electro resonance (${data.resonance.name})`,
        element: data.resonance.element, particles: procs * data.resonance.particles,
        onFieldShare: settings.onField[RESONANCE_KEY] ?? (onField ? 1 : 0),
        citation: data.resonance.citation,
      });
    }
  }
  // The drip is distributed like any particle (gcsim `setup.go:527`, `DistributeParticle`):
  // whoever is active catches it at full value, so an on-field subject catches it on field
  // (owner ruling 2026-11-15, DECISIONS §50), as it does the summons.
  const drip = settings.drip ? {
    particlesPerSecond: data.drip.particles / data.drip.interval_seconds,
    onFieldShare: settings.onField['drip'] ?? (onField ? 1 : 0),
  } : null;
  if (drip) {
    sources.push({
      key: 'drip', label: 'Enemy particles (drip)', element: null,
      particles: drip.particlesPerSecond * seconds, onFieldShare: drip.onFieldShare,
      citation: data.drip.citation,
    });
  }
  return {
    mode: settings.mode === 'wait' && !drip ? 'skip' : settings.mode,
    cost: subject.burst_energy_cost,
    element: subject.element,
    partyCount: data.members.length,
    rotationSeconds: seconds,
    flatEnergy: settings.flatEnergy,
    flatSources,
    sources,
    drip,
    ...(subjectFavonius ? { subjectFavonius } : {}),
  };
}

/**
 * The conditional state a **candidate weapon's** run reads (owner ruling 2026-11-15,
 * `DECISIONS.md` §47: a candidate's passive conditions are shown and editable per candidate).
 *
 * Every key under the candidate's own source is dropped from the page's state — a teammate
 * wielding the same weapon in the equipped run can hold that very source id, and its setting is
 * not this candidate's — and the candidate's own settings are written under it. A condition the
 * user did not set takes the source's default, as every condition does.
 */
export function candidateConditionState(
  state: Readonly<Record<string, ConditionValue>>,
  sourceId: string | null | undefined,
  own: Readonly<Record<string, ConditionValue>>,
): Record<string, ConditionValue> {
  if (!sourceId) return { ...state };
  const prefix = `${sourceId}/`;
  const out: Record<string, ConditionValue> = {};
  for (const [key, value] of Object.entries(state)) {
    if (!key.startsWith(prefix)) out[key] = value;
  }
  for (const [condition, value] of Object.entries(own)) out[`${prefix}${condition}`] = value;
  return out;
}

/**
 * The assumptions panel's group for one candidate weapon (§46): its passive's conditions,
 * defaults, reasons and citation, marked `candidate` so the panel reads and writes that
 * candidate's own state. A weapon with no passive data is named as one, as the equipped
 * weapon's would be.
 */
export function candidateGroup(kits: TeamKits, weapon: WeaponChoice, name: string): ConditionGroup {
  const refinement = weapon.refinement ?? kits.subjectWeapon?.refinement ?? null;
  const label = `Candidate: ${name}${refinement ? ` R${refinement}` : ''}`;
  const source = kits.sources.find((s) => s.id === kits.subjectWeapon?.sourceId);
  const candidate = { weaponId: weapon.id };
  if (!source) {
    return {
      sourceId: `candidate:${weapon.id}`, label, citation: '', conditions: [], kind: 'no-weapon',
      unmodelled: [{
        what: 'weapon passive', reason: 'no weapon passive modelled: base ATK and substat only',
      }],
      candidate,
    };
  }
  return {
    sourceId: `candidate:${weapon.id}`, label, citation: source.citation,
    conditions: source.bonus.conditions,
    unmodelled: source.bonus.unmodelled.filter(
      (part, i, all) => all.findIndex((p) => p.what === part.what) === i,
    ),
    kind: 'weapon', verified: source.verified, candidate,
    ...(source.status === 'no_damage_effect' ? { inert: true } : {}),
  };
}

/** The API's search context in the kernel's spelling — the same mapping single-hit uses. */
export function kernelContext(context: SearchContext): KernelContext {
  return {
    base: context.base,
    hit: {
      multiplier: context.hit.multiplier,
      scalingStat: context.hit.scaling_stat as ScalingStat,
      flatDamage: 0,
      baseDamageBonus: 0,
      amplifying: context.hit.amplifying as Amplifying | null,
      reactionBonus: 0,
      extraTerms: context.hit.extra_terms,
    },
    target: {
      level: context.target.level,
      resistance: context.target.resistance,
      defReduction: context.target.def_reduction,
      defIgnore: context.target.def_ignore,
    },
    characterLevel: context.character_level,
    dmgBonusQuantity: context.dmg_bonus_quantity,
    reactionLevelMultiplier: context.reaction_level_multiplier,
  };
}

let nextRow = 0;

/** A fresh reaction row (P3): one instance of `reaction`, a starting assumption to edit. */
export function reactionRowFor(hit: AvailableHit, reaction: FormulaReaction): TargetRow {
  nextRow += 1;
  return {
    id: `row-${nextRow}`,
    hit: { talent: hit.talent, label: hit.label, index: hit.index },
    label: reactionLabel(reaction),
    count: 1,
    move: null,
    overrides: {},
    reaction,
  };
}

/** A fresh proc row (§45): one instance of the weapon's proc, a starting assumption to edit. */
export function procRowFor(hit: AvailableHit, proc: ProcChoice): TargetRow {
  nextRow += 1;
  return {
    id: `row-${nextRow}`,
    hit: { talent: hit.talent, label: hit.label, index: hit.index },
    label: proc.label,
    count: 1,
    move: null,
    overrides: {},
    proc: { source: proc.source, key: proc.key },
  };
}

/** A fresh row for a hit: its move (the sheet's, else the label's guess) and a count of one. */
export function rowFor(hit: AvailableHit): TargetRow {
  nextRow += 1;
  return {
    id: `row-${nextRow}`,
    hit: { talent: hit.talent, label: hit.label, index: hit.index },
    label: hit.label,
    count: 1,
    move: hitMove(hit),
    overrides: {},
  };
}

/**
 * The formula target and its conditionals, shared by Optimize, Rank and Upgrade.
 *
 * Math-fallback P1, task 8. A root singleton like `ArtifactsContextService`, because the three
 * are sibling surfaces asking about the same build: a target composed on Optimize is the one
 * Rank should score against, and composing it twice is the friction the tabs exist to remove.
 *
 * **Nothing here touches gcsim, the recipe cache or the run corpus.** A formula estimate is
 * rebuilt from the API every time it is asked for — it costs a few requests, not a simulation
 * — so there is nothing worth caching and nothing that could be mistaken for a sim run.
 */
@Injectable({ providedIn: 'root' })
export class FormulaEstimateService {
  private api = injectApi();
  private optimize = inject(OptimizeService);

  /** The target's rows, for `forBuild`. */
  readonly rows = signal<TargetRow[]>([]);
  /** The build the rows belong to: a row names a talent of one character. */
  readonly forBuild = signal('');
  /** Team-level conditionals the user changed. An absent key takes the source's default. */
  readonly conditionals = signal<Record<string, ConditionValue>>({});
  /**
   * Each candidate weapon's own passive conditions the user changed, by catalogue weapon id
   * and condition key (owner ruling 2026-11-15, §46). Read only by that candidate's run
   * (`candidateConditionState`); an absent key takes the passive's default.
   */
  readonly candidateConditionals = signal<Record<string, Record<string, ConditionValue>>>({});

  /** The energy model's assumptions (task 14). */
  readonly energy = signal<EnergySettings>(DEFAULT_ENERGY);
  /** The current team's energy data, refreshed with the panel's groups; null before. */
  readonly teamEnergy = signal<TeamEnergyData | null>(null);

  private tiers: Promise<FormulaSetTier[]> | null = null;
  /**
   * Kit resolutions by subject, team **and weapon**: the panel and the estimate ask alike, and a
   * weapon comparison asks once per candidate. **The weapon is in the key** — #240 shipped a
   * flat weapon ranking because a cache key lacked it, every candidate reading the first
   * weapon's numbers back (`formula-weapon-compare.spec.ts` pins it).
   */
  private kitCache = new Map<string, Promise<TeamKits>>();

  /** Start (or keep) a target for this build, seeded with one hit. */
  ensureTarget(buildId: string, hits: readonly AvailableHit[], seed = 0): void {
    if (this.forBuild() === buildId && this.rows().length) return;
    this.forBuild.set(buildId);
    const hit = hits[seed] ?? hits[0];
    this.rows.set(hit ? [rowFor(hit)] : []);
  }

  addRow(hit: AvailableHit): void {
    this.rows.update((rows) => [...rows, rowFor(hit)]);
  }

  /** Add a reaction row (P3); `hit` only fetches the build's context. */
  addReactionRow(hit: AvailableHit, reaction: FormulaReaction): void {
    this.rows.update((rows) => [...rows, reactionRowFor(hit, reaction)]);
  }

  /** Add a weapon proc row (§45); `hit` only fetches the build's context. */
  addProcRow(hit: AvailableHit, proc: ProcChoice): void {
    this.rows.update((rows) => [...rows, procRowFor(hit, proc)]);
  }

  removeRow(id: string): void {
    this.rows.update((rows) => (rows.length > 1 ? rows.filter((r) => r.id !== id) : rows));
  }

  updateRow(id: string, patch: Partial<Omit<TargetRow, 'id'>>): void {
    this.rows.update((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  /** Set one row's override of a conditional; `undefined` returns it to the team setting. */
  overrideRow(id: string, key: string, value: ConditionValue | undefined): void {
    this.rows.update((rows) => rows.map((r) => {
      if (r.id !== id) return r;
      const overrides = { ...r.overrides };
      if (value === undefined) delete overrides[key];
      else overrides[key] = value;
      return { ...r, overrides };
    }));
  }

  /** Change some of the energy assumptions; the rest stand. */
  setEnergy(patch: Partial<EnergySettings>): void {
    this.energy.update((state) => ({ ...state, ...patch }));
  }

  /**
   * The team's energy data for the optimized build (task 14): burst costs and cooldowns, each
   * member's cited skill particles, the drip. Fetched per team; a member with no curated count
   * comes back named.
   */
  async energyData(team: readonly BuildRead[], subjectBuildId: string): Promise<TeamEnergyData> {
    const ids = [...new Set([subjectBuildId, ...team.map((b) => b.id)])].slice(0, 4);
    const { data, error } = await this.api.GET('/api/v1/formula/energy', {
      params: { query: { subject_build_id: subjectBuildId, member_build_id: ids } },
    });
    if (error) throw new Error('Could not load the team\'s energy data');
    return data;
  }

  setCondition(key: string, value: ConditionValue): void {
    this.conditionals.update((state) => ({ ...state, [key]: value }));
  }

  /** Set one candidate weapon's passive condition (§46), keyed by the condition's own key. */
  setCandidateCondition(weaponId: string, condition: string, value: ConditionValue): void {
    this.candidateConditionals.update((all) => ({
      ...all, [weaponId]: { ...all[weaponId], [condition]: value },
    }));
  }

  resetConditions(): void {
    this.conditionals.set({});
    this.candidateConditionals.set({});
  }

  /** Every conditional set tier. Fetched once per session: it is catalogue data. */
  setTiers(): Promise<FormulaSetTier[]> {
    this.tiers ??= (async () => {
      const { data, error } = await this.api.GET('/api/v1/formula/set-effects');
      if (error) {
        this.tiers = null;
        throw new Error('Could not load the formula set effects');
      }
      return data.tiers as FormulaSetTier[];
    })();
    return this.tiers;
  }

  /** The team's active resonances. Fewer than four members with an element: none. */
  async resonances(team: readonly BuildRead[]): Promise<FormulaResonance[]> {
    const ids = [...new Set(team.map((b) => b.character_id).filter((id): id is string => !!id))];
    if (!ids.length) return [];
    const { data, error } = await this.api.GET('/api/v1/formula/resonance', {
      params: { query: { character_id: ids.slice(0, 4) } },
    });
    if (error) throw new Error('Could not load the team\'s elemental resonance');
    return data.active as FormulaResonance[];
  }

  /**
   * Every member's kit, resolved by the server's two-pass evaluation for this optimized build
   * (math-fallback P2): teammates' stats first, from their own builds, then each sheet in its
   * giver's context. Members with no sheet come back named, for "no kit buffs modelled".
   *
   * Rebuilt per subject and team, never cached across them: Bennett's buff depends on Bennett's
   * build, so a changed teammate is a changed number.
   */
  kits(
    team: readonly BuildRead[], subjectBuildId: string, weapon?: WeaponChoice,
  ): Promise<TeamKits> {
    // The optimized build is always a member: the server refuses a subject outside the team.
    const ids = [...new Set([subjectBuildId, ...team.map((b) => b.id)])].slice(0, 4);
    const key = kitKey(subjectBuildId, ids, weapon);
    const cached = this.kitCache.get(key);
    if (cached) return cached;
    const value = (async (): Promise<TeamKits> => {
      const { data, error } = await this.api.GET('/api/v1/formula/kit-buffs', {
        params: {
          query: {
            subject_build_id: subjectBuildId, member_build_id: ids,
            ...(weapon ? { subject_weapon_id: weapon.id } : {}),
            ...(weapon?.refinement ? { subject_weapon_refinement: weapon.refinement } : {}),
          },
        },
      });
      if (error) {
        this.kitCache.delete(key);
        throw new Error('Could not load the team\'s kit buffs');
      }
      const mine = (data.weapons ?? []).find((w) => w.is_subject);
      const sources = data.sources as FormulaKit[];
      return {
        sources: data.sources as FormulaKit[],
        missing: data.members.filter((m) => m.status === 'no_sheet').map((m) => m.name),
        raisedTalents: (data.raised_talents ?? []) as FormulaRaisedTalent[],
        missingWeapons: (data.weapons ?? [])
          .filter((w) => w.status === 'no_passive_data' && w.weapon)
          .map((w) => `${w.weapon} R${w.refinement} (${w.wielder})`),
        ...(mine ? {
          subjectWeapon: {
            name: mine.weapon, refinement: mine.refinement, status: mine.status,
            sourceId: mine.source_id ?? null,
          },
        } : {}),
        procs: sources
          .filter((s) => s.id === mine?.source_id)
          .flatMap((s) => (s.procs ?? []).map((p: FormulaProc) => ({
            source: s.id, key: p.key, label: p.label, weapon: mine?.weapon ?? '',
          }))),
      };
    })();
    // Bounded: a comparison asks a handful of weapons per team, never hundreds.
    if (this.kitCache.size > 32) this.kitCache.clear();
    this.kitCache.set(key, value);
    return value;
  }

  /**
   * The conditions the assumptions panel draws, for this team and these sets — and, given the
   * optimized build, every member's kit (P2).
   */
  async groups(
    team: readonly BuildRead[], setIds: Iterable<number>, subjectBuildId?: string,
  ): Promise<ConditionGroup[]> {
    const [resonances, tiers, kits] = await Promise.all([
      this.resonances(team),
      this.setTiers(),
      subjectBuildId ? this.kits(team, subjectBuildId) : Promise.resolve(undefined),
    ]);
    if (subjectBuildId) {
      // The energy section reads the same team; a failure leaves it saying nothing is known.
      this.energyData(team, subjectBuildId)
        .then((data) => this.teamEnergy.set(data))
        .catch(() => this.teamEnergy.set(null));
    }
    return conditionGroups(resonances, tiers, new Set(setIds), kits);
  }

  /**
   * Build the estimate: one search context per row, the team's resonance, every conditional
   * tier and the static pools, folded into recipes by `formulaCalibration`.
   */
  async estimate(request: FormulaRequest): Promise<FormulaEstimate> {
    const rows = this.rows();
    if (this.forBuild() !== request.buildId || !rows.length) {
      throw new Error('Choose at least one ability for the formula target.');
    }
    const [contexts, resonances, tiers, statics, kits, energy] = await Promise.all([
      // **The scope follows the row's move** where it is known: it decides which scoped stats
      // the server folds into the base (a normal-attack DMG bonus reaches a normal attack), so
      // one page-level scope would read a burst row as a normal attack.
      Promise.all(rows.map((row) => this.optimize.context(
        request.buildId, row.hit, request.channel, row.move ?? request.scope, request.enemyLevel,
        request.weapon?.id,
      ))),
      this.resonances(request.team),
      this.setTiers(),
      this.optimize.setBonuses(),
      this.kits(request.team, request.buildId, request.weapon),
      // The energy model (task 14). A failure leaves the estimate without one — ER worth
      // nothing, as before — rather than failing the estimate.
      this.energyData(request.team, request.buildId).catch(() => null),
    ]);
    // A candidate's run reads the candidate's own passive conditions (§46), never the equipped
    // run's under the same source id — on the team state and on each row's overrides alike.
    const candidateSource = request.weapon ? kits.subjectWeapon?.sourceId ?? null : null;
    const own = request.weapon ? this.candidateConditionals()[request.weapon.id] ?? {} : {};
    const teamState = request.weapon
      ? candidateConditionState(this.conditionals(), candidateSource, own)
      : this.conditionals();
    const formulaRows: FormulaRow[] = rows.map((row, i) => ({
      id: row.id,
      label: row.label,
      move: row.move,
      hit: row.reaction || row.proc
        ? null : { talent: row.hit.talent, label: row.hit.label, index: row.hit.index },
      count: row.count,
      context: kernelContext(contexts[i]),
      conditionals: request.weapon
        ? candidateConditionState(row.overrides, candidateSource, {})
        : row.overrides,
      reaction: row.reaction ?? null,
      additive: row.reaction || row.proc ? null : row.additive ?? null,
      proc: row.proc ?? null,
    }));
    const character = request.build.character;
    const lower = (e: string | null | undefined) => (e ? e.toLowerCase() : null);
    const formula = formulaCalibration({
      rows: formulaRows,
      team: {
        element: lower(character?.element) ?? '',
        weaponType: character?.weapon_type ?? '',
        memberElements: request.team.map((b) => lower(b.character?.element)),
      },
      resonances,
      setTiers: tiers,
      staticSetBonuses: statics.map((b: components['schemas']['KernelSetBonus']) => ({
        setId: b.set_id, piecesRequired: b.pieces_required, stats: b.stats,
      })),
      fourPieceSetIds: request.fourPieceSetIds,
      ...(energy ? (() => {
        const input = energyInput(energy, this.energy(), subjectHitsOf(rows), subjectOnFieldOf(rows));
        return input ? { energy: input } : {};
      })() : {}),
      conditionals: teamState as ConditionState,
      kits,
      characters: [character?.name ?? 'Build', ...request.team
        .filter((b) => b.id !== request.buildId)
        .map((b) => b.character?.name ?? '')
        .filter(Boolean)],
    });
    return {
      formula,
      kits,
      calibration: {
        noFourPiece: formula.noFourPiece,
        byFourPieceSet: formula.byFourPieceSet,
        byPair: formula.byPair,
        caveats: {
          unstable: [], staleConversions: [], fromCache: [], unscoredLabels: [],
          energyCost: null, energySweep: null,
        },
      },
    };
  }
}
