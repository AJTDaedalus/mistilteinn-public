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

export interface ComboboxOption {
  /** Stable identifier emitted via valueChange. */
  value: string;
  /** Primary visible label, also used for filtering. */
  label: string;
  /** Optional secondary text rendered after the label and included in filter. */
  detail?: string;
  /** Optional group bucket label (used to render <optgroup>-style sections). */
  group?: string;
  /** Disable the option without removing it from the list. */
  disabled?: boolean;
}

interface OptionGroup {
  label: string;
  items: ComboboxOption[];
}

@Component({
  selector: 'mist-combobox',
  imports: [],
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

  valueChange = output<string | null>();

  protected open = signal(false);
  protected query = signal('');
  protected highlight = signal(0);

  // ---- derived state ----------------------------------------------------

  protected selectedLabel = computed<string>(() => {
    const opts = this.options();
    const v = this.value();
    return opts.find((o) => o.value === v)?.label ?? '';
  });

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
