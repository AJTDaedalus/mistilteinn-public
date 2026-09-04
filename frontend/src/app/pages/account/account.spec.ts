import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { signal } from '@angular/core';

import { AccountPage } from './account';
import { AuthService } from '../../api/auth.service';
import { CardPicker } from '../../shared/card-picker/card-picker';
import { CatalogueService } from '../catalogue/catalogue.service';

const AYAKA = {
  id: 'char-1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka',
  element: 'Cryo', element_icon: null, weapon_type: 'Sword',
  weapon_type_display: 'Sword', weapon_type_icon: null,
};

const me = (avatar: unknown = null) => ({
  email: 'owner@example.com', label: 'Owner', status: 'approved', avatar,
});

/**
 * The account page.
 *
 * The interesting assertions are the two states nobody thinks to draw: an account that has
 * picked nobody, and a catalogue request that failed. Both look like a broken page if they
 * render as blank space.
 */
describe('AccountPage', () => {
  let fixture: ComponentFixture<AccountPage>;
  let setAvatar: ReturnType<typeof vi.fn>;
  let listCharacters: ReturnType<typeof vi.fn>;

  async function build(avatar: unknown = null): Promise<void> {
    await TestBed.configureTestingModule({
      imports: [AccountPage],
      providers: [
        { provide: AuthService, useValue: { me: signal(me(avatar)), setAvatar } },
        { provide: CatalogueService, useValue: { listCharacters } },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(AccountPage);
    fixture.detectChanges();
    await settle();
  }

  /**
   * Let `ngOnInit`'s promise chain finish before asserting.
   *
   * `whenStable()` alone is not enough here: a bare promise is not a task the zoneless
   * scheduler tracks, so it resolves while the page is still on "Loading characters…" — and
   * every assertion about the picker then fails against a picker that does not exist yet. A
   * macrotask drains the microtask queue behind it.
   */
  async function settle(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await fixture.whenStable();
    fixture.detectChanges();
  }

  /** Emit from the real picker rather than calling the handler: the binding is the thing. */
  function choose(values: string[]): void {
    fixture.debugElement.query(By.directive(CardPicker))
      .componentInstance.selectedChange.emit(values);
  }

  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';

  beforeEach(() => {
    setAvatar = vi.fn().mockResolvedValue(undefined);
    listCharacters = vi.fn().mockResolvedValue({ items: [AYAKA], total: 1 });
    TestBed.resetTestingModule();
  });

  it('shows the account it belongs to', async () => {
    // The only place the app named your own email was the header chip, truncated at 16
    // characters. `owner@example.com` did not fit in it.
    await build();

    expect(text()).toContain('owner@example.com');
  });

  it('says nobody has been picked rather than leaving the slot empty', async () => {
    // An empty box beside a picker reads as a picture that failed to load.
    await build();

    expect(text()).toContain('Nobody yet');
  });

  it('names and draws the chosen character', async () => {
    await build({ character_id: 'char-1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka' });

    expect(text()).toContain('Kamisato Ayaka');
    expect(fixture.nativeElement.querySelector('img')?.getAttribute('src'))
      .toBe('/icons/UI_AvatarIcon_Ayaka.webp');
  });

  it('offers the whole catalogue, not only what you own', async () => {
    // Owner ruling: an avatar is decoration, and a roster gate hands a user who has not
    // imported yet an empty grid on the one page that exists to pick from a grid.
    await build();
    const picker = fixture.debugElement.query(By.directive(CardPicker)).componentInstance;

    expect(picker.options().map((o: { value: string }) => o.value)).toEqual(['char-1']);
  });

  it('saves the pick', async () => {
    await build();

    choose(['char-1']);

    expect(setAvatar).toHaveBeenCalledWith('char-1');
  });

  it('saves a clear as null', async () => {
    await build({ character_id: 'char-1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka' });

    choose([]);

    expect(setAvatar).toHaveBeenCalledWith(null);
  });

  it('does not re-save the character already chosen', async () => {
    // The picker emits on every confirm, including one that changed nothing. A write per
    // click is a write that can fail for no reason the user caused.
    await build({ character_id: 'char-1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka' });

    choose(['char-1']);

    expect(setAvatar).not.toHaveBeenCalled();
  });

  it('keeps the page when the catalogue will not load, and offers a retry', async () => {
    // The picker is what broke. The email, the status and the current avatar are already in
    // memory, and replacing an account page with an error message loses all three.
    listCharacters.mockRejectedValue(new Error('nope'));
    await build({ character_id: 'char-1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka' });

    expect(text()).toContain('Could not load the character list.');
    expect(text()).toContain('owner@example.com');
    expect(text()).toContain('Kamisato Ayaka');
  });

  it('says so when the save fails', async () => {
    // `setAvatar` leaves `me` untouched on failure, so the page goes on showing the old
    // avatar — which is indistinguishable from a save that worked and picked the wrong one.
    setAvatar.mockRejectedValue(new Error('nope'));
    await build();

    choose(['char-1']);
    await settle();

    expect(text()).toContain('Could not save your avatar.');
  });
});
