import { Component, computed, input } from '@angular/core';

import { rollupSubstats } from './disc-rollup';
import { formatStatLabel, formatStatValue } from './stat-format';
import type { OptimizerDiscBuildSchema } from './optimizer.service';

@Component({
  selector: 'optimizer-build-detail',
  standalone: true,
  templateUrl: './optimizer-build-detail.html',
  styleUrl: './optimizer-build-detail.scss',
})
export class OptimizerBuildDetail {
  build = input.required<OptimizerDiscBuildSchema>();

  protected rollup = computed(() => rollupSubstats(this.build().discs ?? []));

  protected readonly statKeys: { key: string; label: string }[] = [
    { key: 'atk',                 label: 'ATK'                 },
    { key: 'crit_rate',           label: 'CRIT Rate'           },
    { key: 'crit_dmg',            label: 'CRIT DMG'            },
    { key: 'pen_ratio',           label: 'PEN %'               },
    { key: 'pen_flat',            label: 'PEN'                 },
    { key: 'anomaly_proficiency', label: 'Anomaly Proficiency' },
  ];

  protected statValue(key: string): string {
    const stats = this.build().total_stats as Record<string, number> | undefined;
    const val = stats?.[key];
    if (val === undefined) return '—';
    return formatStatValue(key, val);
  }

  protected formatStatLabel(stat: string): string {
    return formatStatLabel(stat);
  }

  protected formatMainStat(statType: string, value: number): string {
    return formatStatValue(statType, value);
  }

  protected formatSubstat(statType: string, value: number): string {
    return formatStatValue(statType, value);
  }

  protected formatScore(score: number | null | undefined): string {
    if (score == null) return '—';
    return score.toFixed(2);
  }
}
