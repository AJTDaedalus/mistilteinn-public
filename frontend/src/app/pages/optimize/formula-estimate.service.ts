import { Injectable, inject, signal } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import type { Amplifying, ScalingStat } from '../../sim/damage';
import {
  conditionGroups,
  formulaCalibration,
  type ConditionGroup,
  type FormulaCalibration,
} from '../../sim/formula-calibration';
import {
  hitMove,
  type ConditionState,
  type ConditionValue,
  type FormulaKit,
  type FormulaResonance,
  type FormulaRow,
  type FormulaSetTier,
} from '../../sim/formula-recipe';
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
}

/** Every member's kit for one optimized build, and the members with none. */
export interface TeamKits {
  sources: FormulaKit[];
  missing: string[];
}

/** A calibration and the formula's own reporting, side by side. */
export interface FormulaEstimate {
  calibration: CalibrationResult;
  formula: FormulaCalibration;
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
  };
}

let nextRow = 0;

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

  private tiers: Promise<FormulaSetTier[]> | null = null;
  /** The last kit resolution, by subject and team: the panel and the estimate ask alike. */
  private kitCache: { key: string; value: Promise<TeamKits> } | null = null;

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

  setCondition(key: string, value: ConditionValue): void {
    this.conditionals.update((state) => ({ ...state, [key]: value }));
  }

  resetConditions(): void {
    this.conditionals.set({});
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
  kits(team: readonly BuildRead[], subjectBuildId: string): Promise<TeamKits> {
    // The optimized build is always a member: the server refuses a subject outside the team.
    const ids = [...new Set([subjectBuildId, ...team.map((b) => b.id)])].slice(0, 4);
    const key = `${subjectBuildId}|${ids.join(',')}`;
    if (this.kitCache?.key === key) return this.kitCache.value;
    const value = (async (): Promise<TeamKits> => {
      const { data, error } = await this.api.GET('/api/v1/formula/kit-buffs', {
        params: { query: { subject_build_id: subjectBuildId, member_build_id: ids } },
      });
      if (error) {
        this.kitCache = null;
        throw new Error('Could not load the team\'s kit buffs');
      }
      return {
        sources: data.sources as FormulaKit[],
        missing: data.members.filter((m) => m.status === 'no_sheet').map((m) => m.name),
      };
    })();
    this.kitCache = { key, value };
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
    const [contexts, resonances, tiers, statics, kits] = await Promise.all([
      // **The scope follows the row's move** where it is known: it decides which scoped stats
      // the server folds into the base (a normal-attack DMG bonus reaches a normal attack), so
      // one page-level scope would read a burst row as a normal attack.
      Promise.all(rows.map((row) => this.optimize.context(
        request.buildId, row.hit, request.channel, row.move ?? request.scope, request.enemyLevel,
      ))),
      this.resonances(request.team),
      this.setTiers(),
      this.optimize.setBonuses(),
      this.kits(request.team, request.buildId),
    ]);
    const formulaRows: FormulaRow[] = rows.map((row, i) => ({
      id: row.id,
      label: row.label,
      move: row.move,
      hit: { talent: row.hit.talent, label: row.hit.label },
      count: row.count,
      context: kernelContext(contexts[i]),
      conditionals: row.overrides,
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
      conditionals: this.conditionals() as ConditionState,
      kits,
      characters: [character?.name ?? 'Build', ...request.team
        .filter((b) => b.id !== request.buildId)
        .map((b) => b.character?.name ?? '')
        .filter(Boolean)],
    });
    return {
      formula,
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
