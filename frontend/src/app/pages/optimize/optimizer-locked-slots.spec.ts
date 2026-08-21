import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { Component } from '@angular/core';

import { OptimizerLockedSlots, type LockedSlotMap } from './optimizer-locked-slots';

async function renderComponent(lockedSlots: LockedSlotMap = {}) {
  @Component({
    template: `
      <optimizer-locked-slots
        [lockedSlots]="lockedSlots"
        (lockedSlotsChange)="onChange($event)"
      />
    `,
    imports: [OptimizerLockedSlots],
    standalone: true,
  })
  class Host {
    lockedSlots = lockedSlots;
    emitted: LockedSlotMap[] = [];
    onChange(s: LockedSlotMap) {
      this.emitted.push(s);
      this.lockedSlots = s;
    }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('OptimizerLockedSlots', () => {
  it('is collapsed by default', async () => {
    const fixture = await renderComponent();
    const table = fixture.nativeElement.querySelector('.locked-slots__table');
    expect(table).toBeNull();
  });

  it('expands to show 6 rows after toggle', async () => {
    const fixture = await renderComponent();
    fixture.nativeElement.querySelector('.locked-slots__toggle').click();
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(rows.length).toBe(6);
  });

  it('emits updated map when a slot value is set', async () => {
    const fixture = await renderComponent();
    const host = fixture.componentInstance;
    fixture.nativeElement.querySelector('.locked-slots__toggle').click();
    fixture.detectChanges();

    const inputs = fixture.nativeElement.querySelectorAll('.locked-slots__input');
    inputs[0].value = 'abc-disc-id';
    inputs[0].dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(host.emitted.length).toBe(1);
    expect((host.emitted[0] as Record<number, string>)[1]).toBe('abc-disc-id');
  });

  it('removes key from map when slot cleared', async () => {
    const fixture = await renderComponent({ 1: 'some-id' } as LockedSlotMap);
    const host = fixture.componentInstance;
    fixture.nativeElement.querySelector('.locked-slots__toggle').click();
    fixture.detectChanges();

    const clearBtn = fixture.nativeElement.querySelector('.locked-slots__clear');
    clearBtn.click();
    fixture.detectChanges();

    expect(host.emitted.length).toBe(1);
    expect((host.emitted[0] as Record<number, string>)[1]).toBeUndefined();
  });
});
