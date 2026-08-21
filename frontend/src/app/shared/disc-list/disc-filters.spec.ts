import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DiscFiltersPanel, defaultFilters, type DiscFilterState } from './disc-filters';
import type { DiscSetSummary } from '../icon-url';

const DISC_SETS: DiscSetSummary[] = [
  { id: 'set-a', hakushin_id: 1, name: 'Chaotic Metal', two_piece_text: '2pc a', four_piece_text: '4pc a', icon_path: '' },
  { id: 'set-b', hakushin_id: 2, name: 'Fanged Metal', two_piece_text: '2pc b', four_piece_text: '4pc b', icon_path: '' },
];

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});

async function renderFilters(discSets = DISC_SETS) {
  const emitted: DiscFilterState[] = [];

  @Component({
    template: `<fairy-disc-filters [discSets]="sets" (filtersChange)="onFilters($event)" />`,
    imports: [DiscFiltersPanel],
    standalone: true,
  })
  class Host {
    sets = discSets;
    onFilters(f: DiscFilterState) { emitted.push(f); }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, emitted };
}

describe('DiscFiltersPanel — set filter', () => {
  it('renders the set-picker trigger button when sets are provided', async () => {
    const { fixture } = await renderFilters();
    const trigger = fixture.nativeElement.querySelector('.slot-btn');
    expect(trigger).toBeTruthy();
  });

  it('emits selected set id when a set card is clicked', async () => {
    const { fixture, emitted } = await renderFilters();
    const card = Array.from(
      fixture.nativeElement.querySelectorAll('.set-card') as NodeListOf<HTMLButtonElement>,
    ).find((b) => b.textContent?.includes('Chaotic Metal'));
    card?.click();
    fixture.detectChanges();
    expect(emitted.at(-1)?.sets).toContain('set-a');
  });

  it('deselects set on second click', async () => {
    const { fixture, emitted } = await renderFilters();
    const card = Array.from(
      fixture.nativeElement.querySelectorAll('.set-card') as NodeListOf<HTMLButtonElement>,
    ).find((b) => b.textContent?.includes('Chaotic Metal'));
    card?.click();
    fixture.detectChanges();
    card?.click();
    fixture.detectChanges();
    expect(emitted.at(-1)?.sets).not.toContain('set-a');
  });

  it('reset clears the set selection', async () => {
    const { fixture, emitted } = await renderFilters();
    const card = Array.from(
      fixture.nativeElement.querySelectorAll('.set-card') as NodeListOf<HTMLButtonElement>,
    ).find((b) => b.textContent?.includes('Chaotic Metal'));
    card?.click();
    fixture.detectChanges();

    const resetBtn = Array.from(
      fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>,
    ).find((b) => b.textContent?.trim() === 'Reset');
    resetBtn?.click();
    fixture.detectChanges();
    expect(emitted.at(-1)?.sets).toHaveLength(0);
  });
});

describe('DiscFiltersPanel — defaultFilters', () => {
  it('returns expected defaults', () => {
    const f = defaultFilters();
    expect(f.sets).toHaveLength(0);
    expect(f.rarities).toContain('S');
    expect(f.minLevel).toBe(15);
  });
});
