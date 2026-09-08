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
  it('offers every level, because level is what a player reads off their screen', async () => {
    // The control used to list only the levels the *chosen phase* allowed, which put the
    // derived value in front: someone at level 62 had to work out that 62 means phase 4
    // before the page would offer 62 at all.
    const page = makePage();
    await page.ngOnInit();

    expect(page['levels'][0]).toBe(1);
    expect(page['levels'].at(-1)).toBe(90);
    expect(page['levels']).toHaveLength(90);
  });

  it('asks about ascension only at a cap, and then offers exactly two', async () => {
    // 80 is the top of phase 5 and the floor of phase 6, and both are real states the game
    // distinguishes — only one of them can go on to 90. Every other level sits in exactly one
    // phase and there is nothing to ask.
    const page = makePage();
    await page.ngOnInit();

    expect(page['ascensionsAt'](80).map((entry) => entry.phase)).toEqual([5, 6]);
    expect(page['ascensionAmbiguous'](80)).toBe(true);
    expect(page['ascensionsAt'](55).map((entry) => entry.phase)).toEqual([3]);
    expect(page['ascensionAmbiguous'](55)).toBe(false);
    // The two ends are unambiguous, which is why the page's own defaults ask nothing.
    expect(page['ascensionAmbiguous'](1)).toBe(false);
    expect(page['ascensionAmbiguous'](90)).toBe(false);
  });

  it('writes a phase the way the game does, current over max', async () => {
    // "5" and "6" at level 80 are before and after the same ascension, and the cap is what
    // separates them: A5 is capped where it stands, A6 has ninety levels of headroom. The
    // game's own `current/max` shorthand, so the answer is read rather than translated.
    const page = makePage();
    await page.ngOnInit();

    expect(page['ascensionLabel'](5, 80)).toBe('A5 80/80');
    expect(page['ascensionLabel'](6, 80)).toBe('A6 80/90');
  });

  it('follows that shape at every ascension boundary', async () => {
    // The boundaries are not evenly spaced — 20, 40, then 50/60/70/80 ten apart — so a rule
    // checked only at 80 would pass while saying nothing about the two that differ.
    const page = makePage();
    await page.ngOnInit();

    const at = (level: number) => page['ascensionsAt'](level)
      .map((entry) => page['ascensionLabel'](entry.phase, level));

    expect(at(20)).toEqual(['A0 20/20', 'A1 20/40']);
    expect(at(40)).toEqual(['A1 40/40', 'A2 40/50']);
    expect(at(50)).toEqual(['A2 50/50', 'A3 50/60']);
    expect(at(60)).toEqual(['A3 60/60', 'A4 60/70']);
    expect(at(70)).toEqual(['A4 70/70', 'A5 70/80']);
    expect(at(80)).toEqual(['A5 80/80', 'A6 80/90']);
  });

  it('replaces a phase the new level cannot be in', async () => {
    // The hazard the old model had, running the other way. A phase left over from the
    // previous level would be posted against a level it does not contain — and 1/6 is exactly
    // the pair that billed a user for 1→90 instead of 80→90 without anything rejecting it.
    const page = makePage();
    await page.ngOnInit();
    page['fromAscension'].set(6);

    page['setLevel'](55, page['fromLevel'], page['fromAscension']);

    expect(page['fromLevel']()).toBe(55);
    expect(page['fromAscension']()).toBe(3);
  });

  it('keeps a phase that is still legal at the new level', async () => {
    // Moving the target from 90 to 80 leaves phase 6 legal — that is "ascend but stop at 80",
    // the case the two controls exist for. Clamping to the lower phase here would silently
    // delete the plan the user was expressing.
    const page = makePage();
    await page.ngOnInit();

    page['setLevel'](80, page['toLevel'], page['toAscension']);

    expect(page['toAscension']()).toBe(6);
  });

  it('cannot produce a level and phase the backend would refuse', async () => {
    // **The property, rather than the instance.** The backend rejects a pair the game cannot
    // produce — "level 50 is outside 1-20, which is what ascension phase 0 unlocks" — and a
    // control that can express such a pair and leaves the server to say no is a control that
    // should not have offered it. This walks every level the picker lists and every phase it
    // would offer at that level.
    const page = makePage();
    await page.ngOnInit();
    const caps = page['options']()!.level_caps as Record<number, number>;

    for (const level of page['levels']) {
      const offered = page['ascensionsAt'](level);
      expect(offered.length).toBeGreaterThan(0);
      for (const { phase } of offered) {
        const floor = phase === 0 ? 1 : caps[phase - 1];
        expect(level).toBeGreaterThanOrEqual(floor);
        expect(level).toBeLessThanOrEqual(caps[phase]);
      }
    }
  });

  it('groups crafting help by material class and by what the passive does', async () => {
    // Two facts per passive — which materials it touches and what it does to them — and the
    // flat list encoded both in one sentence, so twelve rows all read the same.
    const page = makePage();
    await page.ngOnInit();
    page['options'].set({
      ...page['options']()!,
      bonuses: [
        { character_id: 'a', character_name: 'Albedo', effect: 'double', chance: 0.1,
          classes: ['weapon_ascension'], applicable: true } as never,
        { character_id: 'x', character_name: 'Xingqiu', effect: 'refund', chance: 0.25,
          classes: ['talent'], applicable: false } as never,
        // Sucrose names both classes, so she belongs in both tables. That is duplication on
        // screen and it is right: each table answers "what can help *this* class".
        { character_id: 's', character_name: 'Sucrose', effect: 'double', chance: 0.1,
          classes: ['weapon_ascension', 'talent'], applicable: true } as never,
      ],
    });

    const groups = page['craftGroups']();
    const weapon = groups.find((g) => g.key === 'weapon_ascension')!;
    const talent = groups.find((g) => g.key === 'talent')!;

    expect(weapon.bonus.map((b) => b.character_name)).toEqual(['Albedo', 'Sucrose']);
    expect(weapon.refund).toEqual([]);
    expect(talent.bonus.map((b) => b.character_name)).toEqual(['Sucrose']);
    expect(talent.refund.map((b) => b.character_name)).toEqual(['Xingqiu']);
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

describe('the resin histogram', () => {
  const section = (probabilities: number[]) => ({
    resin: {
      histogram: probabilities.map((probability, index) => ({
        low: index * 10, high: (index + 1) * 10, probability,
      })),
    },
  }) as never;

  it('scales bars against a round ceiling, not against the tallest bar', async () => {
    // **The bug this replaces.** Every bar used to be a percentage of the peak, so the tallest
    // bar was full height in every chart — a distribution spread over a wide range and one
    // concentrated in a single bin drew the same picture, which is the one thing this chart
    // exists to tell apart.
    const page = makePage();
    await page.ngOnInit();

    const flat = page['plot'](section([0.2, 0.2, 0.2, 0.2, 0.2]));
    const peaked = page['plot'](section([0.02, 0.06, 0.84, 0.06, 0.02]));

    // The flat chart tops out at 20% of a 20% axis: full height. The peaked one is 84% of a
    // 100% axis. Under the old rule both would have been full height.
    const tallest = (p: typeof flat) => Math.max(...p.bars.map((b) => b.height));
    expect(tallest(flat)).toBeCloseTo(flat.bottom - flat.top, 5);
    expect(tallest(peaked)).toBeLessThan(peaked.bottom - peaked.top);
    expect(peaked.yTicks.at(-1)!.label).toBe('100%');
    expect(flat.yTicks.at(-1)!.label).toBe('20%');
  });

  it('anchors every bar to the baseline and keeps them inside the plot', () => {
    const page = makePage();
    const chart = page['plot'](section([0.1, 0.3, 0.05, 0.0]));

    for (const bar of chart.bars) {
      expect(bar.y + bar.height).toBeCloseTo(chart.bottom, 5);
      expect(bar.y).toBeGreaterThanOrEqual(chart.top - 0.001);
      expect(bar.x).toBeGreaterThanOrEqual(chart.left);
      expect(bar.x + bar.width).toBeLessThanOrEqual(chart.right + 0.001);
    }
    // A zero-probability bin draws nothing, so "impossible" does not look like "unlikely".
    expect(chart.bars.at(-1)!.height).toBe(0);
  });

  it('labels the x axis on bin edges, ending at the last bin high', () => {
    // A tick in the middle of a bar names a number no boundary has. The final edge is the one
    // no bin starts at, which is why it is taken from `high` rather than from another `low`.
    const page = makePage();
    const chart = page['plot'](section([0.25, 0.25, 0.25, 0.25]));

    expect(chart.xTicks.map((tick) => tick.label)).toEqual(['0', '20', '40']);
    expect(chart.xTicks[0].x).toBe(chart.left);
    expect(chart.xTicks.at(-1)!.x).toBeCloseTo(chart.right, 5);
  });

  it('leaves a gap between neighbouring bars', () => {
    // Contiguous fills read as one block and the eye cannot count them.
    const page = makePage();
    const chart = page['plot'](section([0.5, 0.5]));

    expect(chart.bars[1].x - (chart.bars[0].x + chart.bars[0].width)).toBeCloseTo(2, 5);
  });
});

describe('crafting help is one pick per class', () => {
  it('replaces the pick within a class, across both columns', async () => {
    // **Bonus and refund are alternatives, not additions.** Only one character crafts a given
    // batch, so `craft_multiplier` takes the best and never stacks — a grid of checkboxes said
    // otherwise, and a control implying an interaction the game does not have misinforms.
    const page = makePage();
    await page.ngOnInit();

    page['pickCraft']('weapon_ascension', 'albedo');
    expect(page['crafterFor']('weapon_ascension')).toBe('albedo');

    // A refund, in the other column of the same class, replaces it rather than joining it.
    page['pickCraft']('weapon_ascension', 'mona');

    expect(page['crafterFor']('weapon_ascension')).toBe('mona');
    expect(page['selectedBonusIds']()).toEqual(['mona']);
  });

  it('keeps the two classes independent', async () => {
    // Weapon materials and talent books are separate batches, so Albedo can craft one while
    // Eula crafts the other. One pick overall would have made that unexpressible.
    const page = makePage();
    await page.ngOnInit();

    page['pickCraft']('weapon_ascension', 'albedo');
    page['pickCraft']('talent', 'eula');

    expect(page['selectedBonusIds']().sort()).toEqual(['albedo', 'eula']);
  });

  it('sends a character naming both classes once', async () => {
    // Sucrose doubles either and Dori refunds either. The backend filters each bonus by class,
    // so one id applies to both — sending it twice would say nothing new.
    const page = makePage();
    await page.ngOnInit();

    page['pickCraft']('weapon_ascension', 'sucrose');
    page['pickCraft']('talent', 'sucrose');

    expect(page['selectedBonusIds']()).toEqual(['sucrose']);
  });

  it('can go back to nobody', async () => {
    // A radio cannot be unchecked by clicking it, so "No one" is an option rather than an
    // absence. Without it the first pick would be permanent.
    const page = makePage();
    await page.ngOnInit();
    page['pickCraft']('talent', 'eula');

    page['pickCraft']('talent', null);

    expect(page['crafterFor']('talent')).toBeNull();
    expect(page['selectedBonusIds']()).toEqual([]);
  });
});
