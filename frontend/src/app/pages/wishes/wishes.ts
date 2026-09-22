import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  WishesService,
  type WishIncomeVersionRead,
  type WishLimits,
  type WishPlanRead,
  type WishTarget,
} from './wishes.service';

/** The three spending tiers the bookkeeping workbook publishes. */
const TIERS = ['f2p', 'welkin', 'welkin_bp'] as const;
type Tier = (typeof TIERS)[number];

/** How long to wait after the last keystroke before asking the backend. */
const DEBOUNCE_MS = 250;

/** Copies that take an item to its maximum. */
const MAX_COPIES = { character: 7, weapon: 5 } as const;

/** One banner's starting position, as the controls hold it. */
interface Position {
  label: string;
  pity: number;
  guaranteed: boolean;
  lostFiftyFifties: number;
  ownedCopies: number;
}

/** A row of the custom plan. */
interface CustomRow extends Position {
  banner: 'character' | 'weapon';
  targetCopies: number;
}

function position(label = ''): Position {
  return { label, pity: 0, guaranteed: false, lostFiftyFifties: 0, ownedCopies: 0 };
}

/**
 * The wish planner — odds of reaching a constellation or refinement on a given budget.
 *
 * `docs/DESIGN_wish_planner.md`. Laid out after Fribbels' Warp Planner, deliberately, so that
 * anyone who has used that one already knows this one.
 *
 * **Two modes, as Fribbels has.** *Simple* plans one character and optionally their signature
 * weapon, ordered by a strategy. *Custom* takes an explicit ordered list of goals across as
 * many characters as you like. Both spend **one** budget: the thing a per-banner ladder
 * cannot do, because two separate ladders each assume they own the whole wallet and can both
 * read "almost certain" when affording both is impossible.
 *
 * Genshin-specific additions Fribbels has no equivalent of: **Capturing Radiance**, as a
 * "50/50s lost" control, and **whole patches** of projected income rather than half-patches,
 * because the source workbook has no phase structure.
 */
@Component({
  selector: 'app-wishes',
  imports: [FormsModule, DecimalPipe, DatePipe],
  templateUrl: './wishes.html',
  styleUrl: './wishes.scss',
})
export class WishesPage {
  private service = inject(WishesService);

  protected readonly mode = signal<'simple' | 'custom'>('simple');

  // -- simple mode
  protected readonly character = signal<Position>(position('Character'));
  protected readonly weapon = signal<Position>(position('Weapon'));
  protected readonly planWeapon = signal(true);
  protected readonly strategy = signal('c0_first');

  // -- custom mode
  protected readonly rows = signal<CustomRow[]>([
    { ...position('Character'), banner: 'character', targetCopies: 1 },
  ]);

  // -- wallet
  protected readonly primogems = signal(0);
  protected readonly intertwined = signal(0);
  protected readonly refund = signal('none');
  protected readonly tier = signal<Tier>('f2p');
  protected readonly selectedVersions = signal<ReadonlySet<string>>(new Set());

  protected readonly limits = signal<WishLimits | null>(null);
  protected readonly income = signal<WishIncomeVersionRead[]>([]);
  protected readonly incomeFetchedAt = signal<string | null>(null);
  protected readonly plan = signal<WishPlanRead | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly pending = signal(false);

  protected readonly strategies = computed(() => this.limits()?.strategies ?? []);
  protected readonly refundTiers = computed(() =>
    Object.keys(this.limits()?.starglitter_refund_tiers ?? { none: 0 }),
  );

  protected readonly characterHardPity = computed(
    () => this.limits()?.banners['character']?.hard_pity ?? 90,
  );
  protected readonly weaponHardPity = computed(
    () => this.limits()?.banners['weapon']?.hard_pity ?? 80,
  );
  protected readonly maxLosses = computed(() => this.limits()?.max_lost_fifty_fifties ?? 3);

  /** True once the counter alone guarantees the next 50/50, so the page can say why. */
  protected readonly radianceIsCertain = computed(
    () => this.character().lostFiftyFifties >= this.maxLosses(),
  );

  /** Wishes from the patches ticked, at the chosen tier. */
  protected readonly projectedWishes = computed(() => {
    const chosen = this.selectedVersions();
    const tier = this.tier();
    return Math.floor(
      this.income()
        .filter((version) => chosen.has(version.version))
        .reduce((total, version) => total + version[tier], 0),
    );
  });

  /** Versions still ahead, newest first — nobody budgets for a patch that has been and gone. */
  protected readonly upcoming = computed(() => this.income().slice(-8).reverse());

  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    void this.load();
    // Debounced. Firing per keystroke would send `9`, `99`, `999` on the way to `9999` — the
    // defect CLAUDE.md records for the materials editor, one layer up.
    effect(() => {
      const request = this.request();
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => void this.recompute(request), DEBOUNCE_MS);
    });
  }

  private target(from: Position, banner: 'character' | 'weapon'): WishTarget {
    return {
      banner,
      label: from.label,
      pity: from.pity,
      guaranteed: from.guaranteed,
      // Capturing Radiance is the character banner's, and it is one account-wide counter, so
      // only the first target of a plan may carry it.
      lost_fifty_fifties: banner === 'character' ? from.lostFiftyFifties : 0,
      owned_copies: from.ownedCopies,
    };
  }

  protected request() {
    const wallet = {
      primogems: this.primogems(),
      intertwined_fate: this.intertwined(),
      extra_wishes: this.projectedWishes(),
      starglitter_refund: this.refund(),
    };

    if (this.mode() === 'custom') {
      return {
        ...wallet,
        targets: this.rows().map((row, index) => ({
          ...this.target(row, row.banner),
          // Only the first row declares the counter; the backend refuses a later one.
          lost_fifty_fifties: index === 0 ? this.target(row, row.banner).lost_fifty_fifties : 0,
          target_copies: row.targetCopies,
        })),
      };
    }

    return {
      ...wallet,
      character: this.target(this.character(), 'character'),
      weapon: this.planWeapon() ? this.target(this.weapon(), 'weapon') : null,
      strategy: this.strategy(),
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
      this.plan.set(await this.service.plan(request as never));
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
  protected parse(target: EventTarget | null, max?: number): number | null {
    const raw = (target as HTMLInputElement | null)?.value ?? '';
    if (raw.trim() === '') return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) return null;
    return max === undefined ? Math.floor(value) : Math.min(Math.floor(value), max);
  }

  protected setNumber(
    target: EventTarget | null,
    into: (value: number) => void,
    max?: number,
  ): void {
    const value = this.parse(target, max);
    if (value !== null) into(value);
  }

  /** Update one field of a simple-mode position. */
  protected patch(which: 'character' | 'weapon', change: Partial<Position>): void {
    const signal = which === 'character' ? this.character : this.weapon;
    signal.set({ ...signal(), ...change });
  }

  /**
   * Guaranteed and the loss counter are not independent. Arming the guarantee *requires*
   * losing a 50/50, so `guaranteed` with zero losses is a state the game cannot produce.
   * Selecting it here raises the counter rather than sending a 422.
   */
  protected setGuaranteed(which: 'character' | 'weapon', next: boolean): void {
    const current = which === 'character' ? this.character() : this.weapon();
    const losses =
      which === 'character' && next && current.lostFiftyFifties === 0
        ? 1
        : current.lostFiftyFifties;
    this.patch(which, { guaranteed: next, lostFiftyFifties: losses });
  }

  protected setLosses(next: number): void {
    const current = this.character();
    this.patch('character', {
      lostFiftyFifties: next,
      guaranteed: next === 0 ? false : current.guaranteed,
    });
  }

  // -- custom rows

  protected addRow(banner: 'character' | 'weapon'): void {
    const label = banner === 'character' ? 'Character' : 'Weapon';
    this.rows.set([
      ...this.rows(),
      { ...position(`${label} ${this.rows().length + 1}`), banner, targetCopies: 1 },
    ]);
  }

  protected removeRow(index: number): void {
    // Never leave the plan empty: a request with no targets is refused, and the page would
    // show an error rather than an empty state.
    if (this.rows().length === 1) return;
    this.rows.set(this.rows().filter((_, i) => i !== index));
  }

  protected moveRow(index: number, by: -1 | 1): void {
    const next = [...this.rows()];
    const to = index + by;
    if (to < 0 || to >= next.length) return;
    [next[index], next[to]] = [next[to], next[index]];
    this.rows.set(next);
  }

  protected patchRow(index: number, change: Partial<CustomRow>): void {
    const next = [...this.rows()];
    next[index] = { ...next[index], ...change };
    // Changing the banner can leave a goal above the new banner's cap.
    const cap = MAX_COPIES[next[index].banner];
    next[index].targetCopies = Math.min(next[index].targetCopies, cap);
    next[index].ownedCopies = Math.min(next[index].ownedCopies, cap - 1);
    if (next[index].targetCopies <= next[index].ownedCopies) {
      next[index].targetCopies = next[index].ownedCopies + 1;
    }
    this.rows.set(next);
  }

  protected copyOptions(banner: 'character' | 'weapon'): number[] {
    return Array.from({ length: MAX_COPIES[banner] }, (_, i) => i + 1);
  }

  protected ownedOptions(banner: 'character' | 'weapon'): number[] {
    return Array.from({ length: MAX_COPIES[banner] }, (_, i) => i);
  }

  /** "C3" for the fourth copy of a character, "R2" for the second of a weapon. */
  protected rung(banner: 'character' | 'weapon', copies: number): string {
    return banner === 'character' ? `C${copies - 1}` : `R${copies}`;
  }

  /**
   * What *holding* `copies` is called — which is not the same as the rung `copies` reaches.
   *
   * Holding none is "None", not "C0": a character you have never pulled is not a C0
   * character. Getting this wrong made a fresh row read "from C0 to C0", which is both
   * self-contradictory and a goal the backend refuses.
   */
  protected ownedLabel(banner: 'character' | 'weapon', copies: number): string {
    return copies === 0 ? 'None' : this.rung(banner, copies);
  }

  // -- income

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

  protected strategyLabel(value: string): string {
    return value === 'r1_first' ? 'R1 first' : `${value.slice(0, 2).toUpperCase()} first`;
  }

  protected refundLabel(tier: string): string {
    const percent = (this.limits()?.starglitter_refund_tiers[tier] ?? 0) * 100;
    if (tier === 'none') return 'None';
    const shape = { low: 'Low', average: 'Average', high: 'High' }[tier] ?? tier;
    return `${percent.toFixed(1)}% (${shape})`;
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
