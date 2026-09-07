import { Component, ElementRef, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../api/api-error';
import { CardPicker, type CardFilter, type CardOption } from '../../shared/card-picker/card-picker';
import { characterCardFilters, characterCardOptions } from '../../shared/character-cards';
import { ElementChip } from '../../shared/element/element';
import { CatalogueIcon } from '../../shared/icon/icon';
import { Combobox, type ComboboxOption } from '../../shared/combobox/combobox';
import { EntityToken } from '../../shared/token/token';
import { KQM_FILTER, listedFirst, weaponCard, weaponsById } from '../../shared/kqm/kqm';
import { allPages } from '../../api/all-pages';
import { ArtifactPanel } from './artifact-panel';
import {
  CatalogueService,
  type CharacterWeaponGuideRead,
} from '../catalogue/catalogue.service';
import {
  BuildsService,
  type BuildFields,
  type BuildRead,
  type CharacterSummary,
  type WeaponSummary,
} from './builds.service';
import { RosterService, type RosterEntry } from './roster.service';

/** What a new build starts as. Matches the server's own defaults, which bound each field. */
function blank(talents: string[]): BuildFields {
  return {
    name: '',
    character_level: 90,
    ascension_phase: 6,
    weapon_level: 90,
    refinement: 1,
    constellation_level: 0,
    talent_levels: Object.fromEntries(talents.map((t) => [t, 1])),
    notes: '',
  };
}

/**
 * The saved-column predicate, as a function rather than a closure inside a `computed`.
 *
 * Exported so it can be tested without standing up a TestBed for a page that had no spec
 * file at all — the same reason `comparator` on the artifacts page is exported.
 *
 * **Characters only, by owner ruling.** It used to search the weapon's name too, on the
 * argument that *"who has Freedom-Sworn"* is as ordinary a question as *"where's Nahida"*. The
 * owner's audit says otherwise, and the reason is visible once the filters are chips: typing
 * "sword" matched every build holding one, so a search for a *character* returned a wall of
 * weapons. The weapon question is a filter, not a search.
 */
export function matchesBuild(
  search: string,
  element: string,
  weaponType = '',
  stars = '',
): (build: {
  character?: {
    name?: string | null; element?: string | null;
    weapon_type?: string | null; stars?: number | null;
  } | null;
}) => boolean {
  const q = search.trim().toLowerCase();
  return (build) => {
    if (element && build.character?.element !== element) return false;
    if (weaponType && build.character?.weapon_type !== weaponType) return false;
    if (stars && String(build.character?.stars ?? '') !== stars) return false;
    if (!q) return true;
    return (build.character?.name ?? '').toLowerCase().includes(q);
  };
}

/**
 * The build editor.
 *
 * A build is a character, a weapon that character can hold, and the levels. The page's job is
 * to make the second clause structural rather than a rule a user has to know: **the weapon
 * list is fetched filtered by the chosen character's weapon class**, server-side, so a
 * selection the API would refuse cannot be made. T.1 refuses a Bow on a Sword character, and
 * a picker offering one would let a user pick it and then be told their own choice is
 * invalid.
 *
 * The talent inputs come from `/builds/options` for the same reason. A hardcoded list here
 * would be a third copy of `LEVELLED_TALENTS` — the first two being the validator and the
 * gcsim renderer, which were themselves one list too many until T.1.
 */
@Component({
  selector: 'page-builds',
  imports: [
    FormsModule, ArtifactPanel, CardPicker, CatalogueIcon, ElementChip, EntityToken, Combobox,
  ],
  templateUrl: './builds.html',
  styleUrl: './builds.scss',
})
export class BuildsPage implements OnInit {
  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no builds". */
  protected readonly error = signal<string | null>(null);
  /** Non-null means one action failed — a save, a delete. */
  protected readonly actionError = signal<string | null>(null);

  protected readonly builds = signal<BuildRead[]>([]);
  protected readonly characters = signal<CharacterSummary[]>([]);
  protected readonly weapons = signal<WeaponSummary[]>([]);
  protected readonly talents = signal<string[]>([]);
  protected readonly maxTalent = signal(15);

  /** The build being edited, or null while composing a new one. */
  /**
   * Narrowing for the saved column.
   *
   * The owner's GOOD export makes **75 builds**, and the column shows about nine at a time
   * with no way to reach a tenth but scrolling. A name match and an element filter are what
   * a player actually has in mind — "where's my Nahida" — and both are one pass over a list
   * the page already holds.
   *
   * Client-side, because the list is already loaded in full and a round trip per keystroke
   * would be slower and no more correct.
   */
  /**
   * Which tab is showing. Owner: *"we need a tab for both so users can change ownership
   * manually if needed."*
   *
   * The two answer different questions and the page had only ever asked one of them: a build
   * says what gear a character has, the roster says whether the account has the character at
   * all. Twelve of the owner's characters had no build — because a build is only made for a
   * character holding gear — and so no way to be counted. `DESIGN_character_roster.md`.
   */
  protected readonly tab = signal<'builds' | 'roster'>('builds');

  protected readonly roster = signal<RosterEntry[]>([]);
  /** Non-null while one toggle is in flight, so the row can show it is saving. */
  protected readonly savingCharacter = signal<string | null>(null);

  protected readonly search = signal('');
  protected readonly elementFilter = signal('');
  protected readonly weaponFilter = signal('');
  protected readonly starsFilter = signal('');

  /**
   * The chips are drawn from the builds on screen, never from the catalogue.
   *
   * A vision nobody has built for is a chip that filters to nothing — a control whose only
   * possible outcome is an empty list. Same for a weapon class and a rarity.
   */
  private facet<T>(
    read: (build: BuildRead) => T | null | undefined,
    icon: (build: BuildRead) => string | null | undefined,
  ): { value: string; icon: string | null }[] {
    const seen = new Map<string, string | null>();
    for (const b of this.builds()) {
      const key = read(b);
      if (key === null || key === undefined || key === '') continue;
      if (!seen.has(String(key))) seen.set(String(key), icon(b) ?? null);
    }
    return [...seen].map(([value, art]) => ({ value, icon: art }))
      .sort((a, b) => a.value.localeCompare(b.value));
  }

  protected readonly elementsPresent = computed(() =>
    this.facet((b) => b.character?.element, (b) => b.character?.element_icon)
      .map(({ value, icon }) => ({ element: value, icon })),
  );

  protected readonly weaponTypesPresent = computed(() =>
    this.facet((b) => b.character?.weapon_type, (b) => b.character?.weapon_type_icon)
      .map(({ value, icon }) => ({
        value,
        icon,
        label: this.builds().find((b) => b.character?.weapon_type === value)
          ?.character?.weapon_type_display ?? value,
      })),
  );

  /** Character rarity, not the weapon's — these cards are character-first. */
  protected readonly starsPresent = computed(() =>
    this.facet((b) => b.character?.stars, () => null)
      .map(({ value }) => value)
      .sort((a, b) => Number(b) - Number(a)),
  );

  protected readonly shownBuilds = computed(() =>
    this.builds().filter(matchesBuild(
      this.search(), this.elementFilter(), this.weaponFilter(), this.starsFilter(),
    )),
  );

  protected readonly ownedCount = computed(
    () => this.roster().filter((entry) => entry.owned === true).length,
  );

  /**
   * The roster tab's rows, through the same search and filters the builds tab uses.
   *
   * Reuses `matchesBuild` by shaping each entry into the `{ character }` it reads — one
   * predicate rather than two that must agree. The chips themselves are still drawn from the
   * builds, which is a known narrowing: a vision nobody has built for offers no chip even
   * though the roster has characters of it. Left alone deliberately — the alternative is
   * chips that change meaning when you switch tabs.
   */
  protected readonly shownRoster = computed(() => {
    const match = matchesBuild(
      this.search(), this.elementFilter(), this.weaponFilter(), this.starsFilter(),
    );
    return this.roster().filter((entry) => match({
      character: {
        name: entry.name,
        element: entry.element,
        weapon_type: entry.weapon_type,
        stars: entry.rarity === 'five_star' ? 5 : entry.rarity === 'four_star' ? 4 : null,
      },
    }));
  });

  /**
   * Characters the account owns and has not built.
   *
   * Shown on the **builds** tab, muted and last — the owner's original request, kept because
   * it is a useful thing for that tab to say: *you have this character and have not built
   * them*. It is a prompt, not an empty row pretending to be a build.
   */
  protected readonly unbuilt = computed(() => {
    const built = new Set(
      this.builds().map((build) => build.character?.id).filter(Boolean) as string[],
    );
    const match = matchesBuild(
      this.search(), this.elementFilter(), this.weaponFilter(), this.starsFilter(),
    );
    return this.roster()
      .filter((entry) => entry.owned === true && !built.has(entry.character_id))
      .filter((entry) => match({
        character: {
          name: entry.name,
          element: entry.element,
          weapon_type: entry.weapon_type,
          stars: entry.rarity === 'five_star' ? 5 : entry.rarity === 'four_star' ? 4 : null,
        },
      }));
  });

  /**
   * The character grid — the same one `/account` draws, built by the same function.
   *
   * It was a private copy here and a verbatim second copy there; `shared/character-cards`
   * carries the rationale for the chips and is now the only place that decides them.
   */
  protected readonly characterOptions = computed(() => characterCardOptions(this.characters()));

  protected readonly characterFilters = computed(() => characterCardFilters(this.characters()));

  /**
   * The weapon grid.
   *
   * **No weapon-class filter here**, because the list is already one class: the server filtered
   * it by the chosen character's, so a chip offering "Bow" on a Sword character would filter to
   * nothing. Rarity is the axis that remains, and it is the one a player narrows by.
   */
  /**
   * What KeqingMains lists for the chosen character, or null when no guide was captured.
   *
   * **Null is not an empty list.** "Nobody has captured this character" and "KQM recommends
   * nothing for them" are different statements, and a card marked *not recommended* on the
   * strength of the first would be a claim about KQM that nobody made.
   */
  protected readonly weaponGuide = signal<CharacterWeaponGuideRead | null>(null);

  /** `weapon id -> what KQM said`, for marking and ordering the picker. */
  private readonly recommended = computed(() => weaponsById(this.weaponGuide()));

  protected readonly weaponOptions = computed<CardOption[]>(() => {
    const listed = this.recommended();
    // **The refinement is not on this line** (owner): it is read off the weapon the user owns,
    // so KQM's `R5` would be somebody else's account's number shown against this user's
    // inventory. `relative_dps` took its place where KQM published one.
    const cards = this.weapons().map((w) => weaponCard(w, listed.get(w.id)));
    // Listed weapons first, in KQM's order; everything else after, as before. A weapon KQM did
    // not list is not thereby *bad* — it is unlisted, which is why the rest keep their order
    // rather than being pushed into a "not recommended" bucket.
    return listedFirst(cards, (card) => listed.get(card.value)?.position);
  });

  protected readonly weaponFilters = computed<CardFilter[]>(() => {
    const listed = this.recommended().size > 0;
    const stars = [...new Set(this.weapons().map((w) => w.stars))]
      .sort((a, b) => b - a)
      .map((s) => ({ value: String(s), label: `${s}★` }));
    const filters: CardFilter[] = [];
    if (listed) {
      // Offered only when there is a guide, for the same reason the chips elsewhere are drawn
      // from what is on screen: a filter whose only outcome is an empty grid is not a filter.
      filters.push(KQM_FILTER);
    }
    if (stars.length > 1) filters.push({ group: 'stars', label: 'Rarity', options: stars });
    return filters;
  });

  protected readonly editing = signal<BuildRead | null>(null);
  protected readonly characterId = signal('');
  protected readonly weaponId = signal<string | null>(null);
  protected fields: BuildFields = blank([]);

  protected readonly character = computed(
    () => this.characters().find((c) => c.id === this.characterId()) ?? null,
  );

  protected readonly canSave = computed(() => this.characterId() !== '');

  /* ── The build ranking ───────────────────────────────────────────────────────
     `BACKLOG_frontend.md` §3, and the reason `optimizer_priority` was on the model with an
     index for months while nothing read it. The ranking answers "who gets the piece" when two
     builds want the same artifact — the optimizer used to refuse outright.

     **A short list, not the grid.** Seventy-five cards are not draggable in any useful sense,
     and a ranking only matters for the handful of characters that actually contend for pieces.
     So the ranking is its own list: add a build to it, drag or nudge it into place. */
  protected readonly ranking = viewChild<ElementRef<HTMLDialogElement>>('ranking');
  protected readonly rankOrder = signal<string[]>([]);
  protected readonly rankError = signal<string | null>(null);
  protected readonly rankSaved = signal(false);

  /** The ranked builds, in rank order, as rows to draw. */
  protected readonly rankedBuilds = computed(() => {
    const byId = new Map(this.builds().map((b) => [b.id, b]));
    return this.rankOrder().map((id) => byId.get(id)).filter((b) => b !== undefined);
  });

  /** Everything not yet ranked, for the picker that adds to the list. */
  protected readonly rankableOptions = computed<ComboboxOption[]>(() => {
    const ranked = new Set(this.rankOrder());
    return this.builds()
      .filter((b) => !ranked.has(b.id))
      .map((b) => ({ value: b.id, label: b.character?.name || 'Unnamed build' }));
  });

  protected openRanking(): void {
    // Seeded from what the server holds, so opening it twice does not show a stale draft.
    this.rankOrder.set(
      this.builds()
        .filter((b) => b.optimizer_priority !== null && b.optimizer_priority !== undefined)
        .sort((a, b) => (a.optimizer_priority ?? 0) - (b.optimizer_priority ?? 0))
        .map((b) => b.id),
    );
    this.rankError.set(null);
    this.rankSaved.set(false);
    this.ranking()?.nativeElement.showModal?.();
  }

  protected closeRanking(): void {
    this.ranking()?.nativeElement.close?.();
  }

  protected addToRanking(buildId: string | null): void {
    if (!buildId || this.rankOrder().includes(buildId)) return;
    this.rankOrder.update((order) => [...order, buildId]);
    this.rankSaved.set(false);
  }

  protected removeFromRanking(buildId: string): void {
    this.rankOrder.update((order) => order.filter((id) => id !== buildId));
    this.rankSaved.set(false);
  }

  /**
   * Move a build one place.
   *
   * **Buttons as well as dragging.** The rotation builder learned this: a drag-only reorder is
   * unusable by keyboard and fiddly with a trackpad, and the buttons are what a test can press.
   */
  protected moveRank(index: number, delta: number): void {
    const target = index + delta;
    const order = this.rankOrder();
    if (target < 0 || target >= order.length) return;
    const next = [...order];
    [next[index], next[target]] = [next[target], next[index]];
    this.rankOrder.set(next);
    this.rankSaved.set(false);
  }

  protected readonly rankDragging = signal<number | null>(null);

  protected onRankDragStart(index: number): void {
    this.rankDragging.set(index);
  }

  protected onRankDrop(index: number): void {
    const from = this.rankDragging();
    this.rankDragging.set(null);
    if (from === null || from === index) return;
    const next = [...this.rankOrder()];
    const [moved] = next.splice(from, 1);
    next.splice(index, 0, moved);
    this.rankOrder.set(next);
    this.rankSaved.set(false);
  }

  protected async saveRanking(): Promise<void> {
    this.rankError.set(null);
    try {
      await this.service.setPriority(this.rankOrder());
      await this.load();
      this.rankSaved.set(true);
    } catch (err) {
      this.rankError.set(apiErrorMessage(err));
    }
  }

  protected readonly editor = viewChild<ElementRef<HTMLDialogElement>>('editor');

  /**
   * Open the editor on a blank build.
   *
   * **`showModal?.()`, deliberately.** `HTMLDialogElement` is absent in jsdom, so a bare call
   * is a `TypeError` thrown from inside a click handler — which takes the page out rather than
   * failing the one control. `CardPicker` learned this from a test and the reasoning is the
   * same here: any browser without `<dialog>` behaves as jsdom does.
   */
  protected startNew(): void {
    this.newBuild();
    this.editor()?.nativeElement.showModal?.();
  }

  protected closeEditor(): void {
    this.editor()?.nativeElement.close?.();
  }

  /**
   * Escape and the backdrop close a native dialog without going through `closeEditor`, so the
   * page's own state is reconciled on the `close` event rather than in the button handler.
   *
   * **`editing` is cleared here**, because it is what draws the brass glow on a card in the
   * list: leaving it set marked a build as being edited while no editor was open, and the
   * highlight then sat there until another card was clicked (#289). Nothing is lost by
   * clearing it — `edit()` refills every field from the build it reopens, so the "resume
   * where you left off" this used to claim was never what happened.
   */
  protected onEditorClosed(): void {
    this.actionError.set(null);
    this.editing.set(null);
  }

  private readonly service = inject(BuildsService);
  private readonly catalogue = inject(CatalogueService);
  private readonly rosterService = inject(RosterService);

  ngOnInit(): void {
    void this.load();
  }

  /**
   * Record the user's own answer about one character.
   *
   * **Optimistic, and reverted on failure.** A checkbox that waits for a round trip before it
   * moves reads as broken, and a checkbox that moves and silently stays moved after the save
   * failed is worse — the user believes a fact the server does not hold. So it flips, and flips
   * back with a message if the write did not land.
   */
  protected async toggleOwned(entry: RosterEntry, owned: boolean): Promise<void> {
    const previous = entry.owned;
    this.savingCharacter.set(entry.character_id);
    this.actionError.set(null);
    this.applyOwned(entry.character_id, owned, 'manual');
    try {
      await this.rosterService.setOwned(entry.character_id, owned);
    } catch {
      this.applyOwned(entry.character_id, previous, entry.source);
      this.actionError.set(`Could not save whether you have ${entry.name}.`);
    } finally {
      this.savingCharacter.set(null);
    }
  }

  private applyOwned(
    characterId: string, owned: boolean | null, source: string | null,
  ): void {
    this.roster.update((entries) => entries.map(
      (entry) => entry.character_id === characterId ? { ...entry, owned, source } : entry,
    ));
  }

  /** Open the editor on a new build for a character the account owns but has not built. */
  protected async buildFor(entry: RosterEntry): Promise<void> {
    this.tab.set('builds');
    this.startNew();
    await this.selectCharacter(entry.character_id);
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [options, builds, characters, roster] = await Promise.all([
        this.service.options(),
        this.service.list(),
        // Every character, not the first page. 150 today against a cap of 200 — so this is
        // latent rather than broken, and the failure when it lands is the worst kind: the
        // picker would quietly lose the *newest* characters, which are exactly the ones
        // someone opens this page to build.
        allPages((offset, limit) => this.catalogue.listCharacters({ offset, limit })),
        // **Not fatal if it fails.** The roster is a second view of this page, and losing it
        // must not take the build editor with it — so it resolves to an empty roster rather
        // than rejecting the whole `Promise.all`.
        this.rosterService.list().catch(() => ({ entries: [], owned_count: 0 })),
      ]);
      this.talents.set(options.talents);
      this.maxTalent.set(options.max_talent_level);
      this.builds.set(builds);
      this.characters.set(characters.items as CharacterSummary[]);
      this.roster.set(roster.entries);
      if (this.editing() === null) this.fields = blank(options.talents);
    } catch {
      // Surfaced, not swallowed: an empty list and a failed request look identical on
      // screen, and only one of them means the account has no builds.
      this.error.set('Could not load the build editor.');
      this.builds.set([]);
      this.characters.set([]);
      this.roster.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Choosing a character reloads the weapon list, filtered **by the server** to that
   * character's class.
   *
   * The filtering is the server's rule, not one re-implemented here. If this page filtered a
   * full list client-side, the two could disagree — and the one that drifted would be the one
   * offering a weapon the API then refuses.
   */
  /**
   * The picker's two handlers.
   *
   * They take the whole array rather than `$event[0] ?? ''` in the template, because a picker
   * that has just been cleared emits `[]` — and Angular's own NG8102 diagnostic calls that
   * `??` redundant, since `string[]` indexing is typed as `string` without
   * `noUncheckedIndexedAccess`. The type is wrong and the guard is not, so the guard moves
   * where the compiler will not argue with it.
   */
  protected pickCharacter(ids: readonly string[]): void {
    void this.selectCharacter(ids[0] ?? '');
  }

  protected pickWeapon(ids: readonly string[]): void {
    this.weaponId.set(ids[0] ?? null);
  }

  protected async selectCharacter(id: string): Promise<void> {
    this.characterId.set(id);
    this.weaponId.set(null);
    this.weapons.set([]);
    this.weaponGuide.set(null);
    const chosen = this.characters().find((c) => c.id === id);
    if (!chosen) return;
    try {
      const page = await allPages((offset, limit) =>
        this.catalogue.listWeapons({ weapon_type: chosen.weapon_type, offset, limit }),
      );
      this.weapons.set(page.items as WeaponSummary[]);
      // Never fatal: the picker works without a guide, and three characters are captured
      // today. A page that failed to open because a recommendation could not be fetched would
      // be worse than one that simply does not mark anything.
      this.weaponGuide.set(await this.catalogue.weaponGuide(chosen.nanoka_id));
    } catch {
      this.actionError.set('Could not load weapons for that character.');
    }
  }

  protected talentLevel(talent: string): number {
    return this.fields.talent_levels[talent] ?? 1;
  }

  protected setTalent(talent: string, level: number): void {
    this.fields = {
      ...this.fields,
      talent_levels: { ...this.fields.talent_levels, [talent]: level },
    };
  }

  protected async save(): Promise<void> {
    if (!this.canSave()) return;
    this.actionError.set(null);
    try {
      const existing = this.editing();
      if (existing) {
        // No `character_id`: `BuildUpdate` has none and refuses one (T.1).
        const saved = await this.service.update(existing.id, {
          ...this.fields,
          weapon_id: this.weaponId(),
        });
        await this.load();
        // Stay in the build that was just saved. Resetting the form here would throw the
        // user out of what they were editing, and the difference between "saved" and
        // "saved and closed" is invisible on screen — it just looks like the edit vanished.
        this.editing.set(saved ?? existing);
      } else {
        await this.service.create({
          ...this.fields,
          character_id: this.characterId(),
          weapon_id: this.weaponId(),
        });
        await this.load();
        // Closed, not reset. The form used to sit permanently on the page, so blanking it was
        // the only way to say "saved"; in a dialog, closing says it, and leaving an empty
        // editor open would read as though the save had not taken.
        this.newBuild();
        this.closeEditor();
      }
    } catch (err) {
      // Verbatim. The API's refusal names both weapon classes, or the talent keys it accepts,
      // which is more useful than anything this page could invent.
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected async edit(build: BuildRead): Promise<void> {
    this.editing.set(build);
    this.actionError.set(null);
    this.editor()?.nativeElement.showModal?.();
    this.fields = {
      character_level: build.character_level,
      ascension_phase: build.ascension_phase,
      weapon_level: build.weapon_level,
      refinement: build.refinement,
      constellation_level: build.constellation_level,
      name: build.name ?? '',
      talent_levels: { ...blank(this.talents()).talent_levels, ...build.talent_levels },
      notes: build.notes,
    };
    if (build.character_id) await this.selectCharacter(build.character_id);
    this.weaponId.set(build.weapon_id ?? null);
  }

  protected newBuild(): void {
    this.editing.set(null);
    this.characterId.set('');
    this.weaponId.set(null);
    this.weapons.set([]);
    this.fields = blank(this.talents());
    this.actionError.set(null);
  }

  protected async remove(build: BuildRead): Promise<void> {
    this.actionError.set(null);
    try {
      await this.service.remove(build.id);
      if (this.editing()?.id === build.id) this.newBuild();
      await this.load();
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }
}
