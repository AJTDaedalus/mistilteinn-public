import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { ElementChip } from './element';

function render(element: string | null, fallback?: string) {
  TestBed.configureTestingModule({ imports: [ElementChip] });
  const fixture = TestBed.createComponent(ElementChip);
  fixture.componentRef.setInput('element', element);
  if (fallback !== undefined) fixture.componentRef.setInput('fallback', fallback);
  fixture.detectChanges();
  return fixture.nativeElement.querySelector('.chip') as HTMLElement;
}

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
