import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { SuiteRow, TeapotRead } from './teapot.service';
import { CatalogueService } from '../catalogue/catalogue.service';
import { TeapotService } from './teapot.service';
import { TeapotPage } from './teapot';

const suite = (over: Partial<SuiteRow> = {}): SuiteRow => ({
  suite_id: 's1', nanoka_id: '1', name: 'Adventurer Camp',
  icon: 'UI_Home_Suite_Camp_01', placement: 'O',
  available: ['a'], completed: [], unowned: [], built: false, done: false,
  remaining: 1, remaining_primogems: null,
  ...over,
} as SuiteRow);

const read = (over: Partial<TeapotRead> = {}): TeapotRead => ({
  suites: [suite()], reward_per_character: null, ...over,
} as TeapotRead);

describe('TeapotPage', () => {
  let fixture: ComponentFixture<TeapotPage>;
  let suites: ReturnType<typeof vi.fn>;
  let setInvited: ReturnType<typeof vi.fn>;
  let setBuilt: ReturnType<typeof vi.fn>;

  async function build(): Promise<void> {
    fixture = TestBed.createComponent(TeapotPage);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    suites = vi.fn().mockResolvedValue(read());
    setInvited = vi.fn().mockResolvedValue(undefined);
    setBuilt = vi.fn().mockResolvedValue(undefined);
    await TestBed.configureTestingModule({
      imports: [TeapotPage],
      providers: [
        { provide: TeapotService, useValue: { suites, setInvited, setBuilt } },
        {
          provide: CatalogueService,
          useValue: {
            listCharacters: vi.fn().mockResolvedValue({
              items: [{ nanoka_id: 'a', name: 'Noelle', icon: 'UI_AvatarIcon_Noelle' }],
            }),
          },
        },
      ],
    }).compileComponents();
  });

  it('lists the sets', async () => {
    await build();

    expect(fixture.nativeElement.textContent).toContain('Adventurer Camp');
  });

  it('says how many characters are still to invite', async () => {
    await build();

    expect(fixture.nativeElement.textContent).toContain('1 to invite');
  });

  it('shows the primos still available', async () => {
    suites.mockResolvedValue(read({
      suites: [suite({ remaining: 2, remaining_primogems: 40 })],
      reward_per_character: 20,
    }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('40');
    expect(fixture.nativeElement.textContent).toContain('primos available');
  });

  it('explains a missing reward rather than showing a blank', async () => {
    // The endpoint is allowed to say it does not know, and a blank column nobody can explain
    // reads as a bug.
    await build();

    expect(fixture.nativeElement.textContent).toContain('no reward figure');
  });

  it('takes the reward from the server rather than restating it', async () => {
    // A second copy of a game constant is the one that drifts when a patch changes it.
    suites.mockResolvedValue(read({
      suites: [suite({ remaining: 1, remaining_primogems: 99 })],
      reward_per_character: 99,
    }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('99');
  });

  it('ticks one character, not the whole set', async () => {
    // The reward is per character per set, so the tick belongs on the character.
    await build();
    fixture.nativeElement.querySelector('.chip--available input').click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(setInvited).toHaveBeenCalledWith('s1', 'a', true);
    expect(fixture.nativeElement.querySelector('.chip--completed')).toBeTruthy();
  });

  it('leaves the other favouring characters still owed', async () => {
    // **The bug the per-set model had.** Two owned favourites is two rewards.
    suites.mockResolvedValue(read({
      suites: [suite({ available: ['a', 'b'], remaining: 2, remaining_primogems: 40 })],
      reward_per_character: 20,
    }));
    await build();

    fixture.nativeElement.querySelector('.chip--available input').click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelectorAll('.chip--available').length).toBe(1);
    expect(fixture.nativeElement.querySelector('.teapot__row--done')).toBeFalsy();
    expect(fixture.nativeElement.textContent).toContain('20 primos');
  });

  it('puts the tick back when the write fails', async () => {
    // Optimistic, because a round trip per click would feel broken — but silently keeping a
    // tick the server refused would be worse.
    setInvited.mockRejectedValue(new Error('nope'));
    await build();

    fixture.nativeElement.querySelector('.chip--available input').click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.chip--completed')).toBeFalsy();
    expect(fixture.nativeElement.querySelector('.error')).toBeTruthy();
  });

  it('shows all three states, told apart by more than colour', async () => {
    suites.mockResolvedValue(read({
      suites: [suite({ available: ['a'], completed: ['b'], unowned: ['c'] })],
    }));
    await build();

    expect(fixture.nativeElement.querySelector('.chip--available input')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.chip--completed input')).toBeTruthy();
    // An unowned character has no control at all — there is nothing to tick.
    expect(fixture.nativeElement.querySelector('.chip--unowned input')).toBeFalsy();
  });

  it("shows the set's own picture", async () => {
    await build();

    const art: HTMLImageElement =
      fixture.nativeElement.querySelector('.teapot__art img');
    expect(art?.getAttribute('src')).toContain('UI_Home_Suite_Camp_01');
  });

  it('puts a face on each character chip', async () => {
    await build();

    const face: HTMLImageElement =
      fixture.nativeElement.querySelector('.chip__face img');
    expect(face?.getAttribute('src')).toContain('UI_AvatarIcon_Noelle');
  });

  it('still names a character whose art the catalogue lacks', async () => {
    // A row with no icon is a seeding gap, not an error — the name has to survive it.
    suites.mockResolvedValue(read({ suites: [suite({ available: ['zzz'] })] }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('zzz');
  });

  it('names a character rather than showing its id', async () => {
    await build();

    expect(fixture.nativeElement.textContent).toContain('Noelle');
  });

  it('asks for a page size the endpoint actually allows', async () => {
    // **`limit` is capped at 200.** Asking for 500 is a 422, which `loadNames` swallows — so
    // every chip silently read as a nanoka id and nothing said why. Found on screen.
    await build();

    const [[query]] = (
      TestBed.inject(CatalogueService).listCharacters as ReturnType<typeof vi.fn>
    ).mock.calls;
    expect(query.limit).toBeLessThanOrEqual(200);
  });

  it('falls back to the id when a name is unknown', async () => {
    // A suite can favour a character this database has not seeded. An id is a worse label
    // than a name and a much better one than an empty chip.
    suites.mockResolvedValue(read({ suites: [suite({ available: ['zzz'] })] }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('zzz');
  });

  it('lists a set nobody on your roster favours', async () => {
    // Owner ruling, 2026-09-06: the tick box that hid these is gone and the hiding went with
    // it. Search has to find every set, so every set is on the page; search and the character
    // chips are what narrow it now.
    suites.mockResolvedValue(read({
      suites: [suite(), suite({
        suite_id: 's2', name: 'Nobody Wants This',
        available: [], completed: [], unowned: ['x'], remaining: 0,
      })],
    }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('Nobody Wants This');
  });

  it('keeps a finished set visible so a tick can be undone', async () => {
    suites.mockResolvedValue(read({
      suites: [suite({ available: [], completed: ['a'], done: true, remaining: 0 })],
    }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('Adventurer Camp');
    expect(fixture.nativeElement.querySelector('.teapot__row--done')).toBeTruthy();
  });

  it('says how many characters favour a set that you do not have', async () => {
    // Why a set can be worth less than its favourite count suggests. Hiding it would make
    // the tracker look wrong.
    suites.mockResolvedValue(read({ suites: [suite({ unowned: ['x', 'y'] })] }));
    await build();

    expect(fixture.nativeElement.querySelectorAll('.chip--unowned').length).toBe(2);
  });
  // ── Finding one set among 109 (#266) ─────────────────────────────────────
  //
  // *"search bar in general lmao, ctrl f to find exactly what i need to keeping track isnt
  // that convenient"*. Ctrl-F is what these replace, so they have to be at least as good as
  // Ctrl-F over the rendered page — which finds a character's name as readily as a set's.

  const ROSTER = read({
    suites: [
      suite({ suite_id: 's1', nanoka_id: '20', name: 'Adventurer Camp',
        placement: 'OG', available: ['a'] }),
      suite({ suite_id: 's2', nanoka_id: '3', name: 'Cool Isle',
        placement: 'IG', available: ['b'] }),
    ],
  });

  async function withRoster(): Promise<void> {
    suites.mockResolvedValue(ROSTER);
    await build();
  }

  it('finds a set by name', async () => {
    await withRoster();

    fixture.componentInstance['search'].set('cool');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Cool Isle');
    expect(fixture.nativeElement.textContent).not.toContain('Adventurer Camp');
  });

  it('finds a set by the name of a character who favours it', async () => {
    // The chips on the row carry these names, so Ctrl-F already found them. A search that
    // matched only the set's name would be a worse Ctrl-F than Ctrl-F.
    await withRoster();

    fixture.componentInstance['search'].set('noelle');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Adventurer Camp');
    expect(fixture.nativeElement.textContent).not.toContain('Cool Isle');
  });

  it('narrows to indoor or outdoor sets on the leading letter, not the whole code', async () => {
    // **Four values, not two.** nanoka spells placement `I`, `IG`, `O` and `OG`, and at
    // 7.0.51 the split is OG 48, IG 31, O 18, I 12 — so an equality match on "I" would offer
    // Indoor and find 12 of the 43 indoor sets. Both fixtures here are the `G` spelling,
    // which is the one an equality match drops.
    await withRoster();

    fixture.componentInstance['placementFilter'].set('I');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Cool Isle');
    expect(fixture.nativeElement.textContent).not.toContain('Adventurer Camp');
  });

  it('says where a set goes for the G spellings too', async () => {
    // The same bug one surface over: `placement()` compared the whole string, so 79 of the
    // 109 rows said nothing at all about where the set goes.
    await withRoster();

    expect(fixture.nativeElement.textContent).toContain('outdoor');
    expect(fixture.nativeElement.textContent).toContain('indoor');
  });

  it('orders by release when asked, numerically', async () => {
    // The ask was *"sort sets by how they appear in-game"*; the source has no field for that,
    // so the control is labelled Release order for what `nanoka_id` actually is. Numeric,
    // because these are "1" … "109" and a string sort puts 100 between 10 and 11.
    await withRoster();

    fixture.componentInstance['sort'].set('release');
    fixture.detectChanges();

    expect(fixture.componentInstance['visible']().map((row) => row.name))
      .toEqual(['Cool Isle', 'Adventurer Camp']);
  });

  it('narrows to the sets a chosen character favours', async () => {
    // Any of the chosen characters, not all: *"show only sets of your selected 3 chars"* is
    // "what should I build for this group", and requiring all three finds nothing.
    await withRoster();

    fixture.componentInstance['toggleCharacter']('a');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Adventurer Camp');
    expect(fixture.nativeElement.textContent).not.toContain('Cool Isle');
  });

  it('offers a character chip only for characters this roster has', async () => {
    // A chip for somebody you do not own can only narrow to sets you cannot claim, so it is
    // a control whose every outcome is an empty list.
    suites.mockResolvedValue(read({
      suites: [suite({ available: ['a'], unowned: ['zzz-not-owned'] })],
    }));
    await build();

    expect(fixture.componentInstance['characterOptions']().map((o) => o.id)).toEqual(['a']);
  });

  it('puts every filter back with one control', async () => {
    await withRoster();
    fixture.componentInstance['search'].set('cool');
    fixture.componentInstance['placementFilter'].set('I');
    fixture.componentInstance['toggleCharacter']('b');
    fixture.componentInstance['sort'].set('release');
    fixture.detectChanges();

    fixture.componentInstance['clearFilters']();
    fixture.detectChanges();

    expect(fixture.componentInstance['filtering']()).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('Adventurer Camp');
    expect(fixture.nativeElement.textContent).toContain('Cool Isle');
  });

  it('offers Clear for a tick box, because Clear resets one', async () => {
    // The two are one control between them: `clearFilters()` put `hideDone` back and
    // `filtering()` did not count it, so the only narrowing a user had applied was the one
    // the button was hidden for.
    await withRoster();

    fixture.componentInstance['hideDone'].set(true);
    fixture.detectChanges();

    expect(fixture.componentInstance['filtering']()).toBe(true);
  });

});


describe('TeapotPage — built is its own axis', () => {
  // Owner: *"it takes time and effort to build them so that's different from the invites."*
  it('marks a set built without inviting anybody', async () => {
    const suites = vi.fn().mockResolvedValue(read());
    const setBuilt = vi.fn().mockResolvedValue(undefined);
    await TestBed.configureTestingModule({
      imports: [TeapotPage],
      providers: [
        {
          provide: TeapotService,
          useValue: { suites, setBuilt, setInvited: vi.fn() },
        },
        {
          provide: CatalogueService,
          useValue: { listCharacters: vi.fn().mockResolvedValue({ items: [] }) },
        },
      ],
    }).compileComponents();
    const fixture = TestBed.createComponent(TeapotPage);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    fixture.nativeElement.querySelector('.teapot__built input').click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(setBuilt).toHaveBeenCalledWith('s1', true);
    // Building it invites nobody, so the reward is untouched.
    expect(fixture.nativeElement.querySelectorAll('.chip--available').length).toBe(1);
  });
});
