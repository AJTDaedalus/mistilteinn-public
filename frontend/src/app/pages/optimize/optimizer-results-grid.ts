import {
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { OptimizerBuildDetail } from './optimizer-build-detail';
import type { OptimizerDiscBuildSchema, OptimizerDiscSummary } from './optimizer.service';
import { discSetIconUrl } from '../../shared/icon-url';
import { RankBreakdownPanel } from '../rank/rank-breakdown-panel';
import { RankService } from '../rank/rank.service';
import type { TeamCalculateResponse } from '../rank/rank.service';

interface SetPill { setId: string; count: number; name: string; iconUrl: string | null; }

type StatSortKey = 'atk' | 'crit_rate' | 'crit_dmg' | 'pen_ratio' | 'anomaly_proficiency';
type SortKey = 'total_damage' | 'delta' | StatSortKey;

const STAT_COLUMNS: { key: StatSortKey; label: string; bpField: boolean }[] = [
  { key: 'atk', label: 'ATK', bpField: false },
  { key: 'crit_rate', label: 'CR', bpField: true },
  { key: 'crit_dmg', label: 'CD', bpField: true },
  { key: 'pen_ratio', label: 'PR', bpField: true },
  { key: 'anomaly_proficiency', label: 'AP', bpField: false },
];

@Component({
  selector: 'optimizer-results-grid',
  standalone: true,
  imports: [OptimizerBuildDetail, RankBreakdownPanel],
  templateUrl: './optimizer-results-grid.html',
  styleUrl: './optimizer-results-grid.scss',
})
export class OptimizerResultsGrid {
  // Reuses RankService.evaluateDiscs directly (B6's keystone deep-link) --
  // it's a generic /evaluate-discs client with nothing rank-specific about
  // the implementation, so a second copy here would just be duplication.
  private rankService = inject(RankService);

  results = input<OptimizerDiscBuildSchema[]>([]);
  currentBuildDamage = input<number | null>(null);
  equip = output<string[]>();

  // Keystone deep-link context (DESIGN §3.1-3.2, F3) -- from the job's
  // stored DiscOptimizeRequest. null when the job predates team-context
  // submission or wasn't run against a team, in which case the breakdown
  // button stays disabled (no /evaluate-discs call can be made without it).
  teamId = input<string | null>(null);
  comboId = input<string | null>(null);
  enemyProfileId = input<string | null>(null);
  activeIndex = input<number>(0);

  protected sortKey = signal<SortKey>('total_damage');
  protected expandedIdx = signal<number | null>(null);
  protected readonly statColumns = STAT_COLUMNS;

  protected breakdownOpen = signal(false);
  protected breakdownLabel = signal('');
  protected breakdownLoading = signal(false);
  protected breakdownError = signal<string | null>(null);
  protected breakdownResponse = signal<TeamCalculateResponse | null>(null);

  protected hasDeepLinkContext = computed(
    () => !!this.teamId() && !!this.comboId() && !!this.enemyProfileId(),
  );

  protected sorted = computed(() => {
    const key = this.sortKey();
    const base = this.currentBuildDamage();
    return [...this.results()].sort((a, b) => {
      if (key === 'delta' && base) {
        return (b.total_damage - base) - (a.total_damage - base);
      }
      if (key === 'total_damage') {
        return b.total_damage - a.total_damage;
      }
      // Stat sort: descending
      const av = (a.total_stats as Record<string, number>)?.[key] ?? 0;
      const bv = (b.total_stats as Record<string, number>)?.[key] ?? 0;
      return bv - av;
    });
  });

  protected delta(dmg: number): number | null {
    const base = this.currentBuildDamage();
    if (!base) return null;
    return (dmg - base) / base;
  }

  protected deltaClass(dmg: number): string {
    const d = this.delta(dmg);
    if (d === null) return '';
    return d >= 0 ? 'positive' : 'negative';
  }

  protected formatDelta(dmg: number): string {
    const d = this.delta(dmg);
    if (d === null) return '—';
    const sign = d >= 0 ? '+' : '';
    return `${sign}${(d * 100).toFixed(1)}%`;
  }

  protected formatStat(build: OptimizerDiscBuildSchema, key: StatSortKey, bpField: boolean): string {
    const val = (build.total_stats as Record<string, number>)?.[key];
    if (val === undefined) return '—';
    if (bpField) return `${(val / 100).toFixed(1)}%`;
    return String(val);
  }

  protected setPillsFor(build: OptimizerDiscBuildSchema): SetPill[] {
    // Index discs by set_id so we can resolve name + icon for each set in set_counts.
    const bySetId = new Map<string, OptimizerDiscSummary>();
    for (const disc of build.discs ?? []) {
      const key = String(disc.set_id);
      if (!bySetId.has(key)) bySetId.set(key, disc);
    }
    return Object.entries(build.set_counts ?? {})
      .map(([setId, count]) => {
        const disc = bySetId.get(setId);
        return {
          setId,
          count,
          name: disc?.set_name ?? setId,
          iconUrl: discSetIconUrl(disc?.icon_path),
        };
      })
      .sort((a, b) => b.count - a.count); // 4p first, then 2p(s)
  }

  protected toggleExpand(idx: number) {
    this.expandedIdx.set(this.expandedIdx() === idx ? null : idx);
  }

  protected isExpanded(idx: number) {
    return this.expandedIdx() === idx;
  }

  protected onEquip(build: OptimizerDiscBuildSchema) {
    this.equip.emit(build.disc_ids);
  }

  /**
   * Keystone deep-link (DESIGN §3.1-3.2, F3) -- evaluate this candidate
   * combo's discs through the real calculator, comparing against the
   * equipped set (same evaluate-discs + compare_to='equipped' pattern as
   * the rank page's B6 breakdown).
   */
  protected async openBreakdown(build: OptimizerDiscBuildSchema, idx: number): Promise<void> {
    this.breakdownOpen.set(true);
    this.breakdownLoading.set(true);
    this.breakdownError.set(null);
    this.breakdownResponse.set(null);
    this.breakdownLabel.set(`Result #${idx + 1}`);

    const teamId = this.teamId();
    const comboId = this.comboId();
    const enemyProfileId = this.enemyProfileId();
    if (!teamId || !comboId || !enemyProfileId) {
      this.breakdownLoading.set(false);
      this.breakdownError.set('This run has no team/combo/enemy context to evaluate against.');
      return;
    }

    try {
      const response = await this.rankService.evaluateDiscs(teamId, {
        comboId,
        enemyProfileId,
        activeIndex: this.activeIndex(),
        discIds: build.disc_ids,
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

  protected discSetName(disc: OptimizerDiscSummary): string {
    return disc.set_name || String(disc.set_id);
  }
}
