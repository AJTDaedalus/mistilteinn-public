import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { CardPicker, type CardFilter, type CardOption } from './card-picker';

/**
 * The pop-up grid the owner asked for four times.
 *
 * Most of what matters here is the **filter semantics** — within a group the chips are
 * alternatives, across groups they narrow — because getting that backwards makes a filter bar
 * widen as you add filters, which reads as broken rather than as wrong.
 */
describe('CardPicker', () => {
  let fixture: ComponentFixture<CardPicker>;

  const options: CardOption[] = [
    { value: 'nahida', label: 'Nahida', tags: { element: 'Dendro', weapon: 'Catalyst' } },
    { value: 'alhaitham', label: 'Alhaitham', tags: { element: 'Dendro', weapon: 'Sword' } },
    { value: 'ayaka', label: 'Kamisato Ayaka', tags: { element: 'Cryo', weapon: 'Sword' } },
    { value: 'beidou', label: 'Beidou', detail: 'C5', tags: { element: 'Electro', weapon: 'Claymore' } },
  ];

  const filters: CardFilter[] = [
    { group: 'element', label: 'Vision', options: [
      { value: 'Dendro', label: 'Dendro' }, { value: 'Cryo', label: 'Cryo' },
    ] },
    { group: 'weapon', label: 'Weapon', options: [
      { value: 'Sword', label: 'Sword' }, { value: 'Catalyst', label: 'Catalyst' },
    ] },
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [CardPicker] }).compileComponents();
    fixture = TestBed.createComponent(CardPicker);
    fixture.componentRef.setInput('options', options);
    fixture.componentRef.setInput('filters', filters);
    fixture.detectChanges();
  });

  const shown = () => {
    fixture.detectChanges();
    return [...fixture.nativeElement.querySelectorAll('.picker__name')]
      .map((el) => (el as HTMLElement).textContent?.trim());
  };
  const inner = () => fixture.componentInstance as unknown as {
    toggleFilter(g: string, v: string): void;
    pick(v: string): void;
    search: { set(v: string): void };
  };

  it('shows everything before anything is asked', () => {
    expect(shown()).toHaveLength(4);
  });

  it('treats chips in one group as alternatives', () => {
    inner().toggleFilter('element', 'Dendro');
    inner().toggleFilter('element', 'Cryo');

    // Dendro OR Cryo — three characters, not the zero an AND would give.
    expect(shown()).toHaveLength(3);
  });

  it('treats chips in different groups as narrowing', () => {
    inner().toggleFilter('element', 'Dendro');
    inner().toggleFilter('weapon', 'Sword');

    // **The one that must not be backwards.** A filter bar that widens as you add a filter
    // reads as broken rather than as wrong.
    expect(shown()).toEqual(['Alhaitham']);
  });

  it('searches the label and the detail', () => {
    inner().search.set('c5');

    expect(shown()).toEqual(['Beidou']);
  });

  it('applies the search and the filters together', () => {
    inner().toggleFilter('weapon', 'Sword');
    inner().search.set('ayaka');

    expect(shown()).toEqual(['Kamisato Ayaka']);
  });

  it('puts what is already chosen first', () => {
    // A picker's other job is showing what you picked. Scrolling a wall of sixty sets to find
    // the two that are ticked is the failure this replaces.
    fixture.componentRef.setInput('selected', ['beidou']);

    expect(shown()[0]).toBe('Beidou');
  });

  it('emits one value and nothing else when it is not multi', () => {
    const seen: string[][] = [];
    fixture.componentInstance.selectedChange.subscribe((v) => seen.push(v));
    fixture.componentRef.setInput('selected', ['nahida']);

    inner().pick('ayaka');

    expect(seen).toEqual([['ayaka']]);
  });

  it('adds and removes when it is multi', () => {
    const seen: string[][] = [];
    fixture.componentRef.setInput('multi', true);
    fixture.componentRef.setInput('selected', ['nahida']);
    fixture.componentInstance.selectedChange.subscribe((v) => seen.push(v));

    inner().pick('ayaka');
    fixture.componentRef.setInput('selected', ['nahida', 'ayaka']);
    inner().pick('nahida');

    expect(seen[0]).toEqual(['nahida', 'ayaka']);
    expect(seen[1]).toEqual(['ayaka']);
  });

  it('names every card, so the art is never the only label', () => {
    // A grid of pictures is fast for someone who knows the icons and useless to everyone else
    // — the argument `ElementChip` makes about colour.
    expect(shown().filter(Boolean)).toHaveLength(4);
  });

  it('says so rather than showing an empty grid', () => {
    inner().search.set('nobody');

    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Nothing matches');
  });
});
