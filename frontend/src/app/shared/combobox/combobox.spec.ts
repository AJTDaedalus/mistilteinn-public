import { TestBed } from '@angular/core/testing';
import { ComponentRef } from '@angular/core';
import { describe, expect, it } from 'vitest';

import { Combobox, ComboboxOption } from './combobox';

const OPTIONS: ComboboxOption[] = [
  { value: 'a1', label: 'Anby Demara', detail: 'electric · stun' },
  { value: 'a2', label: 'Burnice', detail: 'fire · anomaly' },
  { value: 'a3', label: 'Caesar King', detail: 'physical · defense' },
  { value: 'a4', label: 'Ellen Joe', detail: 'ice · attack' },
];

const GROUPED: ComboboxOption[] = [
  { value: 'w1', label: 'Steel Cushion', group: 'Matches attack' },
  { value: 'w2', label: 'Lunar Decoration', group: 'Matches attack' },
  { value: 'w3', label: 'Tusks of Fury', group: 'Other specialties' },
];

function setup(opts: ComboboxOption[] = OPTIONS, value: string | null = null) {
  TestBed.configureTestingModule({ imports: [Combobox] });
  const f = TestBed.createComponent(Combobox);
  const ref = f.componentRef as ComponentRef<Combobox>;
  ref.setInput('options', opts);
  ref.setInput('value', value);
  ref.setInput('placeholder', 'Pick one');
  return f;
}

async function settle(f: ReturnType<typeof TestBed.createComponent>) {
  f.detectChanges();
  for (let i = 0; i < 3; i++) await Promise.resolve();
  f.detectChanges();
}

describe('Combobox', () => {
  it('renders the selected option label when a value is set', async () => {
    const f = setup(OPTIONS, 'a3');
    await settle(f);
    const input = f.nativeElement.querySelector('input') as HTMLInputElement;
    expect(input.value).toBe('Caesar King');
  });

  it('shows the placeholder when no value is selected', async () => {
    const f = setup(OPTIONS, null);
    await settle(f);
    const input = f.nativeElement.querySelector('input') as HTMLInputElement;
    expect(input.value).toBe('');
    expect(input.placeholder).toBe('Pick one');
  });

  it('filters options by case-insensitive substring match on label or detail', async () => {
    const f = setup();
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void };
      query: { set: (v: string) => void };
      filtered: () => ComboboxOption[];
    };
    cmp.open.set(true);
    cmp.query.set('cae');
    expect(cmp.filtered().map((o) => o.label)).toEqual(['Caesar King']);

    cmp.query.set('STUN'); // matches detail "electric · stun"
    expect(cmp.filtered().map((o) => o.label)).toEqual(['Anby Demara']);

    cmp.query.set('');
    expect(cmp.filtered()).toHaveLength(4);
  });

  it('selecting an option emits valueChange and closes', async () => {
    const f = setup();
    const events: (string | null)[] = [];
    f.componentInstance.valueChange.subscribe((v) => events.push(v));
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void; (): boolean };
      pick: (o: ComboboxOption) => void;
    };
    cmp.open.set(true);
    cmp.pick(OPTIONS[1]);
    expect(events).toEqual(['a2']);
    expect(cmp.open()).toBe(false);
  });

  it('arrow down + enter navigates and selects the highlighted option', async () => {
    const f = setup();
    const events: (string | null)[] = [];
    f.componentInstance.valueChange.subscribe((v) => events.push(v));
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void };
      onKeydown: (e: KeyboardEvent) => void;
    };
    // Highlight starts at index 0 when open, so two ArrowDowns lands on
    // index 2 (a3). This matches GitHub-style combobox behaviour where
    // the first option is pre-highlighted on open.
    cmp.open.set(true);
    cmp.onKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    cmp.onKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    cmp.onKeydown(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(events).toEqual(['a3']);
  });

  it('escape closes without emitting', async () => {
    const f = setup();
    const events: (string | null)[] = [];
    f.componentInstance.valueChange.subscribe((v) => events.push(v));
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void; (): boolean };
      onKeydown: (e: KeyboardEvent) => void;
    };
    cmp.open.set(true);
    cmp.onKeydown(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(cmp.open()).toBe(false);
    expect(events).toEqual([]);
  });

  it('groups options by their `group` field when present', async () => {
    const f = setup(GROUPED);
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void };
      groups: () => { label: string; items: ComboboxOption[] }[];
    };
    cmp.open.set(true);
    const grouped = cmp.groups();
    expect(grouped).toHaveLength(2);
    expect(grouped[0].label).toBe('Matches attack');
    expect(grouped[0].items).toHaveLength(2);
    expect(grouped[1].label).toBe('Other specialties');
  });

  it('groups returns a single empty-label bucket when no option has a group', async () => {
    const f = setup(OPTIONS);
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void };
      groups: () => { label: string; items: ComboboxOption[] }[];
    };
    cmp.open.set(true);
    const grouped = cmp.groups();
    expect(grouped).toHaveLength(1);
    expect(grouped[0].label).toBe('');
    expect(grouped[0].items).toHaveLength(4);
  });

  it('emits null when the user clears the input and presses Enter', async () => {
    const f = setup(OPTIONS, 'a1');
    const events: (string | null)[] = [];
    f.componentInstance.valueChange.subscribe((v) => events.push(v));
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void };
      query: { set: (v: string) => void };
      clear: () => void;
    };
    cmp.open.set(true);
    cmp.query.set('');
    cmp.clear();
    expect(events).toEqual([null]);
  });
  // ── The ARIA contract ──────────────────────────────────────────────────────
  //
  // Pinned because none of it is visible on screen: the component rendered and behaved
  // correctly for months while announcing itself to a screen reader as an unlabelled text
  // box, and `ng lint` only noticed once a caller tried to wrap it in a `<label>` — which
  // associates with nothing across a component boundary.

  it('carries the accessible name it was given', async () => {
    const f = setup();
    (f.componentRef as ComponentRef<Combobox>).setInput('ariaLabel', 'Add a candidate weapon');
    await settle(f);
    const input = f.nativeElement.querySelector('input') as HTMLInputElement;

    expect(input.getAttribute('aria-label')).toBe('Add a candidate weapon');
    expect(input.getAttribute('role')).toBe('combobox');
  });

  it('omits aria-label rather than setting it empty when unnamed', async () => {
    // An empty `aria-label` is worse than none: it overrides whatever the browser would
    // otherwise infer and announces nothing at all.
    const f = setup();
    await settle(f);

    expect(f.nativeElement.querySelector('input').hasAttribute('aria-label')).toBe(false);
  });

  it('points aria-controls at its own listbox', async () => {
    const f = setup();
    const cmp = f.componentInstance as unknown as { open: { set: (v: boolean) => void } };
    cmp.open.set(true);
    await settle(f);

    const input = f.nativeElement.querySelector('input') as HTMLInputElement;
    const list = f.nativeElement.querySelector('[role="listbox"]') as HTMLElement;

    expect(list).toBeTruthy();
    expect(input.getAttribute('aria-controls')).toBe(list.id);
    expect(input.getAttribute('aria-expanded')).toBe('true');
  });

  it('gives two instances on one page distinct listbox ids', async () => {
    // A shared id would have both inputs' `aria-controls` resolve to whichever list the
    // document happened to contain first. The second fixture is built from the *same*
    // TestBed — `setup()` reconfigures it, which an already-instantiated bed refuses.
    const a = setup();
    const b = TestBed.createComponent(Combobox);
    (b.componentRef as ComponentRef<Combobox>).setInput('options', OPTIONS);
    const openIt = (f: typeof a) =>
      (f.componentInstance as unknown as { open: { set: (v: boolean) => void } }).open.set(true);
    openIt(a);
    openIt(b as typeof a);
    await settle(a);
    await settle(b);

    const idA = a.nativeElement.querySelector('[role="listbox"]').id;
    const idB = b.nativeElement.querySelector('[role="listbox"]').id;
    expect(idA).toBeTruthy();
    expect(idA).not.toBe(idB);
  });

  it('tracks the highlighted option with aria-activedescendant', async () => {
    const f = setup();
    const cmp = f.componentInstance as unknown as {
      open: { set: (v: boolean) => void };
      highlight: { set: (v: number) => void };
    };
    cmp.open.set(true);
    cmp.highlight.set(2);
    await settle(f);

    const input = f.nativeElement.querySelector('input') as HTMLInputElement;
    const options = f.nativeElement.querySelectorAll('[role="option"]');

    expect(options).toHaveLength(4);
    expect(input.getAttribute('aria-activedescendant')).toBe(options[2].id);
    expect(options[2].getAttribute('aria-selected')).toBe('true');
    expect(options[0].getAttribute('aria-selected')).toBe('false');
  });

  it('drops aria-activedescendant while closed', async () => {
    // It would otherwise name an element that is not in the document.
    const f = setup();
    await settle(f);

    expect(
      f.nativeElement.querySelector('input').hasAttribute('aria-activedescendant'),
    ).toBe(false);
  });

  it('keeps group headers out of the option list', async () => {
    // A header announced as a selectable option is a row the user can arrow onto and not
    // choose. `role="presentation"` leaves it as the visual divider it is.
    const f = setup(GROUPED);
    (f.componentInstance as unknown as { open: { set: (v: boolean) => void } }).open.set(true);
    await settle(f);

    expect(f.nativeElement.querySelectorAll('[role="option"]')).toHaveLength(3);
    expect(f.nativeElement.querySelectorAll('.cb__group[role="presentation"]')).toHaveLength(2);
  });
});
