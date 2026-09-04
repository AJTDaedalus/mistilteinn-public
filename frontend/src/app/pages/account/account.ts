import { Component, type OnInit, computed, inject, signal } from '@angular/core';

import { AuthService } from '../../api/auth.service';
import { allPages } from '../../api/all-pages';
import { CardPicker } from '../../shared/card-picker/card-picker';
import { characterCardFilters, characterCardOptions } from '../../shared/character-cards';
import { CatalogueIcon } from '../../shared/icon/icon';
import { CatalogueService, type CharacterSummary } from '../catalogue/catalogue.service';

/**
 * The account page — `DESIGN_user_avatar.md` §5.
 *
 * The app had no account surface at all: the header chip's only affordance was *Sign out*, and
 * the only place your own email appeared was inside it, truncated at 16 characters. This is
 * where the avatar is chosen, and where the next account fact goes when there is one.
 *
 * ## Every character, not only the ones you own
 *
 * Owner ruling. An avatar is decoration, and gating it on the roster hands a new user — who has
 * not imported a GOOD export yet — an empty grid on the one page whose whole purpose is
 * choosing something from a grid.
 *
 * ## Failing to load the catalogue costs the picker, not the page
 *
 * The email, the status and the current avatar all come from `AuthService.me()`, which is
 * already in memory. So a dead catalogue request leaves the page standing and says the picker
 * is unavailable, rather than replacing an account page with an error.
 */
@Component({
  selector: 'app-account',
  standalone: true,
  imports: [CardPicker, CatalogueIcon],
  templateUrl: './account.html',
  styleUrl: './account.scss',
})
export class AccountPage implements OnInit {
  private readonly catalogue = inject(CatalogueService);
  protected readonly auth = inject(AuthService);

  protected readonly characters = signal<CharacterSummary[]>([]);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  /** The picker could not be filled. Distinct from a save that failed. */
  protected readonly catalogueError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);

  protected readonly avatar = computed(() => this.auth.me()?.avatar ?? null);
  protected readonly selected = computed(() => {
    const chosen = this.avatar();
    return chosen ? [chosen.character_id] : [];
  });

  /**
   * The grid — `shared/character-cards`, the same builder the build editor uses.
   *
   * These were a verbatim copy of that page's private versions, which is the shape
   * `CLAUDE.md` names: a pattern nothing owned, so every page decided separately.
   */
  protected readonly characterOptions = computed(() => characterCardOptions(this.characters()));

  protected readonly characterFilters = computed(() => characterCardFilters(this.characters()));

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.catalogueError.set(null);
    try {
      // Every character, not the first page: 150 today against a page cap of 200, so a
      // single request is right until the patch that makes it silently drop the newest
      // characters — which are exactly the ones somebody opens a picker to find.
      const characters = await allPages((offset, limit) =>
        this.catalogue.listCharacters({ offset, limit }),
      );
      this.characters.set(characters.items as CharacterSummary[]);
    } catch {
      this.catalogueError.set('Could not load the character list.');
      this.characters.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Save a pick, or a clear.
   *
   * The picker emits an array because it can be multi-select; this one is not, so an empty
   * array is the *Clear* button and the first entry is the choice.
   */
  protected async pick(values: string[]): Promise<void> {
    const characterId = values[0] ?? null;
    if (characterId === (this.avatar()?.character_id ?? null)) return;

    this.saving.set(true);
    this.saveError.set(null);
    try {
      await this.auth.setAvatar(characterId);
    } catch {
      // Said out loud. `AuthService.setAvatar` leaves `me` untouched when the request fails,
      // so the page silently keeps showing the old avatar — which looks exactly like a save
      // that worked and picked the wrong one.
      this.saveError.set('Could not save your avatar.');
    } finally {
      this.saving.set(false);
    }
  }
}
