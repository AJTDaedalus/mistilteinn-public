import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { Component } from '@angular/core';

import {
  OptimizerInventoryFilter,
  emptyInventoryFilterState,
  type InventoryFilterState,
} from './optimizer-inventory-filter';

async function renderComponent(state: InventoryFilterState = emptyInventoryFilterState()) {
  @Component({
    template: `
      <optimizer-inventory-filter
        [state]="state"
        (stateChange)="onChange($event)"
      />
    `,
    imports: [OptimizerInventoryFilter],
    standalone: true,
  })
  class Host {
    state = state;
    emitted: InventoryFilterState[] = [];
    onChange(s: InventoryFilterState) {
      this.emitted.push(s);
      this.state = s;
    }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('OptimizerInventoryFilter', () => {
  describe('C7 — rarity + level', () => {
    it('defaults to S rarity', async () => {
      const fixture = await renderComponent();
      const activeChip = fixture.nativeElement.querySelector('.rarity-chip--active');
      expect(activeChip?.textContent?.trim()).toBe('S');
    });

    it('defaults to min level 15', async () => {
      const fixture = await renderComponent();
      const levelInput = fixture.nativeElement.querySelector('.inv-filter__level');
      expect(levelInput.value).toBe('15');
    });

    it('emits updated rarity when chip clicked', async () => {
      const fixture = await renderComponent();
      const host = fixture.componentInstance;

      const chips = fixture.nativeElement.querySelectorAll('.rarity-chip');
      // Click "A"
      chips[1].click();
      fixture.detectChanges();

      expect(host.emitted.length).toBe(1);
      expect(host.emitted[0].minRarity).toBe('A');
    });

    it('emits updated level when changed', async () => {
      const fixture = await renderComponent();
      const host = fixture.componentInstance;

      const levelInput = fixture.nativeElement.querySelector('.inv-filter__level');
      levelInput.value = '10';
      levelInput.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(host.emitted.length).toBe(1);
      expect(host.emitted[0].minLevel).toBe(10);
    });
  });

  describe('C7b — main stat by slot', () => {
    it('shows "any" hint when no main selected for a slot', async () => {
      const fixture = await renderComponent();
      const anyHints = fixture.nativeElement.querySelectorAll('.inv-filter__any-hint');
      expect(anyHints.length).toBe(3); // slots 4, 5, 6 all unfiltered
    });

    it('emits selection when a main-stat chip is toggled', async () => {
      const fixture = await renderComponent();
      const host = fixture.componentInstance;

      // Slot 6 chips appear last; find CRIT Rate chip (which is in slot 4)
      // Better: find slot-4 row, click "CRIT Rate" chip
      const slot4Chips = fixture.nativeElement.querySelectorAll(
        '.inv-filter__slot-row:first-of-type .main-chip',
      );
      // CRIT Rate is index 3 in slot-4 mains
      slot4Chips[3].click();
      fixture.detectChanges();

      expect(host.emitted.length).toBe(1);
      expect(host.emitted[0].mainStatBySlot[4]).toContain('crit_rate');
    });

    it('deselects chip on second click', async () => {
      const state: InventoryFilterState = {
        minRarity: 'S',
        minLevel: 15,
        mainStatBySlot: { 4: ['crit_rate'] },
      };
      const fixture = await renderComponent(state);
      const host = fixture.componentInstance;

      const slot4Chips = fixture.nativeElement.querySelectorAll(
        '.inv-filter__slot-row:first-of-type .main-chip',
      );
      // CRIT Rate chip should be active; click to deselect
      slot4Chips[3].click();
      fixture.detectChanges();

      expect(host.emitted.length).toBe(1);
      // key removed because array became empty
      expect(host.emitted[0].mainStatBySlot[4]).toBeUndefined();
    });

    it('empty mainStatBySlot means all mains allowed (no filtering)', async () => {
      // Verify the default state has empty mainStatBySlot
      const state = emptyInventoryFilterState();
      expect(state.mainStatBySlot).toEqual({});
    });
  });
});
