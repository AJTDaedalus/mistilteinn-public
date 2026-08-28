import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { CatalogueIcon } from '../icon/icon';

export interface ComboboxOption {
  /** Stable identifier emitted via valueChange. */
  value: string;
  /** Primary visible label, also used for filtering. */
  label: string;
  /**
   * Catalogue basename for the option's art — `UI_EquipIcon_Sword_Blunt`.
   *
   * Optional, and deliberately not part of the filter: a user types a weapon's name, never
   * its icon's. Absent or unloadable art leaves the label where it was.
   */
  icon?: string | null;
  /** Optional secondary text rendered after the label and included in filter. */
  detail?: string;
  /** Optional group bucket label (used to render <optgroup>-style sections). */
  group?: string;
  /** Disable the option without removing it from the list. */
  disabled?: boolean;
}

/**
 * Per-instance id counter, so `aria-controls` and `aria-activedescendant` can point at this
 * combobox's own listbox. Two on one page would otherwise both claim the same element.
 */
let nextId = 0;

interface OptionGroup {
  label: string;
  items: ComboboxOption[];
}

@Component({
  selector: 'mist-combobox',
  imports: [CatalogueIcon],
  templateUrl: './combobox.html',
  styleUrl: './combobox.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Combobox {
  private host = inject(ElementRef<HTMLElement>);

  options = input<ComboboxOption[]>([]);
  value = input<string | null>(null);
  placeholder = input<string>('');
  disabled = input<boolean>(false);

  /**
   * The accessible name for the field.
   *
   * Required in practice, and it did not exist before: the inner `<input>` had no name at
   * all, so a screen reader announced an unlabelled text box. A caller cannot supply one
   * from outside either — wrapping the component in a `<label>` associates it with nothing,
   * which is what `label-has-associated-control` was reporting.
   */
  ariaLabel = input<string>('');

  valueChange = output<string | null>();

  protected open = signal(false);
  protected query = signal('');
  protected highlight = signal(0);

  /** Stable for this instance's lifetime — the listbox and its options hang off it. */
  protected readonly id = `mist-combobox-${nextId++}`;
  protected readonly listId = `${this.id}-list`;

  protected optionId(option: ComboboxOption): string {
    return `${this.id}-opt-${option.value}`;
  }

  /**
   * The option the arrow keys are on, for `aria-activedescendant`.
   *
   * Null while closed: pointing at an element that is not rendered would announce a
   * selection the user cannot see.
   */
  protected readonly activeId = computed<string | null>(() => {
    if (!this.open()) return null;
    const option = this.flat()[this.highlight()];
    return option ? this.optionId(option) : null;
  });

  // ---- derived state ----------------------------------------------------

  protected selected = computed<ComboboxOption | null>(() => {
    const v = this.value();
    return this.options().find((o) => o.value === v) ?? null;
  });

  protected selectedLabel = computed<string>(() => this.selected()?.label ?? '');

  /**
   * The chosen option's art, shown to the left of the field.
   *
   * Only while closed. An `<input>` cannot contain an `<img>`, so this sits beside it — and
   * leaving it up while the user is typing a *different* name would label the field with
   * the thing they are replacing.
   */
  protected selectedIcon = computed<string | null>(() =>
    this.open() ? null : (this.selected()?.icon ?? null),
  );

  /** Visible-input value: shows the selected label when closed, the
   *  user's query when open. */
  protected displayValue = computed<string>(() =>
    this.open() ? this.query() : this.selectedLabel(),
  );

  protected filtered = computed<ComboboxOption[]>(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return this.options();
    return this.options().filter((o) => {
      const hay = (o.label + ' ' + (o.detail ?? '')).toLowerCase();
      return hay.includes(q);
    });
  });

  protected groups = computed<OptionGroup[]>(() => {
    const items = this.filtered();
    const buckets = new Map<string, ComboboxOption[]>();
    for (const o of items) {
      const k = o.group ?? '';
      const arr = buckets.get(k) ?? [];
      arr.push(o);
      buckets.set(k, arr);
    }
    return Array.from(buckets.entries()).map(([label, items]) => ({
      label, items,
    }));
  });

  /** Flat list of currently-visible non-disabled options — drives
   *  arrow-key highlighting (group headers don't get focus). */
  protected flat = computed<ComboboxOption[]>(() =>
    this.filtered().filter((o) => !o.disabled),
  );

  constructor() {
    // Keep the highlight cursor in range as the filter mutates the list.
    effect(() => {
      const len = this.flat().length;
      if (this.highlight() >= len) this.highlight.set(0);
    });
  }

  // ---- input handlers ---------------------------------------------------

  protected onFocus() {
    if (this.disabled()) return;
    this.open.set(true);
    this.query.set('');
    this.highlight.set(0);
  }

  protected onInput(event: Event) {
    if (this.disabled()) return;
    this.open.set(true);
    this.query.set((event.target as HTMLInputElement).value);
    this.highlight.set(0);
  }

  protected onKeydown(event: KeyboardEvent) {
    if (this.disabled()) return;
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (!this.open()) {
          this.open.set(true);
          this.query.set('');
          return;
        }
        this.highlight.set(
          Math.min(this.highlight() + 1, Math.max(0, this.flat().length - 1)),
        );
        return;
      case 'ArrowUp':
        event.preventDefault();
        this.highlight.set(Math.max(0, this.highlight() - 1));
        return;
      case 'Enter':
        event.preventDefault();
        if (!this.open()) return;
        if (this.flat().length === 0 && this.query() === '') {
          // User cleared the field — treat Enter as "deselect".
          this.clear();
          return;
        }
        if (this.flat().length > 0) {
          this.pick(this.flat()[this.highlight()]);
        }
        return;
      case 'Escape':
        event.preventDefault();
        this.close();
        return;
      default:
        return;
    }
  }

  protected pick(option: ComboboxOption) {
    if (option.disabled) return;
    this.valueChange.emit(option.value);
    this.close();
  }

  protected clear() {
    this.valueChange.emit(null);
    this.close();
  }

  protected close() {
    this.open.set(false);
    this.query.set('');
  }

  protected isHighlighted(option: ComboboxOption): boolean {
    const flat = this.flat();
    const idx = flat.indexOf(option);
    return idx === this.highlight();
  }

  protected setHighlight(option: ComboboxOption) {
    const idx = this.flat().indexOf(option);
    if (idx >= 0) this.highlight.set(idx);
  }

  /** Click-outside handler — closes the dropdown when interaction lands
   *  outside this component's host element. */
  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent) {
    if (!this.open()) return;
    const target = event.target as Node;
    const root = this.host.nativeElement as HTMLElement;
    if (!root.contains(target)) this.close();
  }
}
