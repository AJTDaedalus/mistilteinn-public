import { TestBed } from '@angular/core/testing';
import { ComponentRef } from '@angular/core';
import { describe, expect, it } from 'vitest';

import { DiscCard } from './disc-card';
import type { DiscRead } from '../../pages/builds/builds.service';

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

function makeDisc(partial: Partial<DiscLike> & { id: string }): DiscRead {
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
  } as unknown as DiscRead;
}

function createComponent(disc: DiscRead) {
  TestBed.configureTestingModule({ imports: [DiscCard] });
  const fixture = TestBed.createComponent(DiscCard);
  const ref = fixture.componentRef as ComponentRef<DiscCard>;
  ref.setInput('disc', disc);
  fixture.detectChanges();
  return fixture;
}

describe('DiscCard roll display', () => {
  it('shows one dot for a substat at its guaranteed initial roll (issue #65)', () => {
    const disc = makeDisc({ id: 'd1', substats: [{ stat: 'crit_dmg', value: 480, rolls: 1 }] });
    const fixture = createComponent(disc);
    const dots = fixture.nativeElement.querySelectorAll('.disc-card__dot');
    expect(dots.length).toBe(1);
  });

  it('shows total rolls, not upgrade-only, for a leveled substat', () => {
    const disc = makeDisc({ id: 'd2', substats: [{ stat: 'crit_dmg', value: 1440, rolls: 3 }] });
    const fixture = createComponent(disc);
    const dots = fixture.nativeElement.querySelectorAll('.disc-card__dot');
    expect(dots.length).toBe(3);
  });

  it('defaults to one dot when a substat has no rolls field', () => {
    const disc = makeDisc({ id: 'd3', substats: [{ stat: 'crit_dmg', value: 480 }] });
    const fixture = createComponent(disc);
    const dots = fixture.nativeElement.querySelectorAll('.disc-card__dot');
    expect(dots.length).toBe(1);
  });
});
