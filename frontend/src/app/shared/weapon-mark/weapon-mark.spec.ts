import { ComponentFixture, TestBed } from '@angular/core/testing';

import { WeaponMark } from './weapon-mark';

/**
 * The mark is a picture of a weapon class, so the thing worth testing is that it never
 * becomes *only* a picture. A glyph with no accessible name is a label for the person who
 * already knows it — the failure `ng lint` caught on #131, and the one `ElementChip` argues
 * against at length.
 */
describe('WeaponMark', () => {
  let fixture: ComponentFixture<WeaponMark>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [WeaponMark] }).compileComponents();
    fixture = TestBed.createComponent(WeaponMark);
  });

  function render(inputs: Record<string, unknown>) {
    for (const [key, value] of Object.entries(inputs)) fixture.componentRef.setInput(key, value);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('shows the glyph beside the word by default', () => {
    const el = render({ icon: 'Skill_A_01', label: 'Sword' });

    expect(el.querySelector('catalogue-icon')).toBeTruthy();
    expect(el.textContent).toContain('Sword');
  });

  it('keeps the word for assistive tech when it is compact', () => {
    const el = render({ icon: 'Skill_A_01', label: 'Sword', compact: true });

    expect(el.querySelector('.sr-only')?.textContent).toBe('Sword');
    expect(el.querySelector('.mark')?.getAttribute('title')).toBe('Sword');
  });

  it('renders the word alone for a class with no mark', () => {
    // The crossbow class has none at nanoka 7.0.51 — two unreleased Traveler variants with
    // no talents seeded, so there is nothing to derive. A gap would read as a broken image.
    const el = render({ icon: null, label: 'Crossbow' });

    expect(el.querySelector('catalogue-icon')).toBeNull();
    expect(el.textContent).toContain('Crossbow');
  });
});
