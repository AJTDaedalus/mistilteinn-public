import {
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { MAIN_STAT_BY_SLOT } from '../../shared/disc-list/disc-filters';
import { STAT_META } from '../../shared/stat-meta';
import { FormsModule } from '@angular/forms';

import { BuildsService, type BuildRead } from '../builds/builds.service';
import { CombosService, type ComboRead } from '../builds/combos.service';
import { CalculateService, type EnemyProfileRead } from '../calculate/calculate.service';
import { DiscSetsService, type DiscSetSummary } from '../optimize/disc-sets.service';
import { discSetIconUrl } from '../../shared/icon-url';
import {
  buffContextForBuilds,
  type BuffContextDefaults,
} from '../../shared/buff-context.store';
import { defaultEnemyId, ENEMY_TABS, filterEnemiesByTab, type EnemyTab } from '../../shared/enemy-tabs';
import type { RankContextInput } from './rank.service';

const ALL_MAIN_STATS = [...new Set(Object.values(MAIN_STAT_BY_SLOT).flat())];
const RARITY_OPTIONS = ['S', 'A', 'B'] as const;

export interface PriorityBuildRow {
  id: number;
  buildId: string | null;
  /** When set, combos are loaded from this build and the context is emitted
   *  as build_id=comboBuildId + support_slot=(auto-detected). Used when the
   *  selected build is a pure support with no combos of its own. */
  comboBuildId: string | null;
  comboId: string | null;
  enemyProfileId: string | null;
  weight: number;
  allowedSetIds: number[] | null;
  supportSlot: number | null;
  availableSupportSlots: number[];
  mainStats: string[];
  rarities: string[];
  combos: ComboRead[];
  loadingCombos: boolean;
}

@Component({
  selector: 'priority-builds-panel',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './priority-builds-panel.html',
  styleUrl: './priority-builds-panel.scss',
})
export class PriorityBuildsPanel {
  private buildsService = inject(BuildsService);
  private combosService = inject(CombosService);
  private calcService = inject(CalculateService);
  private discSetsService = inject(DiscSetsService);

  /** Whether the panel is shown (toggled from outside). */
  visible = input<boolean>(false);

  /** Emits the full context list whenever any row changes (null = not ready). */
  contextsChange = output<RankContextInput[] | null>();

  /** Emits combined (OR) display-filter state from all rows. */
  filtersChange = output<{ mainStats: string[]; rarities: string[] }>();

  /** Emits when the user clicks Score Discs. */
  scoreRequested = output<void>();

  protected builds = signal<BuildRead[]>([]);
  protected enemies = signal<EnemyProfileRead[]>([]);
  protected enemyTab = signal<EnemyTab>('bosses');
  protected readonly enemyTabs = ENEMY_TABS;
  protected filteredEnemies = computed(() => filterEnemiesByTab(this.enemies(), this.enemyTab()));
  protected allSets = signal<DiscSetSummary[]>([]);
  protected rows = signal<PriorityBuildRow[]>([]);
  protected errorMessage = signal<string | null>(null);

  protected readonly rarityOptions = RARITY_OPTIONS;
  protected readonly mainStatOptions = ALL_MAIN_STATS.map((k) => ({
    key: k,
    label: STAT_META[k]?.label ?? k,
  }));
  protected iconUrl = discSetIconUrl;
  protected isReady = computed(() => {
    const rs = this.rows();
    return rs.length > 0 && rs.every((r) => r.buildId && r.comboId && r.enemyProfileId);
  });

  private nextId = 0;

  constructor() {
    void this.init();
  }

  private async init() {
    try {
      const [builds, enemies, sets] = await Promise.all([
        this.buildsService.list(),
        this.calcService.listEnemies(),
        this.discSetsService.listSets(),
      ]);
      this.builds.set(builds);
      this.enemies.set(enemies);
      this.allSets.set(sets);
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected addRow() {
    const row: PriorityBuildRow = {
      id: this.nextId++,
      buildId: null,
      comboBuildId: null,
      comboId: null,
      enemyProfileId: defaultEnemyId(this.enemies(), this.enemyTab()),
      weight: 1,
      allowedSetIds: null,
      supportSlot: null,
      availableSupportSlots: [],
      mainStats: [],
      rarities: [],
      combos: [],
      loadingCombos: false,
    };
    this.rows.update((rs) => [...rs, row]);
    this.emitContexts();
  }

  protected removeRow(id: number) {
    this.rows.update((rs) => rs.filter((r) => r.id !== id));
    this.emitContexts();
  }

  protected async onBuildChange(rowId: number, buildId: string) {
    this.rows.update((rs) =>
      rs.map((r) =>
        r.id === rowId
          ? {
              ...r,
              buildId: buildId || null,
              comboBuildId: null,
              comboId: null,
              combos: [],
              loadingCombos: !!buildId,
              allowedSetIds: null,
              supportSlot: null,
              availableSupportSlots: [],
            }
          : r,
      ),
    );
    if (!buildId) {
      this.emitContexts();
      return;
    }
    try {
      const [combos, discs] = await Promise.all([
        this.combosService.listForBuild(buildId),
        this.buildsService.listDiscsForBuild(buildId),
      ]);
      const equippedSetUuids = new Set(discs.map((d) => d.disc_set_id));
      const hakushinIds = this.allSets()
        .filter((s) => equippedSetUuids.has(s.id))
        .map((s) => s.hakushin_id);
      // TODO: support-slot auto-detection is unimplemented (detectSupportSlot()
      // below is also stubbed to null) — availableSupportSlots is always empty.
      const availableSupportSlots: number[] = [];
      this.rows.update((rs) =>
        rs.map((r) =>
          r.id === rowId
            ? {
                ...r,
                combos,
                comboId: combos[0]?.id ?? null,
                loadingCombos: false,
                allowedSetIds: hakushinIds.length > 0 ? hakushinIds : null,
                availableSupportSlots,
              }
            : r,
        ),
      );
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
      this.rows.update((rs) =>
        rs.map((r) => (r.id === rowId ? { ...r, loadingCombos: false } : r)),
      );
    }
    this.emitContexts();
  }

  protected onSupportSlotChange(rowId: number, value: string) {
    const supportSlot = value ? Number(value) : null;
    this.rows.update((rs) =>
      rs.map((r) => (r.id === rowId ? { ...r, supportSlot } : r)),
    );
    this.emitContexts();
  }

  protected async onComboBuildChange(rowId: number, comboBuildId: string) {
    if (!comboBuildId) {
      this.rows.update((rs) =>
        rs.map((r) => r.id === rowId ? { ...r, comboBuildId: null, combos: [], comboId: null } : r),
      );
      this.emitContexts();
      return;
    }
    this.rows.update((rs) =>
      rs.map((r) => r.id === rowId ? { ...r, comboBuildId, loadingCombos: true, comboId: null } : r),
    );
    try {
      const combos = await this.combosService.listForBuild(comboBuildId);
      this.rows.update((rs) =>
        rs.map((r) =>
          r.id === rowId
            ? { ...r, combos, comboId: combos[0]?.id ?? null, loadingCombos: false }
            : r,
        ),
      );
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
      this.rows.update((rs) =>
        rs.map((r) => r.id === rowId ? { ...r, loadingCombos: false } : r),
      );
    }
    this.emitContexts();
  }

  protected onComboChange(rowId: number, comboId: string) {
    this.rows.update((rs) =>
      rs.map((r) => (r.id === rowId ? { ...r, comboId: comboId || null } : r)),
    );
    this.emitContexts();
  }

  protected onEnemyChange(rowId: number, enemyId: string) {
    this.rows.update((rs) =>
      rs.map((r) => (r.id === rowId ? { ...r, enemyProfileId: enemyId || null } : r)),
    );
    this.emitContexts();
  }

  /** One tab governs every row's enemy list — re-defaults any row whose
   *  current pick gets filtered out by the tab switch. */
  protected onEnemyTabChange(tab: EnemyTab) {
    this.enemyTab.set(tab);
    const visible = new Set(filterEnemiesByTab(this.enemies(), tab).map((e) => e.id));
    this.rows.update((rs) =>
      rs.map((r) =>
        r.enemyProfileId && visible.has(r.enemyProfileId)
          ? r
          : { ...r, enemyProfileId: defaultEnemyId(this.enemies(), tab) },
      ),
    );
    this.emitContexts();
  }

  protected onWeightChange(rowId: number, value: number) {
    const w = Number.isFinite(value) && value > 0 ? value : 1;
    this.rows.update((rs) => rs.map((r) => (r.id === rowId ? { ...r, weight: w } : r)));
    this.emitContexts();
  }

  protected toggleSet(rowId: number, hakushinId: number) {
    this.rows.update((rs) =>
      rs.map((r) => {
        if (r.id !== rowId) return r;
        const ids = r.allowedSetIds ?? [];
        const next = ids.includes(hakushinId)
          ? ids.filter((id) => id !== hakushinId)
          : [...ids, hakushinId];
        return { ...r, allowedSetIds: next.length > 0 ? next : null };
      }),
    );
    this.emitContexts();
  }

  protected clearSets(rowId: number) {
    this.rows.update((rs) =>
      rs.map((r) => (r.id === rowId ? { ...r, allowedSetIds: null } : r)),
    );
    this.emitContexts();
  }

  protected toggleRowMainStat(rowId: number, key: string) {
    this.rows.update((rs) =>
      rs.map((r) => {
        if (r.id !== rowId) return r;
        const ms = r.mainStats;
        return { ...r, mainStats: ms.includes(key) ? ms.filter((x) => x !== key) : [...ms, key] };
      }),
    );
    this.emitFilters();
  }

  protected toggleRowRarity(rowId: number, r: string) {
    this.rows.update((rs) =>
      rs.map((row) => {
        if (row.id !== rowId) return row;
        const rs2 = row.rarities;
        return { ...row, rarities: rs2.includes(r) ? rs2.filter((x) => x !== r) : [...rs2, r] };
      }),
    );
    this.emitFilters();
  }

  protected isRowMainStatSelected(row: PriorityBuildRow, key: string): boolean {
    return row.mainStats.includes(key);
  }

  protected isRowRaritySelected(row: PriorityBuildRow, r: string): boolean {
    return row.rarities.includes(r);
  }

  async loadContexts(contexts: RankContextInput[]): Promise<void> {
    this.rows.set([]);
    const rowPromises = contexts.map(async (ctx) => {
      const base: PriorityBuildRow = {
        id: this.nextId++,
        buildId: ctx.build_id ?? null,
        comboBuildId: null,
        comboId: ctx.combo_id,
        enemyProfileId: ctx.enemy_profile_id,
        weight: ctx.weight ?? 1,
        allowedSetIds: ctx.allowed_set_ids ?? null,
        supportSlot: ctx.support_slot ?? null,
        availableSupportSlots: [],
        mainStats: [],
        rarities: [],
        combos: [],
        loadingCombos: true,
      };
      // TODO: support-slot auto-detection is unimplemented (detectSupportSlot()
      // below is also stubbed to null) — availableSupportSlots is always empty.
      const availableSupportSlots: number[] = [];
      try {
        const combos = ctx.build_id
          ? await this.combosService.listForBuild(ctx.build_id)
          : [];
        return { ...base, combos, loadingCombos: false, availableSupportSlots };
      } catch (e) {
        this.errorMessage.set(e instanceof Error ? e.message : String(e));
        return { ...base, loadingCombos: false, availableSupportSlots };
      }
    });
    const rows = await Promise.all(rowPromises);
    this.rows.set(rows);
    this.emitContexts();
  }

  protected requestScore() {
    if (this.isReady()) this.scoreRequested.emit();
  }

  protected isSetSelected(row: PriorityBuildRow, hakushinId: number): boolean {
    return (row.allowedSetIds ?? []).includes(hakushinId);
  }

  protected buildLabel(b: BuildRead): string {
    return b.id;
  }

  protected setHint(row: PriorityBuildRow): string {
    const ids = row.allowedSetIds;
    if (!ids || ids.length === 0) return 'all sets';
    return `${ids.length} set${ids.length === 1 ? '' : 's'}`;
  }

  private emitContexts() {
    const rows = this.rows();
    const ready = rows.every(
      (r) => r.buildId && r.comboId && r.enemyProfileId,
    );
    if (rows.length === 0 || !ready) {
      this.contextsChange.emit(null);
      return;
    }
    const contexts: RankContextInput[] = rows.map((r) => {
      if (r.comboBuildId && r.comboBuildId !== r.buildId) {
        return {
          build_id: r.comboBuildId,
          combo_id: r.comboId!,
          enemy_profile_id: r.enemyProfileId!,
          weight: r.weight,
          allowed_set_ids: r.allowedSetIds,
          support_slot: this.detectSupportSlot(r.buildId!, r.comboBuildId),
          // The context targets the combo's build; the row's own build is the
          // support being ranked, and the backend snapshots it too on the
          // support_slot path — so its disabled_buffs belong in the union.
          ...(this.buffContextFor(r.comboBuildId, r.buildId) ?? {}),
        };
      }
      return {
        build_id: r.buildId!,
        combo_id: r.comboId!,
        enemy_profile_id: r.enemyProfileId!,
        weight: r.weight,
        allowed_set_ids: r.allowedSetIds,
        support_slot: r.supportSlot,
        ...(this.buffContextFor(r.buildId!) ?? {}),
      };
    });
    this.contextsChange.emit(contexts);
    this.emitFilters();
  }

  /**
   * Per-context buff state for one priority row (DESIGN §2.5, #95), seeded
   * from that row's own target build rather than from the shared store — a
   * priority job ranks N unrelated builds, so one broadcast value is wrong for
   * all but at most one of them.
   *
   * `targetId` heads the list (its `active_conditions`/`stack_counts` win);
   * any further ids contribute only to the `disabled_buffs` union. Returns
   * null when the target's row isn't loaded, so the caller keeps the store
   * fallback instead of sending an empty context.
   */
  private buffContextFor(targetId: string, ...alsoSnapshotted: (string | null)[]): BuffContextDefaults | null {
    const byId = new Map(this.builds().map((b) => [b.id, b]));
    const target = byId.get(targetId);
    if (!target) return null;
    const others = alsoSnapshotted
      .filter((id): id is string => !!id && id !== targetId)
      .map((id) => byId.get(id))
      .filter((b): b is BuildRead => !!b);
    return buffContextForBuilds([target, ...others]);
  }

  // TODO: unimplemented — always returns null (no support-slot auto-detection yet).
  private detectSupportSlot(_supportBuildId: string, _mainBuildId: string): number | null {
    return null;
  }

  private emitFilters() {
    const rows = this.rows();
    // OR logic: if any row has no filter, show all; otherwise union.
    const anyNoMain = rows.some((r) => r.mainStats.length === 0);
    const anyNoRarity = rows.some((r) => r.rarities.length === 0);
    this.filtersChange.emit({
      mainStats: anyNoMain ? [] : [...new Set(rows.flatMap((r) => r.mainStats))],
      rarities: anyNoRarity ? [] : [...new Set(rows.flatMap((r) => r.rarities))],
    });
  }

  get rowCount(): number {
    return this.rows().length;
  }
}
