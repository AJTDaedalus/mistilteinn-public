import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { describe, expect, it } from 'vitest';

import { TeamMemberFilters, defaultMemberFilters, type MemberFilterState } from './team-member-filters';
import { ELEMENTS, SPECIALTIES } from '../builds/build-filters';

async function render() {
  const emitted: MemberFilterState[] = [];

  @Component({
    template: `<team-member-filters (filtersChange)="onFilters($event)" />`,
    imports: [TeamMemberFilters],
    standalone: true,
  })
  class Host {
    onFilters(f: MemberFilterState) { emitted.push(f); }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, emitted };
}

describe('TeamMemberFilters', () => {
  describe('enum coverage', () => {
    it('renders all 5 elements from ELEMENTS constant', async () => {
      const { fixture } = await render();
      const titles = Array.from(
        fixture.nativeElement.querySelectorAll('[title]') as NodeListOf<HTMLElement>,
      ).map(el => el.getAttribute('title'));
      for (const el of ELEMENTS) {
        expect(titles).toContain(el);
      }
    });

    it('renders all 6 specialties from SPECIALTIES constant', async () => {
      const { fixture } = await render();
      const titles = Array.from(
        fixture.nativeElement.querySelectorAll('[title]') as NodeListOf<HTMLElement>,
      ).map(el => el.getAttribute('title'));
      for (const sp of SPECIALTIES) {
        expect(titles).toContain(sp);
      }
    });
  });

  describe('element facet', () => {
    it('toggling an element chip emits updated state', async () => {
      const { fixture, emitted } = await render();
      const chips: NodeListOf<HTMLButtonElement> = fixture.nativeElement.querySelectorAll('.chip--icon');
      chips[0].click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.elements).toHaveLength(1);
    });

    it('toggling same element chip twice deselects it', async () => {
      const { fixture, emitted } = await render();
      const chip: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.chip--icon')[0];
      chip.click();
      fixture.detectChanges();
      chip.click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.elements).toHaveLength(0);
    });
  });

  describe('specialty facet', () => {
    it('toggling a specialty chip emits updated state', async () => {
      const { fixture, emitted } = await render();
      // Specialty chips follow the 5 element chips
      const chips: NodeListOf<HTMLButtonElement> = fixture.nativeElement.querySelectorAll('.chip--icon');
      chips[5].click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.specialties).toHaveLength(1);
    });
  });

  describe('rarity facet', () => {
    it('toggling rarity S chip emits updated state with S', async () => {
      const { fixture, emitted } = await render();
      const rarityBtns = Array.from(
        fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>,
      ).filter(b => b.textContent?.trim() === 'S' || b.textContent?.trim() === 'A');
      rarityBtns[0].click(); // S
      fixture.detectChanges();
      expect(emitted.at(-1)?.rarities).toContain('S');
    });

    it('toggling rarity S twice deselects it', async () => {
      const { fixture, emitted } = await render();
      const rarityBtns = Array.from(
        fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>,
      ).filter(b => b.textContent?.trim() === 'S' || b.textContent?.trim() === 'A');
      rarityBtns[0].click();
      fixture.detectChanges();
      rarityBtns[0].click();
      fixture.detectChanges();
      expect(emitted.at(-1)?.rarities).not.toContain('S');
    });
  });

  describe('name facet', () => {
    it('name input emits on each keystroke', async () => {
      const { fixture, emitted } = await render();
      const input: HTMLInputElement = fixture.nativeElement.querySelector('.search-input');
      input.value = 'Z';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(emitted.at(-1)?.name).toBe('Z');
    });
  });

  describe('clear', () => {
    it('clear button is hidden when no filters active', async () => {
      const { fixture } = await render();
      const clearBtn = fixture.nativeElement.querySelector('.reset-btn');
      expect(clearBtn).toBeFalsy();
    });

    it('clear button appears after selecting a filter', async () => {
      const { fixture } = await render();
      const chip: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.chip--icon')[0];
      chip.click();
      fixture.detectChanges();
      const clearBtn = fixture.nativeElement.querySelector('.reset-btn');
      expect(clearBtn).toBeTruthy();
    });

    it('"clear" resets to defaultMemberFilters() and emits', async () => {
      const { fixture, emitted } = await render();
      const chip: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.chip--icon')[0];
      chip.click();
      fixture.detectChanges();
      const clearBtn: HTMLButtonElement = fixture.nativeElement.querySelector('.reset-btn');
      clearBtn.click();
      fixture.detectChanges();
      expect(emitted.at(-1)).toEqual(defaultMemberFilters());
    });
  });
});
