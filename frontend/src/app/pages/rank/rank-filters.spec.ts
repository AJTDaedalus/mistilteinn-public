import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RankFilters } from './rank-filters';
import type { RankFilterState } from './rank-filters';
import type { DiscSetSummary } from '../../shared/icon-url';

const DISC_SETS: DiscSetSummary[] = [
  { id: 'set-a', hakushin_id: 1, name: 'Chaotic Metal', two_piece_text: '2pc a', four_piece_text: '4pc a', icon_path: '' },
  { id: 'set-b', hakushin_id: 2, name: 'Fanged Metal', two_piece_text: '2pc b', four_piece_text: '4pc b', icon_path: '' },
];

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});

async function renderFilters(discSets = DISC_SETS) {
  const emitted: RankFilterState[] = [];

  @Component({
    template: `<rank-filters [discSets]="sets" (filtersChange)="onFilters($event)" />`,
    imports: [RankFilters],
    standalone: true,
  })
  class Host {
    sets = discSets;
    onFilters(f: RankFilterState) { emitted.push(f); }
  }

  TestBed.configureTestingModule({});
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, emitted };
}

function clickButton(fixture: ReturnType<typeof TestBed.createComponent>, text: string): void {
  const btns = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
  const btn = btns.find((b) => b.textContent?.trim() === text);
  if (!btn) throw new Error(`Button not found: "${text}"`);
  btn.click();
  fixture.detectChanges();
}

function clickSetCard(fixture: ReturnType<typeof TestBed.createComponent>, name: string): void {
  const cards = Array.from(fixture.nativeElement.querySelectorAll('.set-card')) as HTMLButtonElement[];
  const card = cards.find((b) => b.textContent?.includes(name));
  if (!card) throw new Error(`Set card not found: "${name}"`);
  card.click();
  fixture.detectChanges();
}

describe('RankFilters', () => {
  describe('F1 — slot filter', () => {
    it('emits slot=1 when slot 1 button is clicked', async () => {
      const { fixture, emitted } = await renderFilters();
      clickButton(fixture, '1');
      expect(emitted.at(-1)?.slot).toBe(1);
    });

    it('resets slot to 0 when All is clicked', async () => {
      const { fixture, emitted } = await renderFilters();
      clickButton(fixture, '1');
      clickButton(fixture, 'All');
      expect(emitted.at(-1)?.slot).toBe(0);
    });
  });

  describe('F2 — set filter', () => {
    it('renders the set-picker trigger button when sets are provided', async () => {
      const { fixture } = await renderFilters();
      const trigger = fixture.nativeElement.querySelector('.slot-btn');
      expect(trigger).toBeTruthy();
    });

    it('emits selected set id when a set card is clicked', async () => {
      const { fixture, emitted } = await renderFilters();
      clickSetCard(fixture, 'Chaotic Metal');
      expect(emitted.at(-1)?.sets).toContain('set-a');
    });

    it('deselects set on second click', async () => {
      const { fixture, emitted } = await renderFilters();
      clickSetCard(fixture, 'Chaotic Metal');
      clickSetCard(fixture, 'Chaotic Metal');
      expect(emitted.at(-1)?.sets).not.toContain('set-a');
    });
  });

  describe('F3 — reset', () => {
    it('clears slot and sets on reset', async () => {
      const { fixture, emitted } = await renderFilters();
      clickButton(fixture, '2');
      clickSetCard(fixture, 'Chaotic Metal');
      clickButton(fixture, 'Reset');
      const last = emitted.at(-1)!;
      expect(last.slot).toBe(0);
      expect(last.sets).toHaveLength(0);
    });
  });
});
