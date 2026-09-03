import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { SuiteRow, TeapotRead } from './teapot.service';
import { CatalogueService } from '../catalogue/catalogue.service';
import { TeapotService } from './teapot.service';
import { TeapotPage } from './teapot';

const suite = (over: Partial<SuiteRow> = {}): SuiteRow => ({
  suite_id: 's1', name: 'Adventurer Camp', icon: '', placement: 'O',
  available: ['a'], completed: [], unowned: [], done: false,
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

  async function build(): Promise<void> {
    fixture = TestBed.createComponent(TeapotPage);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    suites = vi.fn().mockResolvedValue(read());
    setInvited = vi.fn().mockResolvedValue(undefined);
    await TestBed.configureTestingModule({
      imports: [TeapotPage],
      providers: [
        { provide: TeapotService, useValue: { suites, setInvited } },
        {
          provide: CatalogueService,
          useValue: {
            listCharacters: vi.fn().mockResolvedValue({
              items: [{ nanoka_id: 'a', name: 'Noelle' }],
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

  it('shows the primogems still on the table', async () => {
    suites.mockResolvedValue(read({
      suites: [suite({ remaining: 2, remaining_primogems: 40 })],
      reward_per_character: 20,
    }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('40');
    expect(fixture.nativeElement.textContent).toContain('primogems still on the table');
  });

  it('explains a missing reward rather than showing a blank', async () => {
    // The endpoint is allowed to say it does not know, and a blank column nobody can explain
    // reads as a bug.
    await build();

    expect(fixture.nativeElement.textContent).toContain('no reward figure');
    expect(fixture.nativeElement.textContent).toContain('order is unaffected');
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

  it('hides sets nobody on your roster favours, by default', async () => {
    suites.mockResolvedValue(read({
      suites: [suite(), suite({
        suite_id: 's2', name: 'Nobody Wants This',
        available: [], completed: [], unowned: ['x'], remaining: 0,
      })],
    }));
    await build();

    expect(fixture.nativeElement.textContent).not.toContain('Nobody Wants This');
  });

  it('shows them when asked', async () => {
    suites.mockResolvedValue(read({
      suites: [suite({
        suite_id: 's2', name: 'Nobody Wants This',
        available: [], completed: [], unowned: ['x'], remaining: 0,
      })],
    }));
    await build();

    fixture.nativeElement.querySelectorAll('.teapot__filters input')[1].click();
    fixture.detectChanges();

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
});
