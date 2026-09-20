import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { PlannerService, type MaterialStockRead } from '../planner.service';
import { PlannerMaterials } from './materials';

const TEACHINGS = 104301;
const SLIVER = 104161;
/** Sakura Bloom. **Rarity 0 is unranked, not worst** — a local specialty, and a real cost. */
const SPECIALTY = 101202;

function item(over: Partial<MaterialStockRead> & { material_id: number }): MaterialStockRead {
  return {
    name: 'Something',
    icon: 'UI_ItemIcon_1',
    rarity: 2,
    count: 0,
    ...over,
  } as MaterialStockRead;
}

const ITEMS = [
  item({ material_id: TEACHINGS, name: 'Teachings of Ballad', count: 40 }),
  item({ material_id: SLIVER, name: 'Shivada Jade Sliver', count: 3 }),
  item({ material_id: SPECIALTY, name: 'Sakura Bloom', rarity: 0, count: 0 }),
];

function makeTab(planner: Partial<PlannerService> = {}): PlannerMaterials {
  TestBed.configureTestingModule({
    providers: [
      {
        provide: PlannerService,
        useValue: {
          materials: vi.fn(async () => ({ items: ITEMS, owned_count: 2, mora: null })),
          saveMaterials: vi.fn(async () => ({ items: [] })),
          saveMora: vi.fn(async () => ({ items: [], mora: null })),
          ...planner,
        },
      },
    ],
  });
  return TestBed.runInInjectionContext(() => new PlannerMaterials());
}

describe('the materials tab', () => {
  it('shows every material, including the ones you hold none of', async () => {
    // The case this page was asked for is *the import missed something*, so the row worth
    // typing into is usually the one with no count. Hiding it would hide the point.
    const tab = makeTab();
    await tab.ngOnInit();

    expect(tab['visible']()).toHaveLength(3);
    expect(tab['ownedCount']()).toBe(2);
  });

  it('narrows to a search term', async () => {
    const tab = makeTab();
    await tab.ngOnInit();

    tab['search'].set('sakura');

    expect(tab['visible']().map((row) => row.item.material_id)).toEqual([SPECIALTY]);
  });

  it('hides unowned rows only when asked, and the toggle starts off', async () => {
    const tab = makeTab();
    await tab.ngOnInit();

    expect(tab['ownedOnly']()).toBe(false);
    tab['ownedOnly'].set(true);

    expect(tab['visible']().map((row) => row.item.material_id)).toEqual([TEACHINGS, SLIVER]);
  });

  it('sends only the rows that changed', async () => {
    // Asserted on the request body rather than the rendered table: a save that quietly sent
    // all 514 rows would look identical on screen, and would overwrite counts the user never
    // touched with whatever the page happened to be holding.
    const saveMaterials = vi.fn(async () => ({
      items: [item({ material_id: TEACHINGS, name: 'Teachings of Ballad', count: 12 })],
    }));
    const tab = makeTab({ saveMaterials });
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, 12);
    await tab['save']();

    expect(saveMaterials).toHaveBeenCalledWith([{ material_id: TEACHINGS, count: 12 }]);
  });

  it('does not count a row edited back to its original value as a change', async () => {
    const saveMaterials = vi.fn(async () => ({ items: [] }));
    const tab = makeTab({ saveMaterials });
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, 12);
    expect(tab['dirty']()).toHaveLength(1);

    tab['setCount'](TEACHINGS, 40);

    expect(tab['dirty']()).toHaveLength(0);
    await tab['save']();
    expect(saveMaterials).not.toHaveBeenCalled();
  });

  it('reconciles from the response, not from what it sent', async () => {
    // The server is what the planner will read. Echoing our own numbers back into the table
    // would show a save that had not happened if it ever wrote something different.
    const saveMaterials = vi.fn(async () => ({
      items: [item({ material_id: TEACHINGS, name: 'Teachings of Ballad', count: 999 })],
    }));
    const tab = makeTab({ saveMaterials });
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, 12);
    await tab['save']();

    const row = tab['rows']().find((entry) => entry.item.material_id === TEACHINGS);
    expect(row?.item.count).toBe(999);
    expect(row?.edited).toBeNull();
    expect(tab['dirty']()).toHaveLength(0);
  });

  it('keeps the edits and says so when a save fails', async () => {
    // Clearing them would discard the user's typing on the one page whose whole job is not
    // to discard it.
    const tab = makeTab({
      saveMaterials: vi.fn(async () => { throw new Error('nope'); }),
    });
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, 12);
    await tab['save']();

    expect(tab['error']()).toBeTruthy();
    expect(tab['dirty']()).toHaveLength(1);
  });

  it('refuses a negative entry rather than sending it', async () => {
    const tab = makeTab();
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, -5);

    expect(tab['dirty']()).toHaveLength(0);
    expect(tab['value'](tab['rows']()[0])).toBe(40);
  });

  it('draws every matching row — the list scrolls, it is not capped', async () => {
    // Owner, 2026-09-20: *"scroll the 514"*. An earlier version capped this at 80 because
    // rendering every row made the page 25,349 pixels tall against a real inventory. The
    // height was the complaint; the cap was the wrong fix, since it hid rows behind a search
    // term the user had to guess. The table scrolls in its own box now, so this asserts that
    // nothing is held back.
    const many = Array.from({ length: 514 }, (_, index) =>
      item({ material_id: 200000 + index, name: `Material ${index}`, count: 1 }),
    );
    const tab = makeTab({
      materials: vi.fn(async () => ({ items: many, owned_count: 514 })),
    });
    await tab.ngOnInit();

    expect(tab['visible']()).toHaveLength(514);
  });

  it('still narrows to a search across a full-size list', async () => {
    const many = Array.from({ length: 514 }, (_, index) =>
      item({ material_id: 200000 + index, name: `Material ${index}`, count: 1 }),
    );
    const tab = makeTab({
      materials: vi.fn(async () => ({ items: many, owned_count: 514 })),
    });
    await tab.ngOnInit();

    tab['search'].set('material 51');

    // 51, 510-513, and 51x for x in 4..9 are absent above 513 — the point is that a search
    // still filters rather than that the count is memorable.
    expect(tab['visible']().length).toBeLessThan(514);
    expect(tab['visible']().every((row) => row.item.name.includes('51'))).toBe(true);
  });

  it('treats an emptied box as untouched, not as zero', async () => {
    // `Number('')` is 0. Selecting a field and deleting it to start typing would otherwise
    // say "I hold none of this" for that instant — and save it on a click away.
    const tab = makeTab();
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, '');

    expect(tab['dirty']()).toHaveLength(0);
    expect(tab['value'](tab['rows']()[0])).toBe(40);
  });

  it('filters to the materials the current plan needs', async () => {
    // OQ-M3: the plan response already names them, so this costs a Set. It is the fastest
    // route from "this bill looks wrong" to the rows that are wrong, and unlike the search
    // it does not need the user to remember what a material is called.
    const tab = makeTab();
    await tab.ngOnInit();
    // `planMaterialIds` is a signal input, and this component is built by hand rather than
    // through a fixture, so there is no `setInput`. A signal is a function, so standing one
    // in works — and the assertions below fail if `visible()` stops consulting it.
    (tab as unknown as { planMaterialIds: () => number[] }).planMaterialIds = () => [SLIVER];

    expect(tab['hasPlan']()).toBe(true);
    tab['planOnly'].set(true);

    expect(tab['visible']().map((row) => row.item.material_id)).toEqual([SLIVER]);
  });

  it('hides the plan filter when nothing has been priced', async () => {
    // A filter that is always there and usually does nothing teaches you to ignore it.
    const tab = makeTab();
    await tab.ngOnInit();

    expect(tab['hasPlan']()).toBe(false);
  });

  it('records a mora balance as one change, saved on its own call', async () => {
    // `saveMaterials` never sends the mora key, because omitting it and sending null mean
    // different things to the route — leave it alone, and unsay it.
    const saveMora = vi.fn(async () => ({ items: [], mora: 4_210_000 }));
    const saveMaterials = vi.fn(async () => ({ items: [] }));
    const tab = makeTab({ saveMora, saveMaterials });
    await tab.ngOnInit();

    tab['setMora'](4_210_000);
    expect(tab['moraDirty']()).toBe(true);
    expect(tab['changeCount']()).toBe(1);

    await tab['save']();

    expect(saveMora).toHaveBeenCalledWith(4_210_000);
    expect(saveMaterials).not.toHaveBeenCalled();
    expect(tab['moraDirty']()).toBe(false);
  });

  it('treats an emptied mora box as unsaid, where an emptied count is untouched', async () => {
    // The one place emptiness is not "untouched": a material you hold none of is absent from
    // the export anyway, but a mora balance you never gave is a state the planner reports
    // differently from zero — it refuses to compute a shortfall at all.
    const saveMora = vi.fn(async () => ({ items: [], mora: null }));
    const tab = makeTab({
      saveMora,
      materials: vi.fn(async () => ({ items: ITEMS, owned_count: 2, mora: 500 })),
    });
    await tab.ngOnInit();

    tab['setMora']('');
    expect(tab['moraValue']()).toBeNull();
    await tab['save']();

    expect(saveMora).toHaveBeenCalledWith(null);
  });

  it('says so when the list cannot be loaded', async () => {
    const tab = makeTab({ materials: vi.fn(async () => { throw new Error('nope'); }) });
    await tab.ngOnInit();

    expect(tab['error']()).toBeTruthy();
    expect(tab['loading']()).toBe(false);
  });
});
