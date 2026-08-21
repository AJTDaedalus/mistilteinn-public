import { Component, input, output } from '@angular/core';
import type { OptimizationJobSummary } from './rank.service';

@Component({
  selector: 'rank-jobs-list',
  standalone: true,
  imports: [],
  templateUrl: './rank-jobs-list.html',
  styleUrl: './rank-jobs-list.scss',
})
export class RankJobsList {
  jobs = input<OptimizationJobSummary[]>([]);

  view = output<string>();
  cancelJob = output<string>();

  progressPct(job: OptimizationJobSummary): number {
    if (!job.assignments_total) return 0;
    return Math.round((job.assignments_done / job.assignments_total) * 100);
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  isTerminal(job: OptimizationJobSummary): boolean {
    return ['succeeded', 'failed', 'cancelled'].includes(job.status);
  }
}
