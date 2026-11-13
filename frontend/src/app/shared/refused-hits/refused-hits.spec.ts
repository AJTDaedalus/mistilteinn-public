import { TestBed } from '@angular/core/testing';

import { RefusedHits, type RefusedHit } from './refused-hits';

const WINDSUNDER: RefusedHit = {
  talent: 'normal_attack',
  label: 'Windsunder Arrow DMG',
  spec: '{param12:F1P} Normal Attack DMG',
  reason: "a multiple of the character's Normal Attack DMG, not of a stat",
};

describe('RefusedHits', () => {
  function render(refused: RefusedHit[]) {
    TestBed.configureTestingModule({ imports: [RefusedHits] });
    const fixture = TestBed.createComponent(RefusedHits);
    fixture.componentRef.setInput('refused', refused);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('names each refused row with the parser\'s reason, visibly', () => {
    const el = render([WINDSUNDER]);

    expect(el.querySelector('.refused__label')?.textContent).toBe('Windsunder Arrow DMG');
    expect(el.querySelector('.refused__reason')?.textContent).toContain('Normal Attack DMG');
    expect(el.querySelector('[role=note]')).toBeTruthy();
  });

  it('draws nothing when nothing was refused', () => {
    expect(render([]).querySelector('.refused')).toBeNull();
  });
});
