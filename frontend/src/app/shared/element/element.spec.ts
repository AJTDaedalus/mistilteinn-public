import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { ElementChip } from './element';

function render(
  element: string | null,
  fallback?: string,
  over: { icon?: string | null; compact?: boolean; size?: number } = {},
) {
  TestBed.configureTestingModule({ imports: [ElementChip] });
  const fixture = TestBed.createComponent(ElementChip);
  fixture.componentRef.setInput('element', element);
  if (fallback !== undefined) fixture.componentRef.setInput('fallback', fallback);
  for (const [key, value] of Object.entries(over)) {
    fixture.componentRef.setInput(key, value);
  }
  fixture.detectChanges();
  return fixture.nativeElement.querySelector('.chip') as HTMLElement;
}

describe('ElementChip in compact mode', () => {
  /**
   * **The mode the whole app now uses** (owner, 2026-08-31): *"change the 'Hydro' etc element
   * names on builds and characters to the icons… that's across the app"*. It had no coverage
   * at all while it was an opt-in nobody took.
   */
  it('shows the emblem instead of the word, keeping the word for assistive tech', () => {
    const chip = render('Hydro', undefined, { icon: 'Hydro', compact: true });

    expect(chip.querySelector('catalogue-icon')).not.toBeNull();
    // Not gone — moved. Find-in-page and a screen reader both still get "Hydro", which is
    // what the "colour is never the only channel" rule actually requires.
    expect(chip.querySelector('.sr-only')?.textContent?.trim()).toBe('Hydro');
    expect(chip.getAttribute('title')).toBe('Hydro');
  });

  it('falls back to the word when no emblem was vendored', () => {
    // The failure this guards: compact with no icon would otherwise render a chip with no
    // visible label at all.
    const chip = render('Hydro', undefined, { icon: null, compact: true });

    expect(chip.textContent?.trim()).toBe('Hydro');
    expect(chip.querySelector('.sr-only')).toBeNull();
  });

  it('draws the emblem at the size the caller asked for', () => {
    // "Make sure they're big enough to see clearly" — the size is a caller's decision, and a
    // chip that ignored it would silently keep the 16px default everywhere.
    const chip = render('Pyro', undefined, { icon: 'Pyro', compact: true, size: 22 });
    const img = chip.querySelector('catalogue-icon img') as HTMLImageElement | null;

    expect(img?.getAttribute('width')).toBe('22');
  });

  it('still colours an unknown element rather than dropping it', () => {
    const chip = render('None', undefined, { icon: null, compact: true });

    expect(chip.textContent?.trim()).toBe('No vision');
    expect(chip.style.getPropertyValue('--element')).toBe('var(--element-none)');
  });
});

describe('ElementChip', () => {
  it('names the element as well as colouring it', () => {
    // Colour is a second channel, never the only one. A chip carrying the hue alone is
    // invisible to a colourblind reader and to find-in-page.
    const chip = render('Electro');

    expect(chip.textContent?.trim()).toBe('Electro');
    expect(chip.style.getPropertyValue('--element')).toBe('var(--element-electro)');
  });

  it('matches the token regardless of how the catalogue cased it', () => {
    expect(render('PYRO').style.getPropertyValue('--element')).toBe('var(--element-pyro)');
  });

  it('falls back rather than colouring an element it does not know', () => {
    // Two catalogue rows carry the literal `"None"` — the Traveler before a vision is
    // chosen. A `var(--element-none)` lookup for that spelling would resolve to nothing and
    // the chip would inherit whatever colour it sat on.
    const chip = render('None');

    expect(chip.textContent?.trim()).toBe('No vision');
    expect(chip.style.getPropertyValue('--element')).toBe('var(--element-none)');
  });

  it('treats a null element the same as an unknown one', () => {
    expect(render(null).textContent?.trim()).toBe('No vision');
  });

  it('lets the caller reword the fallback', () => {
    // "No vision" is right for a character and wrong for a hit, which has no vision to lack.
    expect(render(null, 'Physical').textContent?.trim()).toBe('Physical');
  });

  it('never renders Physical as one of the seven', () => {
    // Physical is a damage type, not a vision — `models/enums.py:Element` refuses it by name
    // and so does the palette. A `--element-physical` token would be the ZZZ-shaped
    // equivalence the domain model exists to prevent.
    expect(render('Physical').style.getPropertyValue('--element')).toBe(
      'var(--element-none)',
    );
  });
});
