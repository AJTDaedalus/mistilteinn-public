import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { Component } from '@angular/core';

import { OptimizerStatFloors, type StatFloorMap } from './optimizer-stat-floors';

async function renderComponent(minStats: StatFloorMap = {}) {
  @Component({
    template: `
      <optimizer-stat-floors
        [minStats]="minStats"
        (minStatsChange)="onChange($event)"
      />
    `,
    imports: [OptimizerStatFloors],
    standalone: true,
  })
  class Host {
    minStats = minStats;
    emitted: StatFloorMap[] = [];
    onChange(s: StatFloorMap) {
      this.emitted.push(s);
      this.minStats = s;
    }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('OptimizerStatFloors', () => {
  it('is collapsed by default (no grid visible)', async () => {
    const fixture = await renderComponent();
    const grid = fixture.nativeElement.querySelector('.stat-floors__grid');
    expect(grid).toBeNull();
  });

  it('expands grid on toggle click', async () => {
    const fixture = await renderComponent();
    const toggle = fixture.nativeElement.querySelector('.stat-floors__toggle');
    toggle.click();
    fixture.detectChanges();
    const grid = fixture.nativeElement.querySelector('.stat-floors__grid');
    expect(grid).toBeTruthy();
  });

  it('shows 7 stat rows when expanded', async () => {
    const fixture = await renderComponent();
    fixture.nativeElement.querySelector('.stat-floors__toggle').click();
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('.stat-floors__row');
    expect(rows.length).toBe(7);
  });

  it('renders input values from minStats', async () => {
    const fixture = await renderComponent({ crit_rate: 2400 });
    fixture.nativeElement.querySelector('.stat-floors__toggle').click();
    fixture.detectChanges();
    const inputs = fixture.nativeElement.querySelectorAll('.stat-floors__input');
    // crit_rate is index 2 in the STAT_FLOORS list
    expect(inputs[2].value).toBe('2400');
  });

  it('emits updated map when a value changes', async () => {
    const fixture = await renderComponent();
    const host = fixture.componentInstance;
    fixture.nativeElement.querySelector('.stat-floors__toggle').click();
    fixture.detectChanges();

    const inputs = fixture.nativeElement.querySelectorAll('.stat-floors__input');
    // Set ATK floor (index 0) to 1000.
    inputs[0].value = '1000';
    inputs[0].dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(host.emitted.length).toBe(1);
    expect(host.emitted[0]['atk']).toBe(1000);
  });

  it('omits key from emitted map when value set to 0', async () => {
    const fixture = await renderComponent({ atk: 500 });
    const host = fixture.componentInstance;
    fixture.nativeElement.querySelector('.stat-floors__toggle').click();
    fixture.detectChanges();

    const inputs = fixture.nativeElement.querySelectorAll('.stat-floors__input');
    inputs[0].value = '0';
    inputs[0].dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(host.emitted.length).toBe(1);
    expect('atk' in host.emitted[0]).toBe(false);
  });
});
