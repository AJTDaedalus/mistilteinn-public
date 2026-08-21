import {
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';

import { BuffContextStore } from '../../shared/buff-context.store';
import { statMeta, formatStatValue } from '../../shared/stat-meta';
import {
  BuffDescriptor,
  BuffGroup,
  BuildConditionItem,
  BuildsService,
} from './builds.service';

interface BuffRow extends BuffDescriptor {
  /** Pre-formatted per-stack preview ("+30.00%", "+1000", etc.). */
  preview: string;
  /** "DMG %", "CRIT Rate", "Fire DMG %", "PEN", etc. */
  statLabel: string;
  /** Whether this buff stacks (max_stacks > 1) — drives the stack input. */
  stackable: boolean;
  /** Applied stack count: the user's override, else max_stacks. */
  stacks: number;
  /** Effective total across the applied stacks ("= +18.00%"); null when not stackable. */
  totalPreview: string | null;
}

interface DisplayGroup extends Omit<BuffGroup, 'buffs'> {
  buffs: BuffRow[];
}

const ROLE_TITLE: Record<string, string> = {
  dps: 'DPS',
  support1: 'Support 1',
  support2: 'Support 2',
};

const ROLE_ORDER = ['dps', 'support1', 'support2'] as const;

function formatPreview(stat: string, value: number): string {
  return formatStatValue(stat, value);
}

/**
 * Stack state for one buff row.
 *
 * A stackable buff with no saved override is applied at max stacks — the
 * backend assumes the same (ActiveConditions.get_stacks), because in-game
 * these stacks sit at cap for the window being optimized. The total mirrors
 * whatever count is actually applied, so the row never advertises a number
 * the engine doesn't contribute.
 */
function stackState(
  stat: string,
  value: number,
  maxStacks: number,
  override: number | undefined,
): { stackable: boolean; stacks: number; totalPreview: string | null } {
  if (maxStacks <= 1) {
    return { stackable: false, stacks: 1, totalPreview: null };
  }
  const stacks = Math.min(override ?? maxStacks, maxStacks);
  return {
    stackable: true,
    stacks,
    totalPreview: `= ${formatStatValue(stat, value * stacks)}`,
  };
}

@Component({
  selector: 'buff-toggles',
  imports: [],
  templateUrl: './buff-toggles.html',
  styleUrl: './buff-toggles.scss',
})
export class BuffTogglesPanel {
  private svc = inject(BuildsService);
  private buffContext = inject(BuffContextStore);

  /** ID of the DPS build. Used to call listBuffs (which returns all roles). */
  buildId = input<string | null>(null);

  /** Maps role → build ID so toggle() can PATCH the correct build. */
  roleToBuildId = input<Record<string, string | null>>({
    dps: null,
    support1: null,
    support2: null,
  });

  /**
   * Bumped by the parent after any save that can change buff-affecting state
   * (mindscape, W-Engine, core skill level, ...) without changing `buildId`
   * itself. `buildId` alone doesn't change on an edit-in-place save, so the
   * refresh effect below tracks this too.
   */
  reloadKey = input<number>(0);

  protected groups = signal<BuffGroup[]>([]);
  protected availableConditions = signal<BuildConditionItem[]>([]);
  protected activeConditions = signal<Set<string>>(new Set());
  protected stackCounts = signal<Record<string, number>>({});
  protected loading = signal(false);
  protected error = signal<string | null>(null);

  protected readonly roleOrder = ROLE_ORDER;
  protected readonly roleTitle = ROLE_TITLE;

  /** Raw buff groups decorated with the display fields the template needs. */
  private displayGroups = computed<DisplayGroup[]>(() => {
    const stacks = this.stackCounts();
    return this.groups().map((g) => ({
      ...g,
      buffs: g.buffs.map((b) => ({
        ...b,
        preview: formatPreview(b.stat, b.value),
        statLabel: statMeta(b.stat).label,
        ...stackState(b.stat, b.value, b.max_stacks, stacks[b.source_label]),
      })),
    }));
  });

  /** Bucket the flat group list into role sections for rendering. */
  protected groupsByRole = computed<{ role: string; groups: DisplayGroup[] }[]>(() => {
    const byRole = new Map<string, DisplayGroup[]>();
    for (const g of this.displayGroups()) {
      const list = byRole.get(g.role) ?? [];
      list.push(g);
      byRole.set(g.role, list);
    }
    return ROLE_ORDER
      .filter((role) => byRole.has(role))
      .map((role) => ({ role, groups: byRole.get(role) ?? [] }));
  });

  constructor() {
    effect(() => {
      const id = this.buildId();
      // Tracked for its dependency only — a bump forces this effect to re-run
      // after an in-place save, where `buildId` is unchanged. Not dead code.
      this.reloadKey();
      if (!id) {
        this.groups.set([]);
        this.availableConditions.set([]);
        this.activeConditions.set(new Set());
        return;
      }
      void this.refresh(id);
    });
  }

  private async refresh(buildId: string) {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [res, build, conditions] = await Promise.all([
        this.svc.listBuffs(buildId),
        this.svc.get(buildId),
        this.svc.listConditions(buildId),
      ]);
      this.groups.set(res.groups);
      this.availableConditions.set(conditions);
      this.activeConditions.set(new Set(build.active_conditions ?? []));
      this.stackCounts.set({ ...(build.stack_counts ?? {}) });

      // Seed the shared per-run store from these defaults (Task A8/A11) --
      // disabled_buffs comes from `groups`, which already covers DPS + both
      // supports in one response, so it's the full merged list DESIGN §2.1
      // expects without a second fetch.
      this.buffContext.seed({
        active_conditions: [...(build.active_conditions ?? [])],
        stack_counts: { ...(build.stack_counts ?? {}) },
        disabled_buffs: this.allDisabledBuffIds(res.groups),
      });
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  /** Flat, agent-qualified disabled-buff ids across every role (DPS + both supports). */
  private allDisabledBuffIds(groups: BuffGroup[]): string[] {
    return groups.flatMap((g) => g.buffs.filter((b) => !b.enabled).map((b) => b.id));
  }

  protected async toggleCondition(cond: string) {
    const id = this.buildId();
    if (!id) return;

    const next = new Set(this.activeConditions());
    if (next.has(cond)) {
      next.delete(cond);
    } else {
      next.add(cond);
    }
    this.activeConditions.set(next);
    this.buffContext.setActiveConditions([...next]);

    try {
      await this.svc.update(id, { active_conditions: [...next] });
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      if (id) void this.refresh(id);
    }
  }

  /**
   * Override how many stacks of *buff* are applied.
   *
   * Keyed by ``source_label`` — that is the key the backend resolves stacks
   * by (ActiveConditions.get_stacks). Clearing the override back to
   * ``max_stacks`` drops the key so the buff follows the fully-stacked
   * default rather than pinning a number that a data fix might outgrow.
   */
  protected async setStack(buff: BuffRow, stacks: number) {
    const id = this.buildId();
    if (!id) return;

    const clamped = Math.max(0, Math.min(stacks, buff.max_stacks));
    const nextStacks = { ...this.stackCounts() };
    if (clamped === buff.max_stacks) {
      delete nextStacks[buff.source_label];
    } else {
      nextStacks[buff.source_label] = clamped;
    }
    this.stackCounts.set(nextStacks);
    this.buffContext.setStack(buff.source_label, stacks, buff.max_stacks);

    try {
      await this.svc.update(id, { stack_counts: nextStacks });
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      if (id) void this.refresh(id);
    }
  }

  protected async toggle(buffId: string, currentlyEnabled: boolean) {
    // Find which role this buff belongs to.
    let buffRole: string | null = null;
    for (const g of this.groups()) {
      if (g.buffs.some((r) => r.id === buffId)) {
        buffRole = g.role;
        break;
      }
    }
    if (!buffRole) return;

    const targetId = this.roleToBuildId()[buffRole] ?? this.buildId();
    if (!targetId) return;

    // Optimistic flip in groups — revert via refresh() if PATCH fails.
    const nextGroups = this.groups().map((g) => ({
      ...g,
      buffs: g.buffs.map((r) =>
        r.id === buffId ? { ...r, enabled: !currentlyEnabled } : r,
      ),
    }));
    this.groups.set(nextGroups);

    // Derive disabled_buffs for the target build from the flipped groups.
    const disabledForTarget = nextGroups
      .filter((g) => g.role === buffRole)
      .flatMap((g) => g.buffs.filter((b) => !b.enabled).map((b) => b.id));

    // Mirror into the shared store using the *full* merged list (all roles) --
    // BuffContext.disabled_buffs is one flat, agent-qualified list per DESIGN
    // §2.1, not per-build like the PATCH below.
    this.buffContext.setDisabledBuffs(this.allDisabledBuffIds(nextGroups));

    try {
      await this.svc.update(targetId, { disabled_buffs: disabledForTarget });
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      const dpsId = this.buildId();
      if (dpsId) void this.refresh(dpsId);
    }
  }
}
