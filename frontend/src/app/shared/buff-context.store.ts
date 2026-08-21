import { Injectable, signal } from '@angular/core';

import type { components } from '../api/api.types';
import { CUSTOM_BUFF_PREFIX, customBuffId } from './custom-buff-id';

/**
 * One user-authored stage buff — a Deadly Assault / Shiyu stage effect (#64).
 *
 * Aliased from the generated API types rather than redeclared: a preset is applied by
 * copying its buffs straight into a request, so the stored shape and the request shape
 * must be the same shape, and a local duplicate would be free to drift from the schema
 * that actually validates it.
 */
export type CustomBuff = components['schemas']['CustomBuff'];

/** The BuffContext shape every calc endpoint accepts (DESIGN_buff_context.md §2.1). */
export interface BuffContext {
  active_conditions: string[];
  stack_counts: Record<string, number>;
  disabled_buffs: string[];
  custom_buffs: CustomBuff[];
}

/**
 * The build-derived half of a `BuffContext` — everything a build row can seed.
 *
 * `custom_buffs` is deliberately outside it: a stage buff belongs to the encounter, not
 * to a build, so no build column stores one and nothing derived from a build should be
 * able to *clear* one. Rank's per-context producers spread this object straight into a
 * request context (DESIGN §2.5), and a `custom_buffs: []` in that spread would silently
 * strip the stage buffs from every ranked context.
 */
export type BuffContextDefaults = Omit<BuffContext, 'custom_buffs'>;

function defaultContext(): BuffContext {
  return { active_conditions: ['always'], stack_counts: {}, disabled_buffs: [], custom_buffs: [] };
}

/**
 * The subset of a build row {@link BuffContextStore.seedFromBuilds} needs.
 * `BuildRead` satisfies this structurally — declared locally so `shared/`
 * keeps no dependency on a `pages/` service.
 */
export interface BuildBuffDefaults {
  id: string;
  active_conditions?: string[] | null;
  stack_counts?: Record<string, number> | null;
  disabled_buffs?: string[] | null;
}

/**
 * Derive one {@link BuffContext} from the builds a calculation runs against —
 * DESIGN §2.2's "client owns defaulting", as a pure function.
 *
 * The first build is the target (DPS, or the team member at `active_index`);
 * the rest are its supports. `active_conditions`/`stack_counts` come from the
 * target alone, since both are run-level in `BuffContext` and not
 * agent-qualified. `disabled_buffs` is the deduped union across every member —
 * entries are agent-qualified `buff_id()` values, so one flat list addresses
 * the whole team (§2.1).
 *
 * Exported and pure so the single-target store path ({@link
 * BuffContextStore.seedFromBuilds}) and rank's N-contexts-per-submit path
 * (DESIGN §2.5, #95) share one derivation and cannot drift.
 */
export function buffContextForBuilds(builds: readonly BuildBuffDefaults[]): BuffContextDefaults {
  const [target] = builds;
  if (!target) {
    const { active_conditions, stack_counts, disabled_buffs } = defaultContext();
    return { active_conditions, stack_counts, disabled_buffs };
  }
  return {
    active_conditions: [...(target.active_conditions ?? [])],
    stack_counts: { ...(target.stack_counts ?? {}) },
    disabled_buffs: [...new Set(builds.flatMap((b) => b.disabled_buffs ?? []))],
  };
}

/**
 * Shared, request-scoped buff-state store (DESIGN_buff_context.md §2.1/§3, Task A8).
 *
 * One `BuffContext`, editable per run, serialized verbatim into every
 * simulate/optimizer/damage/rank request (via {@link context}). `seed()`
 * populates it from a build's own columns as *defaults* (DESIGN §2.2) — it
 * never writes back. Persisting an edit to a build is buff-toggles.ts's
 * separate, explicit action (Task A11); this store only holds the
 * current-run value in memory.
 *
 * `providedIn: 'root'` makes this one instance per app session, so a value
 * seeded or edited on one page (e.g. the Builds defaults editor) carries
 * into whatever calc a user runs next, without every page needing its own
 * buff-editing UI.
 */
@Injectable({ providedIn: 'root' })
export class BuffContextStore {
  private readonly activeConditionsSignal = signal<string[]>(['always']);
  private readonly stackCountsSignal = signal<Record<string, number>>({});
  private readonly disabledBuffsSignal = signal<string[]>([]);
  private readonly customBuffsSignal = signal<CustomBuff[]>([]);

  readonly activeConditions = this.activeConditionsSignal.asReadonly();
  readonly stackCounts = this.stackCountsSignal.asReadonly();
  readonly disabledBuffs = this.disabledBuffsSignal.asReadonly();
  readonly customBuffs = this.customBuffsSignal.asReadonly();

  /**
   * Build ids the current value was last seeded from, so re-selecting the
   * same calc target is a no-op rather than a clobber of this run's edits.
   * Null after an explicit {@link seed} — that came from somewhere other than
   * a calc target, so the next target should still get to seed over it.
   */
  private seededFor: string | null = null;

  /**
   * The serialized context every request body should read from.
   *
   * A plain method rather than a `computed` on purpose: a `computed` hands
   * every caller the same memoized object, so request bodies — which embed
   * this directly — would share mutable arrays with the store and with each
   * other. This returns a fresh snapshot per call. It still reads the signals,
   * so calling it inside a reactive context tracks them as normal.
   */
  context(): BuffContext {
    return {
      active_conditions: [...this.activeConditionsSignal()],
      stack_counts: { ...this.stackCountsSignal() },
      disabled_buffs: [...this.disabledBuffsSignal()],
      custom_buffs: this.customBuffsSignal().map((b) => ({ ...b })),
    };
  }

  /**
   * Populate the store from a build's own `active_conditions`/`stack_counts`/
   * `disabled_buffs` columns (or any equivalent already-merged source — e.g.
   * buff-toggles.ts derives `disabled_buffs` across DPS + both supports from
   * one `listBuffs()` response before calling this). Does not touch the DB;
   * purely an in-memory seed.
   */
  seed(context: BuffContextDefaults): void {
    this.seededFor = null;
    this.activeConditionsSignal.set([...context.active_conditions]);
    this.stackCountsSignal.set({ ...context.stack_counts });
    this.setDisabledBuffs(context.disabled_buffs);
    // Deliberately NOT reset from the seed: no build column stores stage buffs, so
    // every seed carries an empty list, and clearing here would wipe the encounter the
    // user is evaluating against every time they switch build or navigate. `reset()`
    // is the explicit way to clear them.
  }

  /**
   * Seed from the builds a calculation is about to run against — the other
   * half of DESIGN §2.2's "client owns defaulting". Without this, a user who
   * never opens the Builds defaults editor calculates with the store's empty
   * initial context, silently dropping every condition and disabled buff they
   * saved. `/simulate` and the optimizer used to inherit that state
   * server-side off the build row; §2.1 removed the fallback, so the client
   * has to supply it.
   *
   * The derivation itself is {@link buffContextForBuilds}; this adds the
   * store-specific part.
   *
   * Idempotent per target: re-seeding the same build ids does nothing, so an
   * edit made during this run survives an unrelated re-render. A *different*
   * target reseeds, which is what keeps build A's context from leaking into a
   * calculation for build B. That guard is exactly why rank cannot call this
   * for its N contexts (§2.5) — it calls {@link buffContextForBuilds} directly.
   */
  seedFromBuilds(builds: readonly BuildBuffDefaults[]): void {
    if (builds.length === 0) return;
    const key = builds.map((b) => b.id).join('|');
    if (key === this.seededFor) return;

    this.seed(buffContextForBuilds(builds));
    this.seededFor = key;
  }

  /** Back to the server's own defaults (`['always']` / `{}` / `[]` / no stage buffs). */
  reset(): void {
    // Straight to the signal, not through `setDisabledBuffs` — reset is the one path
    // that is meant to drop the `custom:` toggles too, since it drops the buffs as well.
    this.disabledBuffsSignal.set([]);
    this.customBuffsSignal.set([]);
    this.seed(defaultContext());
  }

  setActiveConditions(conditions: string[]): void {
    this.activeConditionsSignal.set([...conditions]);
  }

  toggleCondition(condition: string): void {
    const next = new Set(this.activeConditionsSignal());
    if (next.has(condition)) {
      next.delete(condition);
    } else {
      next.add(condition);
    }
    this.activeConditionsSignal.set([...next]);
  }

  /**
   * Override how many stacks of `sourceLabel` are applied. Clamped to
   * `[0, maxStacks]`; a clamped value equal to `maxStacks` drops the
   * override (matches buff-toggles.ts's existing convention — fully
   * stacked is the unmarked default, not a pinned number).
   */
  setStack(sourceLabel: string, stacks: number, maxStacks: number): void {
    const clamped = Math.max(0, Math.min(stacks, maxStacks));
    const next = { ...this.stackCountsSignal() };
    if (clamped === maxStacks) {
      delete next[sourceLabel];
    } else {
      next[sourceLabel] = clamped;
    }
    this.stackCountsSignal.set(next);
  }

  /**
   * Replace the *kit* half of `disabled_buffs`, keeping every `custom:` entry.
   *
   * Both callers of this — `seed()` from a build's columns, and the Builds page's kit
   * toggle — produce lists derived entirely from kit buffs, because no build column ever
   * stores a stage buff's id. A plain replace therefore erased the off-switch of every
   * stage buff whenever the user changed build, changed team, or toggled any unrelated
   * kit buff: the buff itself survived (it is exempt from seeding) and came back
   * *applied*. A toggle that undoes itself on an unrelated edit is the one thing a toggle
   * may not do, and it fails silently — the number moves, nothing says why.
   */
  setDisabledBuffs(ids: readonly string[]): void {
    const stageBuffToggles = this.disabledBuffsSignal().filter((id) =>
      id.startsWith(CUSTOM_BUFF_PREFIX),
    );
    const kitToggles = ids.filter((id) => !id.startsWith(CUSTOM_BUFF_PREFIX));
    this.disabledBuffsSignal.set([...new Set([...kitToggles, ...stageBuffToggles])]);
  }

  /**
   * Replace the whole stage-buff list — what applying a preset does (DESIGN §2.4).
   *
   * Applying **copies**: the buffs become this run's own, with no live link back to the
   * preset row. Editing that preset afterwards therefore cannot retroactively change a
   * result already computed with it.
   */
  setCustomBuffs(buffs: readonly CustomBuff[]): void {
    this.customBuffsSignal.set(buffs.map((b) => ({ ...b })));
    this.pruneOrphanedStageBuffToggles();
  }

  /** Append one stage buff. */
  addCustomBuff(buff: CustomBuff): void {
    this.customBuffsSignal.set([...this.customBuffsSignal(), { ...buff }]);
  }

  /** Replace the stage buff at `index`; out-of-range indices are a no-op. */
  updateCustomBuff(index: number, buff: CustomBuff): void {
    const current = this.customBuffsSignal();
    if (index < 0 || index >= current.length) return;
    const next = [...current];
    next[index] = { ...buff };
    this.customBuffsSignal.set(next);
    this.pruneOrphanedStageBuffToggles();
  }

  /**
   * Remove the stage buff at `index`, and any `disabled_buffs` entry addressing it.
   *
   * Leaving the id behind would be invisible until the user re-created a buff with the
   * same label, which would then arrive switched off for no reason they could see.
   */
  removeCustomBuff(index: number): void {
    const current = this.customBuffsSignal();
    if (index < 0 || index >= current.length) return;
    this.customBuffsSignal.set(current.filter((_, i) => i !== index));
    this.pruneOrphanedStageBuffToggles();
  }

  /**
   * Drop `custom:` entries in `disabled_buffs` that no longer name a live stage buff.
   *
   * The id is derived from the label, so an off-switch outlives the buff it belonged to
   * unless something clears it — and since `setDisabledBuffs` now deliberately *preserves*
   * the `custom:` half, nothing else ever would. A user who switched "DA Stage 3" off,
   * cleared the list, then applied a preset containing a buff of the same name would get
   * it back already switched off, with nothing on screen explaining why. Same failure the
   * remove path was written to avoid, reached by a different route.
   *
   * Kit ids are untouched: those name buffs on builds this store knows nothing about.
   */
  private pruneOrphanedStageBuffToggles(): void {
    const live = new Set(this.customBuffsSignal().map((b) => customBuffId(b.label)));
    this.disabledBuffsSignal.set(
      this.disabledBuffsSignal().filter(
        (id) => !id.startsWith(CUSTOM_BUFF_PREFIX) || live.has(id),
      ),
    );
  }

  toggleBuff(id: string, enabled: boolean): void {
    const next = new Set(this.disabledBuffsSignal());
    if (enabled) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.disabledBuffsSignal.set([...next]);
  }
}
