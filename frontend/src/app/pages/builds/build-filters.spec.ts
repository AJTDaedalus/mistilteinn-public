import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { describe, expect, it } from 'vitest';

import {
  BuildFilters,
  defaultBuildFilters,
  type BuildFilterState,
} from './build-filters';

async function render() {
  const emitted: BuildFilterState[] = [];

  @Component({
    template: `<build-filters (filtersChange)="onFilters($event)" />`,
    imports: [BuildFilters],
    standalone: true,
  })
  class Host {
    onFilters(f: BuildFilterState) { emitted.push(f); }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  return { fixture, emitted };
}

describe('BuildFilters', () => {
  describe('defaultBuildFilters', () => {
    it('returns empty text, elements, and specialties', () => {
      const f = defaultBuildFilters();
      expect(f.text).toBe('');
      expect(f.elements).toHaveLength(0);
      expect(f.specialties).toHaveLength(0);
    });
  });

  describe('text facet', () => {
    it('emits text when search input changes', async () => {
      const { fixture, emitted } = await render();
      const input: HTMLInputElement = fixture.nativeElement.querySelector('.search-input');
      input.value = 'Zhu';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(emitted.at(-1)?.text).toBe('Zhu');
    });
  });

  describe('element facet', () => {
    it('emits selected element on chip click', async () => {
      const { fixture, emitted } = await render();
      const chips: NodeListOf<HTMLButtonElement> = fixture.nativeElement.querySelectorAll('.chip--icon');
      chips[0].click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.elements).toHaveLength(1);
    });

    it('deselects element on second click', async () => {
      const { fixture, emitted } = await render();
      const chip: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.chip--icon')[0];
      chip.click();
      fixture.detectChanges();
      chip.click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.elements).toHaveLength(0);
    });

    it('allows multiple elements selected simultaneously', async () => {
      const { fixture, emitted } = await render();
      const chips: NodeListOf<HTMLButtonElement> = fixture.nativeElement.querySelectorAll('.chip--icon');
      chips[0].click();
      fixture.detectChanges();
      chips[1].click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.elements).toHaveLength(2);
    });
  });

  describe('specialty facet', () => {
    it('emits selected specialty on chip click', async () => {
      const { fixture, emitted } = await render();
      // Specialty chips come after the 5 element chips
      const chips: NodeListOf<HTMLButtonElement> = fixture.nativeElement.querySelectorAll('.chip--icon');
      chips[5].click(); // first specialty chip (index 5, after 5 elements)
      fixture.detectChanges();
      expect(emitted.at(-1)?.specialties).toHaveLength(1);
    });
  });

  describe('reset', () => {
    it('reset button is hidden when no filters active', async () => {
      const { fixture } = await render();
      const resetBtn = fixture.nativeElement.querySelector('.reset-btn');
      expect(resetBtn).toBeFalsy();
    });

    it('reset button appears after selecting a filter', async () => {
      const { fixture } = await render();
      const chip: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.chip--icon')[0];
      chip.click();
      fixture.detectChanges();
      const resetBtn = fixture.nativeElement.querySelector('.reset-btn');
      expect(resetBtn).toBeTruthy();
    });

    it('reset clears all facets and emits defaults', async () => {
      const { fixture, emitted } = await render();
      const chip: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.chip--icon')[0];
      chip.click();
      fixture.detectChanges();
      const resetBtn: HTMLButtonElement = fixture.nativeElement.querySelector('.reset-btn');
      resetBtn.click();
      fixture.detectChanges();
      const last = emitted.at(-1)!;
      expect(last.text).toBe('');
      expect(last.elements).toHaveLength(0);
      expect(last.specialties).toHaveLength(0);
    });
  });
});
