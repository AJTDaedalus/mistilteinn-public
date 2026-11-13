import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import type { components } from '../../api/api.types';

export type GcsimStatus = components['schemas']['GcsimStatusRead'];

/** `high_plunge` → `high plunge`: gcsim's action keys, readable. */
function spoken(action: string): string {
  return action.replace(/_/g, ' ');
}

/**
 * What gcsim can simulate of a character, weapon or set — **before** a search, not after one.
 *
 * `DESIGN_team_math_fallback.md` §1: the catalogue, the team builder and the optimizers used
 * to find out only when a search failed with a 422. The server computes the status on read
 * (D-F1) and this draws it.
 *
 * **Nothing for `full`.** A badge on every card that says "fine" is noise that trains the eye
 * to skip the badge; only the exceptions are marked.
 *
 * **The words are the signal, colour is the second channel** — the rule `ElementChip` and
 * `WeaponMark` already follow. `none` says *No gcsim* and carries gcsim's own refusal as its
 * tooltip; `partial` says *Partial gcsim* and names the moves gcsim does not implement, because
 * "partial" alone would leave the reader to guess which ones.
 *
 * **Plunges and movement do not make a character partial** (owner, 2026-11-13): `partial` is
 * a missing normal, charged/aimed, skill or burst. A `full` character gcsim cannot plunge with
 * still lists the plunges in `missing_actions`, and gets a *quiet* mark — faint, borderless,
 * "No plunge" — so the tooltip has somewhere to live without ranking beside a real gap.
 */
@Component({
  selector: 'gcsim-badge',
  template: `
    @if (label(); as text) {
      <span
        class="badge"
        [class.badge--none]="gcsim()?.status === 'none'"
        [class.badge--quiet]="gcsim()?.status === 'full'"
        [attr.title]="detail()"
        [attr.aria-label]="text + '. ' + detail()"
      >{{ text }}</span>
    }
  `,
  styles: `
    :host { display: inline-flex; }
    .badge {
      display: inline-block;
      padding: 0 var(--space-2);
      border: 1px solid var(--surface-rule);
      border-radius: var(--radius-pill);
      color: var(--ink-dim);
      font-size: var(--text-xs);
      line-height: 1.5;
      white-space: nowrap;
    }
    .badge--quiet {
      border-color: transparent;
      color: var(--ink-faint);
    }
    .badge--none {
      border-color: var(--warning);
      color: var(--warning);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GcsimBadge {
  /** The entry's `gcsim` block. Absent renders nothing — absent is not a claim. */
  readonly gcsim = input<GcsimStatus | null | undefined>(null);

  protected readonly label = computed(() => {
    switch (this.gcsim()?.status) {
      case 'none':
        return 'No gcsim';
      case 'partial':
        return 'Partial gcsim';
      case 'full':
      {
        const missing = this.gcsim()?.missing_actions ?? [];
        if (!missing.length) return null;
        return missing.every((a) => a.endsWith('plunge')) ? 'No plunge' : 'Minor gcsim gaps';
      }
      default:
        return null;
    }
  });

  protected readonly detail = computed(() => {
    const status = this.gcsim();
    if (!status) return '';
    if (status.status === 'none') {
      return status.reason ?? 'gcsim cannot simulate this at the pinned version.';
    }
    const missing = (status.missing_actions ?? []).map(spoken).join(', ');
    return status.status === 'full'
      ? `gcsim does not implement: ${missing}. Not partial: only a missing normal, charged, `
        + 'skill or burst makes a character partial.'
      : `gcsim does not implement: ${missing}.`;
  });
}
