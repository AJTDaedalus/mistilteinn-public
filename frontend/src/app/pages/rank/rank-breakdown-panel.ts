import { Component, computed, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';

import { fmtMultBp } from '../calculate/format-helpers';
import type { TeamCalculateResponse } from './rank.service';

/**
 * Minimal keystone deep-link view (DESIGN §3.4 / B6) — proves the rank page
 * can reach full calculator-grade attribution for a candidate disc without
 * any rank-specific attribution math. The polished full-equation "Details"
 * view (per-zone drill-down, KaTeX, etc.) is Track A/B's F1/F3 — this panel
 * only needs to be correct, not final.
 */
@Component({
  selector: 'rank-breakdown-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './rank-breakdown-panel.html',
  styleUrl: './rank-breakdown-panel.scss',
})
export class RankBreakdownPanel {
  discLabel = input<string>('');
  loading = input(false);
  error = input<string | null>(null);
  response = input<TeamCalculateResponse | null>(null);

  closed = output<void>();

  protected readonly gainPct = computed(() => {
    const delta = this.response()?.delta;
    if (!delta) return null;
    const sign = delta.pct_change >= 0 ? '+' : '';
    return `${sign}${delta.pct_change.toFixed(2)}%`;
  });

  // False when a zone varies across same-type steps (partial stun window,
  // standard+anomaly mix) — the per-zone gain shares are then approximate.
  protected readonly deltaApproximate = computed(
    () => this.response()?.delta?.is_exact === false,
  );

  protected readonly zoneRows = computed(() => {
    const delta = this.response()?.delta;
    if (!delta) return [];
    return delta.zone_deltas.map((z) => ({
      zone: z.zone,
      fromMult: fmtMultBp(z.from_bp),
      toMult: fmtMultBp(z.to_bp),
      sharePct: `${z.gain_share_pct.toFixed(1)}%`,
    }));
  });

  protected close(): void {
    this.closed.emit();
  }

  /** Dismiss only when the backdrop itself is clicked, not the panel inside it. */
  protected onBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.close();
    }
  }
}
