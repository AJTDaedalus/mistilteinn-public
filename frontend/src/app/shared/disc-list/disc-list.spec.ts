import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { DiscList } from './disc-list';

interface DiscLike {
  id: string;
  slot: number;
  disc_set_id: string;
  rarity: string;
  level: number;
  main_stat_type: string;
  main_stat_value: number;
  substats?: { stat: string; value: number; rolls?: number }[];
  build_id?: string | null;
}

function makeDisc(partial: Partial<DiscLike> & { id: string }): DiscLike {
  return {
    slot: 1,
    disc_set_id: 'set-a',
    rarity: 'S',
    level: 15,
    main_stat_type: 'hp_pct',
    main_stat_value: 3000,
    substats: [],
    build_id: null,
    ...partial,
  };
}

function createComponent(discs: DiscLike[] = []) {
  TestBed.configureTestingModule({ imports: [DiscList] });
  const fixture = TestBed.createComponent(DiscList);
  fixture.componentRef.setInput('discs', discs);
  fixture.detectChanges();
  return fixture;
}

describe('DiscList filtering', () => {
  it('shows all discs when no filters active', () => {
    const discs = [makeDisc({ id: 'd1' }), makeDisc({ id: 'd2' })];
    const fixture = createComponent(discs);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('fairy-disc-card')).toHaveLength(2);
  });

  it('main stat filter narrows to matching discs only', () => {
    const discs = [
      makeDisc({ id: 'd1', main_stat_type: 'atk_pct' }),
      makeDisc({ id: 'd2', main_stat_type: 'crit_rate' }),
      makeDisc({ id: 'd3', main_stat_type: 'atk_pct' }),
    ];
    const fixture = createComponent(discs);
    const comp = fixture.componentInstance;
    comp['filters'].set({ ...comp['filters'](), mainStats: ['atk_pct'] });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('fairy-disc-card')).toHaveLength(2);
  });

  it('substat filter uses AND semantics — only discs with ALL selected substats', () => {
    const discs = [
      makeDisc({ id: 'd1', substats: [{ stat: 'crit_rate', value: 240 }, { stat: 'crit_dmg', value: 480 }] }),
      makeDisc({ id: 'd2', substats: [{ stat: 'crit_rate', value: 240 }] }),
      makeDisc({ id: 'd3', substats: [{ stat: 'crit_dmg', value: 480 }] }),
      makeDisc({ id: 'd4', substats: [] }),
    ];
    const fixture = createComponent(discs);
    const comp = fixture.componentInstance;
    comp['filters'].set({ ...comp['filters'](), substats: ['crit_rate', 'crit_dmg'] });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('fairy-disc-card')).toHaveLength(1);
  });

  it('set + rarity filter uses AND across categories', () => {
    const discs = [
      makeDisc({ id: 'd1', disc_set_id: 'set-a', rarity: 'S' }),
      makeDisc({ id: 'd2', disc_set_id: 'set-b', rarity: 'S' }),
      makeDisc({ id: 'd3', disc_set_id: 'set-a', rarity: 'A' }),
    ];
    const fixture = createComponent(discs);
    const comp = fixture.componentInstance;
    comp['filters'].set({ ...comp['filters'](), sets: ['set-a'], rarities: ['S'] });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('fairy-disc-card')).toHaveLength(1);
  });

  it('minLevel filter excludes discs below threshold', () => {
    const discs = [
      makeDisc({ id: 'd1', level: 0 }),
      makeDisc({ id: 'd2', level: 9 }),
      makeDisc({ id: 'd3', level: 15 }),
    ];
    const fixture = createComponent(discs);
    const comp = fixture.componentInstance;
    comp['filters'].set({ ...comp['filters'](), minLevel: 10 });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('fairy-disc-card')).toHaveLength(1);
  });

  it('equipped=unequipped hides discs with a build_id', () => {
    const discs = [
      makeDisc({ id: 'd1', build_id: 'b1' }),
      makeDisc({ id: 'd2', build_id: null }),
      makeDisc({ id: 'd3', build_id: null }),
    ];
    const fixture = createComponent(discs);
    const comp = fixture.componentInstance;
    comp['filters'].set({ ...comp['filters'](), equipped: 'unequipped' });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('fairy-disc-card')).toHaveLength(2);
  });

  it('sort level desc orders highest level first', () => {
    const discs = [
      makeDisc({ id: 'low', level: 15 }),
      makeDisc({ id: 'high', level: 25 }),
      makeDisc({ id: 'mid', level: 20 }),
    ];
    const fixture = createComponent(discs);
    const comp = fixture.componentInstance;
    comp['filters'].set({ ...comp['filters'](), sort: 'level' });
    fixture.detectChanges();

    const filtered = comp['filtered']();
    expect(filtered[0].id).toBe('high');
    expect(filtered[1].id).toBe('mid');
    expect(filtered[2].id).toBe('low');
  });

  it('emits select event in pick mode when a card wrapper is clicked', () => {
    const discs = [makeDisc({ id: 'pick-me' })];
    const fixture = createComponent(discs);
    fixture.componentRef.setInput('mode', 'pick');
    fixture.detectChanges();

    const emitted: string[] = [];
    fixture.componentInstance.discSelected.subscribe((id: string) => emitted.push(id));

    const item = (fixture.nativeElement as HTMLElement).querySelector('.disc-list__item--clickable') as HTMLElement;
    item?.click();
    expect(emitted).toEqual(['pick-me']);
  });

  it('computes setIcons mapping using icon_path and passes to card', () => {
    const discs = [makeDisc({ id: 'd1', disc_set_id: 'set-a' })];
    TestBed.configureTestingModule({ imports: [DiscList] });
    const fixture = TestBed.createComponent(DiscList);
    fixture.componentRef.setInput('discs', discs);
    fixture.componentRef.setInput('discSets', [
      { id: 'set-a', name: 'Woodpecker Electro', icon_path: 'Item/Disc/Woodpecker.png' }
    ]);
    fixture.detectChanges();

    const comp = fixture.componentInstance;
    const icons = comp['setIcons']();
    expect(icons['set-a']).toBe('/icons/Woodpecker.webp');

    const img = (fixture.nativeElement as HTMLElement).querySelector('.disc-card__icon') as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute('src')).toBe('/icons/Woodpecker.webp');
  });
});
