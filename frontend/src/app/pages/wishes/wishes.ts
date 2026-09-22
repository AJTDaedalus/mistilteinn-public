import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  WishesService,
  type WishIncomeVersionRead,
  type WishLimits,
  type WishPlanRead,
} from './wishes.service';

/** The three spending tiers the bookkeeping workbook publishes. */
const TIERS = ['f2p', 'welkin', 'welkin_bp'] as const;
type Tier = (typeof TIERS)[number];

/** How long to wait after the last keystroke before asking the backend. */
const DEBOUNCE_MS = 250;

/**
 * The wish planner — odds of reaching a constellation or refinement on a given budget.
 *
 * `docs/DESIGN_wish_planner.md`. Laid out after Fribbels' Warp Planner, deliberately, so that
 * anyone who has used that one already knows this one: a settings panel, a resource line that
 * shows its own arithmetic, and a goal table with a proportional bar behind each rung.
 *
 * Two differences, both argued in the DESIGN:
 *
 * - **Capturing Radiance**, which HSR has no equivalent of, as a "50/50s lost" control beside
 *   Guaranteed. It is worth up to 22 points of the answer and without it the mechanic is
 *   invisible for the most common question anyone asks.
 * - **Whole patches** of projected income rather than Fribbels' half-patches. The workbook has
 *   no phase structure, and splitting a patch in two would be inventing precision the source
 *   does not have.
 */
@Component({
  selector: 'app-wishes',
  imports: [FormsModule, DecimalPipe, DatePipe],
  templateUrl: './wishes.html',
  styleUrl: './wishes.scss',
})
export class WishesPage {
  private service = inject(WishesService);

  protected readonly banner = signal<'character' | 'weapon'>('character');
  protected readonly primogems = signal(0);
  protected readonly intertwined = signal(0);
  protected readonly pity = signal(0);
  protected readonly guaranteed = signal(false);
  protected readonly lostFiftyFifties = signal(0);
  protected readonly ownedCopies = signal(0);
  protected readonly tier = signal<Tier>('f2p');
  protected readonly selectedVersions = signal<ReadonlySet<string>>(new Set());

  protected readonly limits = signal<WishLimits | null>(null);
  protected readonly income = signal<WishIncomeVersionRead[]>([]);
  protected readonly incomeFetchedAt = signal<string | null>(null);
  protected readonly plan = signal<WishPlanRead | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly pending = signal(false);

  /**
   * Capturing Radiance applies to the character banner only, so the control disappears on the
   * weapon banner — and the banked losses have to go with it, or the next request is refused.
   */
  protected readonly showsRadiance = computed(
    () => this.limits()?.banners[this.banner()]?.capturing_radiance ?? false,
  );

  protected readonly hardPity = computed(
    () => this.limits()?.banners[this.banner()]?.hard_pity ?? 90,
  );

  protected readonly maxOwned = computed(() => {
    const limits = this.limits();
    if (!limits) return 0;
    return this.banner() === 'character' ? limits.max_constellation : limits.max_refinement - 1;
  });

  /** Wishes the wallet alone is worth. */
  protected readonly walletWishes = computed(() => {
    const per = this.limits()?.primogems_per_wish ?? 160;
    return Math.floor(this.primogems() / per) + this.intertwined();
  });

  /** Wishes from the patches the user has ticked, at the chosen tier. */
  protected readonly projectedWishes = computed(() => {
    const chosen = this.selectedVersions();
    const tier = this.tier();
    return Math.floor(
      this.income()
        .filter((version) => chosen.has(version.version))
        .reduce((total, version) => total + version[tier], 0),
    );
  });

  protected readonly budget = computed(() => this.walletWishes() + this.projectedWishes());

  /** True once the counter alone guarantees the next 50/50, so the page can say why. */
  protected readonly radianceIsCertain = computed(
    () => this.showsRadiance() && this.lostFiftyFifties() >= (this.limits()?.max_lost_fifty_fifties ?? 3),
  );

  /** Versions still ahead, newest first — nobody budgets for a patch that has been and gone. */
  protected readonly upcoming = computed(() => this.income().slice(-8).reverse());

  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    void this.load();
    // Recompute when anything the request depends on moves, debounced. Firing per keystroke
    // would send `9`, `99`, `999` on the way to `9999` — the defect CLAUDE.md records for the
    // materials editor, one layer up.
    effect(() => {
      const request = this.request();
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => void this.recompute(request), DEBOUNCE_MS);
    });
  }

  private request() {
    return {
      banner: this.banner(),
      primogems: this.primogems(),
      intertwined_fate: this.intertwined(),
      extra_wishes: this.projectedWishes(),
      pity: this.pity(),
      guaranteed: this.guaranteed(),
      lost_fifty_fifties: this.showsRadiance() ? this.lostFiftyFifties() : 0,
      owned_copies: this.ownedCopies(),
    };
  }

  private async load(): Promise<void> {
    try {
      const [limits, income] = await Promise.all([this.service.limits(), this.service.income()]);
      this.limits.set(limits);
      this.income.set(income.versions);
      this.incomeFetchedAt.set(income.fetched_at ?? null);
    } catch {
      this.error.set('Could not load the planner’s reference data.');
    }
  }

  private async recompute(request: ReturnType<WishesPage['request']>): Promise<void> {
    this.pending.set(true);
    try {
      this.plan.set(await this.service.plan(request));
      this.error.set(null);
    } catch (caught) {
      this.plan.set(null);
      this.error.set(this.describe(caught));
    } finally {
      this.pending.set(false);
    }
  }

  private describe(caught: unknown): string {
    const detail = (caught as { detail?: unknown })?.detail;
    if (typeof detail === 'string') return detail;
    return 'That combination could not be planned.';
  }

  /**
   * `Number('')` is 0, so an emptied box would silently read as "I have none" — the trap
   * CLAUDE.md records from the materials editor. An unparseable value keeps the last one.
   */
  protected setNumber(target: EventTarget | null, into: (value: number) => void, max?: number): void {
    const raw = (target as HTMLInputElement | null)?.value ?? '';
    if (raw.trim() === '') return;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) return;
    into(max === undefined ? Math.floor(value) : Math.min(Math.floor(value), max));
  }

  protected chooseBanner(next: 'character' | 'weapon'): void {
    this.banner.set(next);
    this.ownedCopies.set(0);
    this.pity.set(0);
    // Both pieces of banner state have to reset together: a guarantee carried from the
    // character banner would describe a weapon banner the player has never pulled on.
    this.guaranteed.set(false);
    this.lostFiftyFifties.set(0);
  }

  /**
   * Guaranteed and the loss counter are not independent. Arming the guarantee *requires*
   * losing a 50/50, so `guaranteed` with zero losses is a state the game cannot produce and
   * the service refuses. Selecting it here raises the counter rather than sending a 422.
   */
  protected setGuaranteed(next: boolean): void {
    this.guaranteed.set(next);
    if (next && this.showsRadiance() && this.lostFiftyFifties() === 0) {
      this.lostFiftyFifties.set(1);
    }
  }

  protected setLosses(next: number): void {
    this.lostFiftyFifties.set(next);
    if (next === 0) this.guaranteed.set(false);
  }

  protected toggleVersion(version: string): void {
    const next = new Set(this.selectedVersions());
    if (next.has(version)) next.delete(version);
    else next.add(version);
    this.selectedVersions.set(next);
  }

  protected isSelected(version: string): boolean {
    return this.selectedVersions().has(version);
  }

  protected tierLabel(tier: Tier): string {
    return { f2p: 'F2P', welkin: 'Welkin', welkin_bp: 'Welkin + BP' }[tier];
  }

  protected readonly tiers = TIERS;

  /** Percent for the bar behind a goal chip. */
  protected percent(chance: number): number {
    return Math.round(chance * 1000) / 10;
  }

  /** Green through red, so a row reads before any digit does. */
  protected barClass(chance: number): string {
    if (chance >= 0.9) return 'bar bar--sure';
    if (chance >= 0.6) return 'bar bar--likely';
    if (chance >= 0.25) return 'bar bar--even';
    if (chance > 0) return 'bar bar--unlikely';
    return 'bar bar--none';
  }
}
