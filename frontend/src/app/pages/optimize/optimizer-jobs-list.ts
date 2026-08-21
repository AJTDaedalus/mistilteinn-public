import { Component, input, output } from '@angular/core';
import type { OptimizationJobSummary } from './optimizer.service';

@Component({
  selector: 'optimizer-jobs-list',
  standalone: true,
  imports: [],
  templateUrl: './optimizer-jobs-list.html',
  styleUrl: './optimizer-jobs-list.scss',
})
export class OptimizerJobsList {
  jobs = input<OptimizationJobSummary[]>([]);

  view = output<string>();
  delete = output<string>();

  progressPct(job: OptimizationJobSummary): number {
    if (!job.assignments_total) return 0;
    return Math.round((job.assignments_done / job.assignments_total) * 100);
  }

  formatEta(eta: number | null): string {
    if (eta === null) return '—';
    if (eta < 60) return `${Math.ceil(eta)}s`;
    const m = Math.floor(eta / 60);
    const s = Math.ceil(eta % 60);
    return `${m}m ${s}s`;
  }

  formatDamage(dmg: number | null): string {
    if (dmg === null) return '—';
    return dmg.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  isTerminal(job: OptimizationJobSummary): boolean {
    return ['succeeded', 'failed', 'cancelled'].includes(job.status);
  }
}
