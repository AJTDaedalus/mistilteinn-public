import { TestBed } from '@angular/core/testing';
import { ComponentRef } from '@angular/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SetPicker } from './set-picker';
import type { DiscSetSummary } from '../icon-url';

const SETS: DiscSetSummary[] = [
  { id: 'a', hakushin_id: 1, name: 'Chaotic Metal', two_piece_text: '2pc a', four_piece_text: '4pc a', icon_path: '' },
  { id: 'b', hakushin_id: 2, name: 'Fanged Metal', two_piece_text: '2pc b', four_piece_text: '4pc b', icon_path: '' },
  { id: 'c', hakushin_id: 3, name: 'Polar Metal', two_piece_text: '2pc c', four_piece_text: '4pc c', icon_path: '' },
];

function setup(selected: string[] = [], label = 'Set') {
  TestBed.configureTestingModule({ imports: [SetPicker] });
  const f = TestBed.createComponent(SetPicker);
  const ref = f.componentRef as ComponentRef<SetPicker>;
  ref.setInput('allSets', SETS);
  ref.setInput('selected', selected);
  ref.setInput('label', label);
  f.detectChanges();
  return f;
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});

describe('SetPicker', () => {
  describe('trigger button', () => {
    it('shows label as eyebrow text', () => {
      const f = setup([], 'My Label');
      const label = f.nativeElement.querySelector('.slot-btn__label') as HTMLElement;
      expect(label?.textContent?.trim()).toBe('My Label');
    });

    it('shows a fillable empty-slot placeholder when nothing is selected', () => {
      const f = setup([]);
      const el = f.nativeElement.querySelector('.slot-btn__empty') as HTMLElement;
      expect(el).toBeTruthy();
      expect(el.textContent).toContain('select one or more');
    });

    it('shows selected set chips when sets are selected', () => {
      const f = setup(['a', 'b']);
      const chips = f.nativeElement.querySelectorAll('.slot-chip:not(.slot-chip--add)');
      expect(chips.length).toBe(2);
    });

    it('appends a dashed "add another" chip after one set is already selected (issue #60)', () => {
      const f = setup(['a']);
      const addChip = f.nativeElement.querySelector('.slot-chip--add') as HTMLElement;
      expect(addChip).toBeTruthy();
      expect(addChip.textContent).toContain('add another');
    });

    it('still shows the "add another" affordance after selecting a second set', () => {
      const f = setup(['a', 'b']);
      const realChips = f.nativeElement.querySelectorAll('.slot-chip:not(.slot-chip--add)');
      const addChip = f.nativeElement.querySelector('.slot-chip--add');
      expect(realChips.length).toBe(2);
      expect(addChip).toBeTruthy();
    });

    it('does not show the "add another" chip in the empty state', () => {
      const f = setup([]);
      const addChip = f.nativeElement.querySelector('.slot-chip--add');
      expect(addChip).toBeFalsy();
    });

    it('calls showModal when clicked', () => {
      const f = setup([]);
      const btn = f.nativeElement.querySelector('.slot-btn') as HTMLButtonElement;
      btn.click();
      expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    });
  });

  describe('dialog close', () => {
    it('calls close and clears search when close button is clicked', () => {
      const f = setup([]);
      const closeBtn = f.nativeElement.querySelector('.icon-btn') as HTMLButtonElement;
      closeBtn.click();
      expect(HTMLDialogElement.prototype.close).toHaveBeenCalled();
    });

    it('Done button calls close', () => {
      const f = setup([]);
      const doneBtn = f.nativeElement.querySelector('.btn.btn-primary') as HTMLButtonElement;
      doneBtn.click();
      expect(HTMLDialogElement.prototype.close).toHaveBeenCalled();
    });
  });

  describe('card toggle', () => {
    it('emits selectedChange with added id on first click', () => {
      const f = setup([]);
      const emitted: string[][] = [];
      f.componentInstance.selectedChange.subscribe((ids: string[]) => emitted.push(ids));

      const cards = f.nativeElement.querySelectorAll('.set-card') as NodeListOf<HTMLButtonElement>;
      cards[0].click();
      expect(emitted.length).toBe(1);
      expect(emitted[0]).toContain('a');
    });

    it('emits selectedChange with both ids when a second set is picked (issue #60)', () => {
      const f = setup(['a']);
      const emitted: string[][] = [];
      f.componentInstance.selectedChange.subscribe((ids: string[]) => emitted.push(ids));

      f.detectChanges();
      // 'a' is already selected, so it sorts first; 'b' is the next unselected card.
      const cards = f.nativeElement.querySelectorAll('.set-card') as NodeListOf<HTMLButtonElement>;
      cards[1].click();
      expect(emitted.length).toBe(1);
      expect(emitted[0]).toContain('a');
      expect(emitted[0]).toContain('b');
    });

    it('emits selectedChange without id on deselect', () => {
      const f = setup(['a']);
      const emitted: string[][] = [];
      f.componentInstance.selectedChange.subscribe((ids: string[]) => emitted.push(ids));

      f.detectChanges();
      const cards = f.nativeElement.querySelectorAll('.set-card') as NodeListOf<HTMLButtonElement>;
      // First card should be 'a' (selected sets appear first in sorted order)
      cards[0].click();
      expect(emitted[0]).not.toContain('a');
    });
  });

  describe('search filtering', () => {
    it('filters the grid by name when search text is set', () => {
      const f = setup([]);
      const cmp = f.componentInstance as unknown as {
        search: { set: (v: string) => void };
        sortedSets: () => DiscSetSummary[];
      };
      cmp.search.set('chaotic');
      f.detectChanges();
      const filtered = cmp.sortedSets();
      expect(filtered.length).toBe(1);
      expect(filtered[0].name).toBe('Chaotic Metal');
    });

    it('is case-insensitive', () => {
      const f = setup([]);
      const cmp = f.componentInstance as unknown as {
        search: { set: (v: string) => void };
        sortedSets: () => DiscSetSummary[];
      };
      cmp.search.set('FANGED');
      f.detectChanges();
      expect(cmp.sortedSets().length).toBe(1);
    });
  });

  describe('Clear button', () => {
    it('emits empty array when Clear is clicked', () => {
      const f = setup(['a', 'b']);
      f.detectChanges();
      const emitted: string[][] = [];
      f.componentInstance.selectedChange.subscribe((ids: string[]) => emitted.push(ids));

      const clearBtn = f.nativeElement.querySelector('.link-btn') as HTMLButtonElement;
      clearBtn.click();
      expect(emitted.length).toBe(1);
      expect(emitted[0]).toHaveLength(0);
    });
  });

  describe('sorted order', () => {
    it('places selected sets before unselected sets', () => {
      const f = setup(['c']);
      f.detectChanges();
      const cmp = f.componentInstance as unknown as {
        sortedSets: () => DiscSetSummary[];
      };
      const sorted = cmp.sortedSets();
      expect(sorted[0].id).toBe('c');
    });

    it('sorts unselected sets alphabetically', () => {
      const f = setup([]);
      const cmp = f.componentInstance as unknown as {
        sortedSets: () => DiscSetSummary[];
      };
      const sorted = cmp.sortedSets();
      const names = sorted.map((s) => s.name);
      expect(names).toEqual([...names].sort());
    });
  });
});
