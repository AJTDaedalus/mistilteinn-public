import { ChangeDetectionStrategy, Component, ElementRef, booleanAttribute, computed, input, output, signal, viewChild } from '@angular/core';

import { CatalogueIcon } from '../icon/icon';

/** One choice in the grid. */
export interface CardOption {
  /** Stable identifier, emitted on change. */
  value: string;
  /** Primary label, and what the search matches. */
  label: string;
  /** Catalogue basename for the card's art. Absent art leaves the label where it is. */
  icon?: string | null;
  /**
   * Several pieces of art instead of one, drawn as a row.
   *
   * A team is the case this exists for: its identity is the four characters in it, and picking
   * one of them to stand for the whole thing is a card that lies about what it is. Takes
   * precedence over `icon` when present and non-empty.
   */
  icons?: readonly (string | null | undefined)[];
  /** Secondary line — a weapon's rarity, a build's constellation. Also searched. */
  detail?: string;
  /**
   * Which filter chips this option answers to, as `{ group: value }`.
   *
   * Within a group the chips are alternatives (OR); across groups they narrow (AND). That is
   * the behaviour a user expects from "Pyro" and "Sword" pressed together, and the opposite —
   * widening as you add a filter — is the thing that makes a filter bar feel broken.
   */
  tags?: Readonly<Record<string, string>>;
  /** Shown on hover. For a set's bonus text, which is too long for a card. */
  tooltip?: string;
  /**
   * Draw this card as recommended, and sort it above the rest.
   *
   * **Only ever set from a cited source.** Owner, 2026-09-02: *"We should have both sets and
   * weapons 'tiered' with recommended sets/weapons first and highlighted somehow."* The
   * recommendation comes from KeqingMains and carries their sentence in `tooltip`; a "tier"
   * this app derived itself and labelled recommended would be a citation-shaped thing with no
   * citation, which `CLAUDE.md` names as fairy's worst failure.
   *
   * A character with no captured guide has no recommended cards and **no heading either** —
   * see `optimize`'s weapon options.
   */
  recommended?: boolean;
  /**
   * A stat this card's set grants at two pieces, as a `--stat-*` suffix.
   *
   * Owner, 2026-09-02: *"color coding that identifies the stat (red for attack, blue for hp,
   * yellow for defense, silver for dmg%)"*, then *"ER can be green, give other random weird
   * 2P sets another color"*.
   *
   * **Never the only signal.** The card's `detail` line names the stat in words, because a
   * palette that encodes meaning in hue alone is unreadable to a colour-blind user and
   * invisible in a screenshot pasted into chat.
   */
  statColour?: string;
}

/** One row of chips in the pop-up. */
export interface CardFilter {
  /** Matched against `CardOption.tags[group]`. */
  group: string;
  label: string;
  options: readonly { value: string; label: string; icon?: string | null }[];
}

/**
 * A pop-up grid of picture cards, with search and filters.
 *
 * **Built once because the owner asked for it four times.** Their audit says it of the
 * inventory's set filter, the build character picker, the build weapon picker and the optimize
 * set filter: *"Drop-downs for filters should be pop-up square icon grids with cards for things
 * with images. This applies everywhere."* Fairy has three near-identical pickers —
 * `set-picker`, `agent-picker`, `wengine-picker` — and copying that shape three more times here
 * is how the fourth one ends up subtly different.
 *
 * `shared/combobox` stays: it is a *list* with art beside a label, which is right for a control
 * inside a row. This is for choosing from a wall of things you recognise by sight.
 *
 * ## Art is never the only label
 *
 * Every card carries its name. A grid of pictures is faster for someone who knows the icons and
 * useless to everyone else, which is the argument `ElementChip` and `WeaponMark` both make, and
 * the accessibility bug `ng lint` caught on #131.
 */
@Component({
  selector: 'mist-card-picker',
  imports: [CatalogueIcon],
  templateUrl: './card-picker.html',
  styleUrl: './card-picker.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CardPicker {
  readonly options = input<readonly CardOption[]>([]);
  readonly selected = input<readonly string[]>([]);
  readonly filters = input<readonly CardFilter[]>([]);
  /** The control's own name — "Set", "Character". Always rendered, never a placeholder alone. */
  readonly label = input('');
  /** Shown on the trigger when nothing is chosen. */
  readonly placeholder = input('Choose…');
  /** Several at once. Single-select closes the dialog on pick, which is what one choice means. */
  readonly multi = input(false, { transform: booleanAttribute });
  readonly disabled = input(false, { transform: booleanAttribute });
  /**
   * Offer "Clear" in single-select too.
   *
   * Multi-select always has it, because a set of chosen things needs a way back to none. A
   * *single* choice usually does not — you replace it by picking another. A build's weapon is
   * the exception the flag exists for: `weapon_id` is nullable by design (OQ-T3), a build
   * being assembled without one is a real state, and the old `<select>` said so with a "None
   * yet" option. A picker that can only ever add a weapon would quietly remove that state.
   */
  readonly clearable = input(false, { transform: booleanAttribute });
  /**
   * Keep the caller's order instead of sorting by name.
   *
   * **One lowercase word on purpose.** HTML lowercases static attributes, so an input named
   * `preserveOrder` would silently never match `<mist-card-picker preserveOrder>` — the flag
   * reads as set and is not. `multi`, `clearable` and `chip` escape that only by being single
   * words.
   *
   * Alphabetical is right when the options have no order of their own — sixty artifact sets,
   * a hundred and fifty characters. It is **wrong** when the caller's order is the
   * information: the build weapon picker lists KeqingMains' recommendations first, in KQM's
   * order, and sorting that alphabetically discards the whole point.
   *
   * Found by looking: the page's own options were ordered correctly and the picker re-sorted
   * them, so a unit test asserting the page was right while the screen was wrong.
   */
  readonly ordered = input(false, { transform: booleanAttribute });

  readonly selectedChange = output<string[]>();

  protected readonly dialog = viewChild<ElementRef<HTMLDialogElement>>('dialog');
  protected readonly search = signal('');
  /** Active chips, as `{ group: Set<value> }`. */
  protected readonly active = signal<Record<string, ReadonlySet<string>>>({});

  protected readonly chosen = computed(() => {
    const picked = new Set(this.selected());
    return this.options().filter((option) => picked.has(option.value));
  });

  /**
   * What the grid draws: filtered, searched, and **selected first**.
   *
   * Selected-first because a picker's other job is showing what you already chose — scrolling a
   * wall of sixty sets to find the two that are ticked is the failure this replaces.
   */
  protected readonly visible = computed(() => {
    const query = this.search().trim().toLowerCase();
    const active = this.active();
    const picked = new Set(this.selected());

    const kept = this.options().filter((option) => {
      for (const [group, values] of Object.entries(active)) {
        if (!values.size) continue;
        if (!values.has(option.tags?.[group] ?? '')) return false;
      }
      if (!query) return true;
      return `${option.label} ${option.detail ?? ''}`.toLowerCase().includes(query);
    });

    // Selected-first stays either way: a picker's other job is showing what you already
    // chose, and scrolling a wall of sixty to find the two ticked is the failure this
    // replaces. Only the tiebreak changes.
    const keepOrder = this.ordered();
    return kept
      .map((option, index) => ({ option, index }))
      .sort((a, b) => {
        const byPicked =
          Number(picked.has(b.option.value)) - Number(picked.has(a.option.value));
        if (byPicked !== 0) return byPicked;
        return keepOrder
          ? a.index - b.index
          : a.option.label.localeCompare(b.option.label);
      })
      .map(({ option }) => option);
  });

  /**
   * Does this picker hold few enough options to be drawn small?
   *
   * Counted on the **whole** option list rather than the filtered view, so the panel does not
   * resize under the reader as they type — a dialog that jumps between two widths mid-search
   * is worse than one that is too wide.
   *
   * Eight is one full row of cards at the grid's own `minmax(7.5rem, …)`, so the threshold is
   * "everything fits on one row anyway" rather than a number chosen for its own sake.
   */
  protected readonly isSmall = computed(
    () => this.options().length <= 8 && !this.filters().length,
  );

  protected isSelected(value: string): boolean {
    return this.selected().includes(value);
  }

  protected isActive(group: string, value: string): boolean {
    return this.active()[group]?.has(value) ?? false;
  }

  protected toggleFilter(group: string, value: string): void {
    this.active.update((current) => {
      const next = new Set(current[group] ?? []);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return { ...current, [group]: next };
    });
  }

  protected pick(value: string): void {
    if (!this.multi()) {
      this.selectedChange.emit([value]);
      this.close();
      return;
    }
    const picked = new Set(this.selected());
    if (picked.has(value)) picked.delete(value);
    else picked.add(value);
    this.selectedChange.emit([...picked]);
  }

  protected clear(): void {
    this.selectedChange.emit([]);
  }

  protected open(): void {
    if (this.disabled()) return;
    // Reset the search but **not** the filters: a user who narrowed to Pyro and reopened to
    // pick a second Pyro character should not have to narrow again.
    this.search.set('');
    this.dialog()?.nativeElement.showModal?.();
  }

  protected close(): void {
    // **Optional call, deliberately.** `HTMLDialogElement` is absent in jsdom, so `close()` is
    // undefined there and a bare call is a `TypeError` — thrown from inside a click handler,
    // which takes the page out rather than failing the one control. Found by a test, which is
    // the environment without it; the same is true of any browser that lacks `<dialog>`.
    this.dialog()?.nativeElement.close?.();
  }
}
