import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { CatalogueService } from '../catalogue/catalogue.service';
import { PlannerPage } from './planner';
import { PlannerService, type PlanRead, type SectionRead } from './planner.service';

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 300 };

const OPTIONS = {
  level_caps: { 0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90 },
  talents: [],
  builds: [],
  owned_weapons: [],
  bonuses: [],
  uncurated_sources: ['ley_line_mora'],
};

function makePage(planner: Partial<PlannerService> = {}): PlannerPage {
  TestBed.configureTestingModule({
    providers: [
      {
        provide: PlannerService,
        useValue: { options: vi.fn(async () => OPTIONS), plan: vi.fn(), ...planner },
      },
      {
        provide: CatalogueService,
        useValue: {
          listCharacters: vi.fn(async () => EMPTY_PAGE),
          listWeapons: vi.fn(async () => EMPTY_PAGE),
        },
      },
    ],
  });
  return TestBed.runInInjectionContext(() => new PlannerPage());
}

function section(over: Partial<SectionRead['resin']> = {}): SectionRead {
  return {
    key: 'talents',
    label: 'Talents',
    mora: 100,
    materials: [],
    exp: null,
    resin: { expected: 0, unpriced: [], not_farmable: [], unpriced_sources: [], histogram: [], ...over },
  } as SectionRead;
}

describe('PlannerPage', () => {
  it('offers the levels a phase actually unlocks, not 1-90', async () => {
    // The rule the backend refuses a plan on: level 50 at ascension 0 is not a state the
    // game has. Offering it in the dropdown would make the page's own control produce a 422.
    const page = makePage();
    await page.ngOnInit();

    const phaseZero = page['levelsFor'](0);
    expect(phaseZero[0]).toBe(1);
    expect(phaseZero.at(-1)).toBe(20);
    // Phase 5 starts where phase 4 left off, so "ascend and stop" is reachable at either end.
    expect(page['levelsFor'](5)).toEqual(
      Array.from({ length: 11 }, (_, index) => 70 + index),
    );
  });

  it('turns an avatar icon into the full splash basename', async () => {
    const page = makePage();
    page['characters'].set([{ id: 'c1', name: 'Ayaka', icon: 'UI_AvatarIcon_Ayaka' } as never]);
    page['characterId'].set('c1');

    expect(page['splash']()).toBe('UI_Gacha_AvatarImg_Ayaka');
  });

  it('falls back to the avatar icon when there is no splash naming rule', async () => {
    // The Travelers: an icon upstream and no splash. `CatalogueIcon` then hides a broken
    // image, so the worst case is no art rather than a broken one.
    const page = makePage();
    page['characters'].set([{ id: 'c1', name: 'Odd', icon: 'UI_Something_Else' } as never]);
    page['characterId'].set('c1');

    expect(page['splash']()).toBe('UI_Something_Else');
  });

  it('shows a dash rather than "0" when nothing in a section could be priced', () => {
    // Zero is an answer; this is the absence of one, and the number is what a reader takes
    // away from a heading.
    const page = makePage();

    expect(page['sectionResin'](section({ unpriced_sources: ['mora'] }))).toBe('—');
    expect(page['sectionResin'](section({ expected: 640 }))).toContain('640');
  });

  it('names every gap in one sentence, counting materials and sources separately', () => {
    const page = makePage();

    expect(page['gaps'](section({ unpriced: [113018], unpriced_sources: ['mora'] })))
      .toBe('Resin unknown for 1 material(s) at an unpublished drop rate, mora.');
    expect(page['gaps'](section({ expected: 20 }))).toBeNull();
  });

  it('renders domain weekdays short, and nothing at all for a material with no domain', () => {
    const page = makePage();

    expect(page['days']({ domain_days: ['monday', 'thursday', 'sunday'] } as never))
      .toBe('Mon/Thu/Sun');
    expect(page['days']({ domain_days: [] } as never)).toBe('');
  });

  it('surfaces the backend’s own sentence when a plan is refused', async () => {
    // "level 50 is outside 1-20, which is what ascension phase 0 unlocks" is more useful than
    // anything this page could invent, so it is shown rather than replaced.
    const detail = 'target character level 50 is outside 1-20';
    const page = makePage({ plan: vi.fn(async () => { throw { detail }; }) });
    await page.ngOnInit();
    page['characterId'].set('c1');

    await page['run']();

    expect(page['error']()).toBe(detail);
    expect(page['plan']()).toBeNull();
  });

  it('keeps the plan and clears the error on a success', async () => {
    const result = { character_name: 'Ayaka', sections: [], total: section() } as unknown as PlanRead;
    const page = makePage({ plan: vi.fn(async () => result) });
    await page.ngOnInit();
    page['characterId'].set('c1');

    await page['run']();

    expect(page['plan']()).toBe(result);
    expect(page['error']()).toBeNull();
    expect(page['busy']()).toBe(false);
  });
});
