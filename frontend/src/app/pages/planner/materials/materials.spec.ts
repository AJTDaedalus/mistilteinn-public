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
          materials: vi.fn(async () => ({ items: ITEMS, owned_count: 2 })),
          saveMaterials: vi.fn(async () => []),
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
    const saveMaterials = vi.fn(async () => [
      item({ material_id: TEACHINGS, name: 'Teachings of Ballad', count: 12 }),
    ]);
    const tab = makeTab({ saveMaterials });
    await tab.ngOnInit();

    tab['setCount'](TEACHINGS, 12);
    await tab['save']();

    expect(saveMaterials).toHaveBeenCalledWith([{ material_id: TEACHINGS, count: 12 }]);
  });

  it('does not count a row edited back to its original value as a change', async () => {
    const saveMaterials = vi.fn(async () => []);
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
    const saveMaterials = vi.fn(async () => [
      item({ material_id: TEACHINGS, name: 'Teachings of Ballad', count: 999 }),
    ]);
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

  it('caps how many rows it draws, and says how many it is holding back', async () => {
    // Found by looking: every row rendered made the page 25,349 pixels tall against the
    // owner's real inventory. No test measures a page's height, so this one pins the cap and
    // the sentence that keeps the hidden rows honest.
    const many = Array.from({ length: 300 }, (_, index) =>
      item({ material_id: 200000 + index, name: `Material ${index}`, count: 1 }),
    );
    const tab = makeTab({
      materials: vi.fn(async () => ({ items: many, owned_count: 300 })),
    });
    await tab.ngOnInit();

    expect(tab['matching']()).toHaveLength(300);
    expect(tab['visible']()).toHaveLength(80);
    expect(tab['hidden']()).toBe(220);
  });

  it('keeps an edited row visible even when the cap would drop it', async () => {
    // A count typed and then searched past would otherwise vanish from the table while still
    // counting toward Save — the user would be saving something they cannot see.
    const many = Array.from({ length: 300 }, (_, index) =>
      item({ material_id: 200000 + index, name: `Material ${index}`, count: 1 }),
    );
    const tab = makeTab({
      materials: vi.fn(async () => ({ items: many, owned_count: 300 })),
    });
    await tab.ngOnInit();

    const farDown = many[250].material_id;
    tab['setCount'](farDown, 9);

    expect(tab['visible']().some((row) => row.item.material_id === farDown)).toBe(true);
    expect(tab['dirty']()).toHaveLength(1);
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

  it('says so when the list cannot be loaded', async () => {
    const tab = makeTab({ materials: vi.fn(async () => { throw new Error('nope'); }) });
    await tab.ngOnInit();

    expect(tab['error']()).toBeTruthy();
    expect(tab['loading']()).toBe(false);
  });
});
