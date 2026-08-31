import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * One substat's rolls, drawn as a bar each.
 *
 * Extracted from the artifacts page because a second surface needed it (`BACKLOG_optimize.md`
 * §16, cards on the result rows). The bars themselves were easy to copy; **what they claim**
 * is not, and that is the part worth having one owner for. Three separate rules decide it —
 * an unknown tier is not tier zero, an estimated count is not a fact, and a tie is weaker
 * than an estimate but stronger than nothing — and a second hand-rolled copy would have kept
 * the colours and quietly lost the caveats.
 */

/** What is known about one substat. Mirrors `SubstatAnalysisRead` in the API contract. */
export interface SubstatReading {
  /** The line as the user reads it — `CRIT DMG +24.9%`. */
  label: string;
  /** Rolls behind it, or null when even the count is unsettled. */
  rolls: number | null;
  /** Each roll's tier `0`-`3`, or null. */
  tiers: number[] | null;
  /** True when `tiers` is the only combination of its length rather than one reading. */
  tiersExact: boolean;
  /** True when `rolls` is the likeliest count rather than the only possible one. */
  estimated: boolean;
  /** The line as a multiple of one best-case roll. `3.2` reads as "3.2 max rolls". */
  rollValue: number | null;
}

/** The two API shapes a reading is assembled from. Structural, so no import is needed. */
interface RawSubstat { stat?: string; value?: unknown }
interface RawAnalysis {
  rolls?: number | null;
  roll_tiers?: number[] | null;
  roll_tiers_exact?: boolean;
  roll_value?: number | null;
  estimated?: boolean;
}

/**
 * Build the readings for one artifact from `substats` and `substat_analysis`.
 *
 * **Positional, and that is the contract**: the server emits one analysis entry per substat
 * in the same order, with an empty entry where a line could not be read. Matching them any
 * other way — by stat key, say — would silently mis-pair a piece holding the same stat twice.
 *
 * Shared because both the inventory rows and the optimize cards need it, and the defaults are
 * where a second copy would go wrong: `tiersExact` falls back to **true** (an absent flag
 * means the old, always-exact contract) while `estimated` falls back to **false**. Getting
 * either backwards would caveat every line, or none of them.
 */
export function substatReadings(
  substats: readonly RawSubstat[] | null | undefined,
  analysis: readonly (RawAnalysis | null | undefined)[] | null | undefined,
  label: (stat: string, value: unknown) => string,
): SubstatReading[] {
  return (substats ?? []).map((sub, index) => {
    const found = analysis?.[index];
    return {
      label: label(sub?.stat ?? 'unknown', sub?.value),
      rolls: found?.rolls ?? null,
      tiers: found?.roll_tiers ?? null,
      tiersExact: found?.roll_tiers_exact ?? true,
      estimated: found?.estimated ?? false,
      rollValue: found?.roll_value ?? null,
    };
  });
}

/**
 * The bars to draw: the tier of each roll, or `-1` per roll when only the count is known.
 *
 * `-1` renders undifferentiated rather than as tier 0 — the worst tier and "we do not know
 * which tier" are different claims, and colouring the second as the first would tell the
 * reader a line is bad on no evidence.
 *
 * Since the backend adopted Genshin Optimizer's reading, an established count always carries
 * tiers, so the `-1` path no longer arrives from this API. It stays because `tiers` is
 * nullable in the contract, and degrading to grey beats degrading to "worst".
 */
export function rollBars(sub: SubstatReading): number[] {
  if (sub.tiers) return sub.tiers;
  if (!sub.rolls) return [];
  return Array.from({ length: Math.min(sub.rolls, 6) }, () => -1);
}

/** What the bars are claiming, for the `title`. Unlabelled grey bars mean nothing. */
export function barsTitle(sub: SubstatReading): string | null {
  if (!sub.rolls) return null;
  const rolls = `${sub.rolls} roll${sub.rolls === 1 ? '' : 's'}`;
  // **Estimated first.** Checking `tiers` first returned the confident wording for a guessed
  // count, so the one case that most needs the caveat was the one that lost it.
  if (sub.estimated) return `${rolls} — the likeliest reading, not the only one`;
  // A tie is a weaker caveat than an estimate: the *count* is certain, and only which tiers
  // add up to it is not.
  if (sub.tiers && !sub.tiersExact) return `${rolls}, shaded by one reading of several that fit`;
  if (sub.tiers) return `${rolls}, shaded by how high each rolled`;
  return `${rolls}; which of them rolled high cannot be told apart`;
}

/** `3.2` → `320`, for the roll-value column. */
export function rollValuePercent(sub: SubstatReading): number | null {
  return sub.rollValue === null ? null : Math.round(sub.rollValue * 100);
}

@Component({
  selector: 'substat-bars',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="sub__label mono">{{ sub().label }}</span>
    <span class="sub__bars" [attr.title]="title()">
      @for (tier of bars(); track $index) {
        <i class="bar" [attr.data-tier]="tier"></i>
      }
    </span>
    @if (showRollValue()) {
      <span class="sub__rv mono">
        @if (percent(); as rv) { {{ rv }}% } @else { — }
      </span>
    }
  `,
  styleUrl: './substat-bars.scss',
})
export class SubstatBars {
  readonly sub = input.required<SubstatReading>();
  /** Off on the small cards, where there is no room for a third column. */
  readonly showRollValue = input(true);

  protected readonly bars = computed(() => rollBars(this.sub()));
  protected readonly title = computed(() => barsTitle(this.sub()));
  protected readonly percent = computed(() => rollValuePercent(this.sub()));
}
