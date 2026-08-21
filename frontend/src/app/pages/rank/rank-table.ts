import {
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { ScrollingModule } from '@angular/cdk/scrolling';

import { totalRolls } from '../../shared/disc-rolls';
import { statMeta } from '../../shared/stat-meta';
import { defaultRankFilters } from './rank-filters';
import type { RankFilterState } from './rank-filters';
import { RankBreakdownPanel } from './rank-breakdown-panel';
import { RankService } from './rank.service';
import type { DiscScoreSchema, DiscRankSchema, TeamCalculateResponse } from './rank.service';
import type { DiscRead } from '../builds/discs.service';

interface SubstatRoll {
  stat: string;
  value: number;
  rolls: number;
}

const SUBSTAT_COLS = [
  { key: 'hp_pct',              label: 'HP%'  },
  { key: 'atk_pct',             label: 'ATK%' },
  { key: 'def_pct',             label: 'DEF%' },
  { key: 'hp',                  label: 'HP'   },
  { key: 'atk',                 label: 'ATK'  },
  { key: 'def',                 label: 'DEF'  },
  { key: 'crit_rate',           label: 'CR'   },
  { key: 'crit_dmg',            label: 'CD'   },
  { key: 'pen_flat',            label: 'PEN'  },
  { key: 'anomaly_proficiency', label: 'AP'   },
] as const;
type SubstatKey = (typeof SUBSTAT_COLS)[number]['key'];

type SortKey =
  | 'owner' | 'set_name' | 'slot' | 'rarity' | 'level' | 'main_stat'
  | SubstatKey
  | 'avg_pct' | 'max_pct'
  | 'best_build_avg' | 'best_build_max' | 'portfolio_avg';

interface RowViewModel {
  discId: string;
  owner: string;
  setIconUrl: string | null;
  setName: string;
  slot: string;
  rarity: string;
  level: string;
  mainStat: string;
  /** Pre-formatted substat strings, in SUBSTAT_COLS order. */
  substats: string[];
  avgPct: string;
  maxPct: string;
  // priority-list columns
  bestBuildAvg: string;
  bestBuildMax: string;
  portfolioAvg: string;
  bestBuildLabel: string;
  isBestBuildSupport: boolean;
  /** "vs equipped" / "vs best" for the winning context, or '' when unknown. D1/D2a. */
  bestBuildReferenceLabel: string;
  // raw sort values
  _sortOwner: string;
  _sortSetName: string;
  _sortSlot: number | null;
  _sortRarity: string | null;
  _sortLevel: number | null;
  _sortMainStat: string;
  _sortSubstats: (number | null)[];
  _sortAvgPct: number | null;
  _sortMaxPct: number | null;
  _sortBestBuildAvg: number | null;
  _sortBestBuildMax: number | null;
  _sortPortfolioAvg: number | null;
  _filterMainStatType: string;
  _filterSetId: string;
}

@Component({
  selector: 'rank-table',
  standalone: true,
  imports: [ScrollingModule, RankBreakdownPanel],
  templateUrl: './rank-table.html',
  styleUrl: './rank-table.scss',
})
export class RankTable {
  private rankService = inject(RankService);

  scores          = input<DiscScoreSchema[]>([]);
  discMap         = input<Record<string, DiscRead>>({});
  setNames        = input<Record<string, string>>({});
  setIcons        = input<Record<string, string | null>>({});
  buildNames      = input<Record<string, string>>({});
  filters         = input<RankFilterState>(defaultRankFilters());
  rankResults     = input<DiscRankSchema[] | null>(null);
  supportBuildIds = input<Set<string>>(new Set());

  protected sortKey = signal<SortKey>('avg_pct');
  protected sortDir = signal<'asc' | 'desc'>('desc');
  protected readonly substatCols = SUBSTAT_COLS;

  // Keystone deep-link (DESIGN §3.4 / B6) — evaluated on demand per row.
  protected breakdownOpen  = signal(false);
  protected breakdownLabel = signal('');
  protected breakdownLoading = signal(false);
  protected breakdownError  = signal<string | null>(null);
  protected breakdownResponse = signal<TeamCalculateResponse | null>(null);

  protected gridTemplate = computed(() => {
    const base = '140px 160px 48px 56px 48px 120px' + ' 56px'.repeat(10);
    return (this.hasPriorityList()
      ? base + ' 160px 160px 160px'
      : base + ' 80px 80px') + ' 90px';
  });

  protected trackByDiscId = (_: number, r: RowViewModel): string => r.discId;

  protected hasPriorityList = computed(() => {
    const r = this.rankResults();
    return r !== null && r.length > 0;
  });

  private rankMap = computed<Record<string, DiscRankSchema>>(() => {
    const results = this.rankResults();
    if (!results) return {};
    const map: Record<string, DiscRankSchema> = {};
    for (const r of results) map[r.disc_id] = r;
    return map;
  });

  /**
   * Keystone deep-link (DESIGN §3.4) — swap this row's disc into the
   * currently-equipped six of whichever context it scored best in, then
   * run the real calculator via /evaluate-discs. Reuses the disc's own
   * identity (set/main-stat, already shown in the row) plus the request
   * context surfaced on ``per_build`` (B6) — no rank-specific attribution
   * math involved.
   */
  protected async openBreakdown(discId: string): Promise<void> {
    const disc = this.discMap()[discId];
    const rankResult = this.rankMap()[discId];
    this.breakdownOpen.set(true);
    this.breakdownLoading.set(true);
    this.breakdownError.set(null);
    this.breakdownResponse.set(null);
    this.breakdownLabel.set(this.labelFor(discId));

    if (!disc || !rankResult) {
      this.breakdownLoading.set(false);
      this.breakdownError.set('No scoring data available for this disc.');
      return;
    }

    const ctx =
      rankResult.per_build.find((pb) => pb.build_id === rankResult.best_build_avg_build_id) ??
      rankResult.per_build[0];
    if (!ctx?.team_id || !ctx.combo_id || !ctx.enemy_profile_id) {
      this.breakdownLoading.set(false);
      this.breakdownError.set('This disc has no team/combo/enemy context to evaluate against.');
      return;
    }

    const slotToDiscId = new Map<number, string>();
    for (const d of Object.values(this.discMap())) {
      if (d.build_id === ctx.build_id) slotToDiscId.set(d.slot, d.id);
    }
    slotToDiscId.set(disc.slot, disc.id);

    try {
      const response = await this.rankService.evaluateDiscs(ctx.team_id, {
        comboId: ctx.combo_id,
        enemyProfileId: ctx.enemy_profile_id,
        activeIndex: ctx.active_index ?? 0,
        discIds: [...slotToDiscId.values()],
        // Explain it with the buff state THIS context ranked under, not the shared
        // store's — rank derives per-context state from build rows and never seeds it.
        buildId: ctx.build_id,
      });
      this.breakdownResponse.set(response);
    } catch (e) {
      this.breakdownError.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.breakdownLoading.set(false);
    }
  }

  protected closeBreakdown(): void {
    this.breakdownOpen.set(false);
    this.breakdownResponse.set(null);
    this.breakdownError.set(null);
  }

  private labelFor(discId: string): string {
    const disc = this.discMap()[discId];
    if (!disc) return discId;
    const setName = this.setNames()[String(disc.disc_set_id)] ?? '';
    return `${setName} · slot ${disc.slot}`.trim();
  }

  constructor() {
    effect(() => {
      const hasList = this.hasPriorityList();
      if (hasList) {
        untracked(() => {
          this.sortKey.set('best_build_avg');
          this.sortDir.set('desc');
        });
      } else {
        untracked(() => {
          this.sortKey.set('avg_pct');
          this.sortDir.set('desc');
        });
      }
    }, { allowSignalWrites: true });
  }

  /** Row view models built once per data change — no filter dependency. */
  private allViewModels = computed<RowViewModel[]>(() => {
    const discMap    = this.discMap();
    const setNames   = this.setNames();
    const setIcons   = this.setIcons();
    const buildNames = this.buildNames();
    const rankMap    = this.rankMap();
    const supports   = this.supportBuildIds();

    return this.scores().map(
      (s) => this.buildRow(s, discMap, setNames, setIcons, buildNames, rankMap, supports),
    );
  });

  /** Filtered view models — only filter reads here, no row rebuild. */
  private filteredViewModels = computed<RowViewModel[]>(() => {
    const f = this.filters();
    return this.allViewModels().filter((row) => {
      if (row._filterSetId === '') return true; // disc absent from discMap — pass through
      if (f.slot && row._sortSlot !== f.slot) return false;
      if (f.levelValue !== null) {
        const lv = row._sortLevel ?? 0;
        if (f.levelMode === 'min'   && lv < f.levelValue)  return false;
        if (f.levelMode === 'max'   && lv > f.levelValue)  return false;
        if (f.levelMode === 'exact' && lv !== f.levelValue) return false;
      }
      if (f.mainStats.length && !f.mainStats.includes(row._filterMainStatType)) return false;
      if (f.sets.length      && !f.sets.includes(row._filterSetId))             return false;
      if (f.rarities.length  && !f.rarities.includes(row._sortRarity ?? ''))    return false;
      return true;
    });
  });

  /** Sorted view models — only the sort comparisons run here. */
  protected rows = computed<RowViewModel[]>(() => {
    const key  = this.sortKey();
    const dir  = this.sortDir();
    const mult = dir === 'asc' ? 1 : -1;

    return [...this.filteredViewModels()].sort((a, b) => {
      const av = this.rawSortValue(a, key);
      const bv = this.rawSortValue(b, key);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === 'string' && typeof bv === 'string') return mult * av.localeCompare(bv);
      return mult * ((av as number) - (bv as number));
    });
  });

  protected setSort(key: SortKey): void {
    if (this.sortKey() === key) {
      this.sortDir.update((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      this.sortKey.set(key);
      this.sortDir.set('desc');
    }
  }

  protected sortIndicator(key: SortKey): string {
    if (this.sortKey() !== key) return '';
    return this.sortDir() === 'desc' ? ' ↓' : ' ↑';
  }

  private buildRow(
    score: DiscScoreSchema,
    discMap: Record<string, DiscRead>,
    setNames: Record<string, string>,
    setIcons: Record<string, string | null>,
    buildNames: Record<string, string>,
    rankMap: Record<string, DiscRankSchema>,
    supports: Set<string>,
  ): RowViewModel {
    const disc      = discMap[score.disc_id];
    const setIdStr  = disc ? String(disc.disc_set_id) : '';
    const subs      = (disc?.substats as unknown as SubstatRoll[] | undefined) ?? [];

    const avgPctVal = score.baseline_damage === 0
      ? null
      : (score.mean_improvement / score.baseline_damage) * 100;
    const maxPctVal = score.baseline_damage === 0
      ? null
      : (score.max_improvement / score.baseline_damage) * 100;

    const rankResult = rankMap[score.disc_id];
    const bestBuildAvgVal  = rankResult?.best_build_avg  ?? null;
    const bestBuildMaxVal  = rankResult?.best_build_max  ?? null;
    const portfolioAvgVal  = rankResult?.portfolio_avg   ?? null;
    const bestBuildBuildId = rankResult?.best_build_avg_build_id ?? '';

    // D1/D2a — label the winning context's mode; never affects the sort key,
    // which is best_build_avg (already norm_pct-uniform — see PerBuildBreakdown).
    const winningPerBuild = rankResult?.per_build.find((pb) => pb.build_id === bestBuildBuildId);
    const bestBuildReferenceLabel = winningPerBuild?.reference_mode === 'best'
      ? 'vs best'
      : winningPerBuild?.reference_mode === 'equipped'
        ? 'vs equipped'
        : '';

    // main stat
    let mainStat = '—';
    if (disc) {
      const { label, unit } = statMeta(disc.main_stat_type as string);
      mainStat = unit === 'bp'
        ? `${label} ${(disc.main_stat_value / 100).toFixed(1)}%`
        : `${label} ${disc.main_stat_value}`;
    }

    // substats — one formatted string per SUBSTAT_COLS entry
    const substatStrs = SUBSTAT_COLS.map(({ key }) => {
      const sub = subs.find((s) => s.stat === key);
      if (!sub) return '';
      const { unit } = statMeta(key);
      const formatted = unit === 'bp'
        ? `${(sub.value / 100).toFixed(1)}%`
        : String(sub.value);
      return `${formatted} (${totalRolls(sub.rolls)})`;
    });

    // raw substat values for sorting
    const sortSubstats = SUBSTAT_COLS.map(({ key }) => {
      const sub = subs.find((s) => s.stat === key);
      return sub?.value ?? null;
    });

    return {
      discId:  score.disc_id,
      owner:   disc?.build_id ? (buildNames[disc.build_id] ?? '—') : '—',
      setIconUrl: setIcons[setIdStr] ?? null,
      setName: disc ? (setNames[setIdStr] ?? setIdStr) : '—',
      slot:    disc ? String(disc.slot) : '—',
      rarity:  disc?.rarity as string ?? '—',
      level:   disc ? String(disc.level) : '—',
      mainStat,
      substats: substatStrs,
      avgPct:  formatPct(avgPctVal),
      maxPct:  formatPct(maxPctVal),
      bestBuildAvg:      formatPct(bestBuildAvgVal),
      bestBuildMax:      formatPct(bestBuildMaxVal),
      portfolioAvg:      formatPct(portfolioAvgVal),
      bestBuildLabel:    bestBuildBuildId ? (buildNames[bestBuildBuildId] ?? '') : '',
      isBestBuildSupport: supports.has(bestBuildBuildId),
      bestBuildReferenceLabel,
      _sortOwner:      disc?.build_id ? (buildNames[disc.build_id] ?? '') : '',
      _sortSetName:    disc ? (setNames[setIdStr] ?? setIdStr) : '',
      _sortSlot:       disc ? (disc.slot as unknown as number) : null,
      _sortRarity:     disc?.rarity as string ?? null,
      _sortLevel:      disc?.level ?? null,
      _sortMainStat:   mainStat,
      _sortSubstats:   sortSubstats,
      _sortAvgPct:     avgPctVal,
      _sortMaxPct:     maxPctVal,
      _sortBestBuildAvg: bestBuildAvgVal,
      _sortBestBuildMax: bestBuildMaxVal,
      _sortPortfolioAvg: portfolioAvgVal,
      _filterMainStatType: disc ? (disc.main_stat_type as string ?? '') : '',
      _filterSetId: setIdStr,
    };
  }

  private rawSortValue(row: RowViewModel, key: SortKey): string | number | null {
    switch (key) {
      case 'owner':          return row._sortOwner;
      case 'set_name':       return row._sortSetName;
      case 'slot':           return row._sortSlot;
      case 'rarity':         return row._sortRarity;
      case 'level':          return row._sortLevel;
      case 'main_stat':      return row._sortMainStat;
      case 'avg_pct':        return row._sortAvgPct;
      case 'max_pct':        return row._sortMaxPct;
      case 'best_build_avg': return row._sortBestBuildAvg;
      case 'best_build_max': return row._sortBestBuildMax;
      case 'portfolio_avg':  return row._sortPortfolioAvg;
      default: {
        const idx = SUBSTAT_COLS.findIndex((c) => c.key === key);
        return idx >= 0 ? (row._sortSubstats[idx] ?? null) : null;
      }
    }
  }
}

function formatPct(val: number | null): string {
  if (val === null) return '—';
  return `${val.toFixed(2)}%`;
}
