import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { SuiteRow, TeapotRead } from './teapot.service';
import { TeapotService } from './teapot.service';
import { TeapotPage } from './teapot';

const suite = (over: Partial<SuiteRow> = {}): SuiteRow => ({
  suite_id: 's1', name: 'Adventurer Camp', icon: '', placement: 'O',
  owned_favorites: ['a'], unowned_favorites: [], done: false,
  remaining: 1, remaining_primogems: null,
  ...over,
} as SuiteRow);

const read = (over: Partial<TeapotRead> = {}): TeapotRead => ({
  suites: [suite()], reward_per_character: null, ...over,
} as TeapotRead);

describe('TeapotPage', () => {
  let fixture: ComponentFixture<TeapotPage>;
  let suites: ReturnType<typeof vi.fn>;
  let setDone: ReturnType<typeof vi.fn>;

  async function build(): Promise<void> {
    fixture = TestBed.createComponent(TeapotPage);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    suites = vi.fn().mockResolvedValue(read());
    setDone = vi.fn().mockResolvedValue(undefined);
    await TestBed.configureTestingModule({
      imports: [TeapotPage],
      providers: [{ provide: TeapotService, useValue: { suites, setDone } }],
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

  it('ticks a set off', async () => {
    await build();
    fixture.nativeElement.querySelector('.teapot__tick input').click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(setDone).toHaveBeenCalledWith('s1', true);
    expect(fixture.nativeElement.querySelector('.teapot__row--done')).toBeTruthy();
  });

  it('puts the tick back when the write fails', async () => {
    // Optimistic, because a round trip per click would feel broken — but silently keeping a
    // tick the server refused would be worse.
    setDone.mockRejectedValue(new Error('nope'));
    await build();

    fixture.nativeElement.querySelector('.teapot__tick input').click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.teapot__row--done')).toBeFalsy();
    expect(fixture.nativeElement.querySelector('.error')).toBeTruthy();
  });

  it('hides sets nobody on your roster favours, by default', async () => {
    suites.mockResolvedValue(read({
      suites: [suite(), suite({
        suite_id: 's2', name: 'Nobody Wants This',
        owned_favorites: [], unowned_favorites: ['x'], remaining: 0,
      })],
    }));
    await build();

    expect(fixture.nativeElement.textContent).not.toContain('Nobody Wants This');
  });

  it('shows them when asked', async () => {
    suites.mockResolvedValue(read({
      suites: [suite({
        suite_id: 's2', name: 'Nobody Wants This',
        owned_favorites: [], unowned_favorites: ['x'], remaining: 0,
      })],
    }));
    await build();

    fixture.nativeElement.querySelectorAll('.teapot__filters input')[1].click();
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Nobody Wants This');
  });

  it('keeps a finished set visible so a tick can be undone', async () => {
    suites.mockResolvedValue(read({ suites: [suite({ done: true, remaining: 0 })] }));
    await build();

    expect(fixture.nativeElement.textContent).toContain('Adventurer Camp');
    expect(fixture.nativeElement.querySelector('.teapot__row--done')).toBeTruthy();
  });

  it('says how many characters favour a set that you do not have', async () => {
    // Why a set can be worth less than its favourite count suggests. Hiding it would make
    // the tracker look wrong.
    suites.mockResolvedValue(read({
      suites: [suite({ unowned_favorites: ['x', 'y'] })],
    }));
    await build();

    expect(fixture.nativeElement.textContent).toContain("2 you don't have");
  });
});
