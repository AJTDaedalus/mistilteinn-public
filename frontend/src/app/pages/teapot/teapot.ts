import { DecimalPipe } from '@angular/common';
import { Component, type OnInit, computed, inject, signal } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import type { SuiteRow } from './teapot.service';
import { CatalogueIcon } from '../../shared/icon/icon';
import { CatalogueService } from '../catalogue/catalogue.service';
import { TeapotService } from './teapot.service';

/**
 * The furnishing-set tracker — `DESIGN_account_tracking.md` Track 3.
 *
 * Owner: *"sortable by remaining primogems and lets users mark off which they've already done
 * like Seelie does."*
 *
 * ## The reward comes from the server, not from here
 *
 * 20 Primogems per character, cited at `app/services/teapot.py` and **published by the API**
 * rather than restated in this file — a second copy would be the one that drifted when a
 * patch changed it. The page still copes with it being absent, because the endpoint is
 * allowed to say it does not know.
 *
 * **The ordering never depended on it.** The reward is one constant per character, so
 * `reward × remaining` and `remaining` rank identically.
 */
@Component({
  selector: 'app-teapot',
  standalone: true,
  imports: [DecimalPipe, CatalogueIcon],
  templateUrl: './teapot.html',
  styleUrl: './teapot.scss',
})
export class TeapotPage implements OnInit {
  private readonly teapot = inject(TeapotService);
  private readonly catalogue = inject(CatalogueService);

  protected readonly rows = signal<SuiteRow[]>([]);
  protected readonly reward = signal<number | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly hideDone = signal(false);
  /** Sets nobody on the user's roster favours — noise for most people, so folded away. */
  protected readonly hideUnreachable = signal(true);
  /**
   * Free text, matched against the set's name **and its characters' names**.
   *
   * Owner of the request: *"search bar in general lmao, ctrl f to find exactly what i need to
   * keeping track isnt that convenient"* (#266). Ctrl-F is the thing being replaced, and
   * Ctrl-F over this page finds a character's name as readily as a set's — every chip carries
   * one — so the search does too. A name search that missed what the page already displays
   * would be a worse Ctrl-F than Ctrl-F.
   */
  protected readonly search = signal('');
  /**
   * `''` either, `'I'` indoor, `'O'` outdoor.
   *
   * Matched on the **leading letter**, because the source carries four values and not two: at
   * 7.0.51 the split is `OG` 48, `IG` 31, `O` 18, `I` 12. A filter comparing the whole string
   * would have offered "Indoor" and found 12 of the 43 indoor sets — a control that silently
   * hides two thirds of its own answer. What the `G` means is not documented anywhere this
   * repo can cite, so it is not interpreted; the first letter is the part that is legible.
   */
  protected readonly placementFilter = signal('');
  /** How the list is ordered: `''` keeps the server's ranking. */
  protected readonly sort = signal('');
  /**
   * Show only sets favoured by *these* characters, by nanoka id.
   *
   * *"filters: by characters (e.g. show only sets of your selected 3 chars…)"*. A set matches
   * if **any** of the chosen characters favours it, which is the question being asked — "what
   * should I build for this group" — rather than all of them, which for three characters is
   * almost always nothing.
   */
  protected readonly characterFilter = signal<ReadonlySet<string>>(new Set());
  protected readonly busy = signal<string | null>(null);
  /** nanoka id → name, so a chip reads "Noelle" rather than "10000027". */
  protected readonly names = signal<Map<string, string>>(new Map());
  /** nanoka id → avatar basename, so a chip carries a face rather than only a word. */
  protected readonly faces = signal<Map<string, string>>(new Map());

  protected readonly visible = computed(() => {
    const query = this.search().trim().toLowerCase();
    const placement = this.placementFilter();
    const chosen = this.characterFilter();
    const kept = this.rows().filter((row) => {
      if (this.hideDone() && row.done) return false;
      // A set nobody you own favours is worth nothing now and might be worth something later —
      // hidden by default because it is noise for most rosters, never dropped.
      const reachable = row.available.length > 0 || row.completed.length > 0;
      if (this.hideUnreachable() && !reachable) return false;
      if (placement && !row.placement.startsWith(placement)) return false;
      if (chosen.size && !this.favourites(row).some((id) => chosen.has(id))) return false;
      if (!query) return true;
      // The set's name, then the names on its chips — see `search`'s own note.
      if (row.name.toLowerCase().includes(query)) return true;
      return this.favourites(row).some(
        (id) => this.characterName(id).toLowerCase().includes(query),
      );
    });
    if (this.sort() !== 'release') return kept;
    // **"Release order", not "in-game order".** The ask was *"sort sets by how they appear
    // in-game"* (#266) and the source publishes no field for that — `nanoka_id` is the set's
    // own key, ascending as sets shipped. Labelling it for what it is rather than for what was
    // asked keeps it from becoming a claim nobody can check. Numeric, because these are
    // `"1"` … `"109"` and a string sort puts 100 between 10 and 11.
    return [...kept].sort((a, b) => Number(a.nanoka_id) - Number(b.nanoka_id));
  });

  /** Every character who favours a set, in all three states — what the row's chips show. */
  private favourites(row: SuiteRow): string[] {
    return [...row.available, ...row.completed, ...row.unowned];
  }

  /**
   * One card per character who favours *something* — the character filter's options.
   *
   * **Only the ones this roster has**, because the filter's purpose is "show me sets for my
   * team" and a chip for a character you do not own can only ever narrow to sets you cannot
   * claim. Derived from the rows on screen, so a chip can never find nothing.
   */
  protected readonly characterOptions = computed(() => {
    const owned = new Set<string>();
    for (const row of this.rows()) {
      for (const id of [...row.available, ...row.completed]) owned.add(id);
    }
    return [...owned]
      .map((id) => ({ id, name: this.characterName(id), icon: this.characterIcon(id) }))
      .sort((a, b) => a.name.localeCompare(b.name));
  });

  protected toggleCharacter(id: string): void {
    this.characterFilter.update((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected isCharacterChosen(id: string): boolean {
    return this.characterFilter().has(id);
  }

  /** Back to every set, without hunting for which of six controls is still set. */
  protected clearFilters(): void {
    this.search.set('');
    this.placementFilter.set('');
    this.characterFilter.set(new Set());
    this.sort.set('');
    this.hideDone.set(false);
    this.hideUnreachable.set(true);
  }

  /**
   * Whether anything is narrowing the list — which is what decides whether Clear is offered.
   *
   * **The two tick boxes count.** They were left out while `clearFilters()` reset them, so
   * Clear was hidden from a user whose only narrowing was "hide finished sets", and a user
   * who had deliberately un-ticked "hide sets nobody you have favours" got it silently
   * ticked again by a button labelled Clear. Both are compared against their defaults, so
   * the button appears exactly when it has something to undo.
   */
  protected readonly filtering = computed(
    () => this.search().trim() !== ''
      || this.placementFilter() !== ''
      || this.sort() !== ''
      || this.characterFilter().size > 0
      || this.hideDone()
      || !this.hideUnreachable(),
  );

  protected readonly claimable = computed(
    () => this.rows().reduce((total, row) => total + row.remaining, 0),
  );
  /** Primogems still on the table, or `null` when the server did not publish a reward. */
  protected readonly primogems = computed(() => {
    const reward = this.reward();
    return reward === null ? null : this.claimable() * reward;
  });
  protected readonly finished = computed(() => this.rows().filter((r) => r.done).length);

  async ngOnInit(): Promise<void> {
    // **Names are decoration, so they load beside the tracker and never block it.** A failure
    // here leaves chips reading their nanoka id, which is worse than a name and much better
    // than an empty page.
    await Promise.all([this.load(), this.loadNames()]);
  }

  private async loadNames(): Promise<void> {
    try {
      // **200 is the endpoint's maximum**, not a guess: `limit` is bounded at 200 and 500
      // was a 422 this method's own `catch` swallowed, so every chip silently read as a
      // nanoka id. The catalogue holds 150 characters, so one page covers it.
      const page = await this.catalogue.listCharacters({ limit: 200 });
      const rows = (page as {
        items?: { nanoka_id: string; name: string; icon?: string | null }[];
      })?.items ?? [];
      // **The pairs are typed explicitly.** `new Map(rows.map((r) => [a, b]))` infers
      // `string[]` rather than a tuple under the container's Angular compiler, which is
      // stricter than the host `tsc` — CLAUDE.md records this exact trap, and `npm run
      // verify` passing here does not mean the container will build it.
      const pairs: [string, string][] = rows.map((row) => [row.nanoka_id, row.name]);
      this.names.set(new Map(pairs));
      // **Only the rows that actually have art.** A catalogue row with no icon is a seeding
      // gap rather than an error, and `catalogue-icon` hides a broken image — but leaving the
      // id out of the map keeps "no art" and "no character" distinguishable here.
      const art = rows.filter((row) => row.icon);
      const faces: [string, string][] = art.map((row) => [row.nanoka_id, row.icon as string]);
      this.faces.set(new Map(faces));
    } catch {
      this.names.set(new Map());
    }
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const read = await this.teapot.suites();
      this.rows.set(read.suites ?? []);
      this.reward.set(read.reward_per_character ?? null);
    } catch (caught) {
      this.error.set(apiErrorMessage(caught));
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Tick or un-tick **one character on one set**.
   *
   * That is the unit the reward is given in, so it is the unit the page works in: a set
   * favoured by three characters you own is three separate 20-primogem invitations.
   *
   * **Optimistic, and reverted if the write fails.** Ticking is the page's whole interaction
   * and a round trip per click would make it feel broken; silently keeping a tick the server
   * refused would be worse, so a failure puts the row back and says so.
   */
  protected async toggle(row: SuiteRow, character: string): Promise<void> {
    const inviting = row.available.includes(character);
    this.busy.set(`${row.suite_id}/${character}`);
    this.apply(row.suite_id, character, inviting);
    try {
      await this.teapot.setInvited(row.suite_id, character, inviting);
    } catch (caught) {
      this.apply(row.suite_id, character, !inviting);
      this.error.set(apiErrorMessage(caught));
    } finally {
      this.busy.set(null);
    }
  }

  /** Move one character between `available` and `completed`, and re-derive the row. */
  private apply(suiteId: string, character: string, invited: boolean): void {
    this.rows.update((rows) => rows.map((row) => {
      if (row.suite_id !== suiteId) return row;
      const available = invited
        ? row.available.filter((c) => c !== character)
        : [...row.available, character].sort();
      const completed = invited
        ? [...row.completed, character].sort()
        : row.completed.filter((c) => c !== character);
      return {
        ...row,
        available,
        completed,
        remaining: available.length,
        // `done` is derived the same way the server derives it: nothing left to claim.
        done: available.length === 0 && completed.length > 0,
        remaining_primogems: this.reward() === null
          ? null
          : available.length * (this.reward() as number),
      };
    }));
  }

  protected busyWith(row: SuiteRow, character: string): boolean {
    return this.busy() === `${row.suite_id}/${character}`;
  }

  /**
   * Mark a set as built, or un-mark it.
   *
   * **Separate work from inviting**, so a separate control. Optimistic and reverted on
   * failure, like the invitation ticks.
   */
  protected async toggleBuilt(row: SuiteRow): Promise<void> {
    const next = !row.built;
    this.busy.set(`${row.suite_id}/built`);
    this.applyBuilt(row.suite_id, next);
    try {
      await this.teapot.setBuilt(row.suite_id, next);
    } catch (caught) {
      this.applyBuilt(row.suite_id, !next);
      this.error.set(apiErrorMessage(caught));
    } finally {
      this.busy.set(null);
    }
  }

  private applyBuilt(suiteId: string, built: boolean): void {
    this.rows.update((rows) => rows.map(
      (row) => (row.suite_id === suiteId ? { ...row, built } : row),
    ));
  }

  protected busyBuilding(row: SuiteRow): boolean {
    return this.busy() === `${row.suite_id}/built`;
  }

  /**
   * A character's display name.
   *
   * Falls back to the nanoka id, which is what the tracker holds. **Not a hard failure**: a
   * suite can favour a character this database has not seeded, and an id is a worse label
   * than a name but a much better one than a blank chip.
   */
  protected characterName(nanokaId: string): string {
    return this.names().get(nanokaId) ?? nanokaId;
  }

  /** The character's avatar basename, or `null` when the catalogue has no art for them. */
  protected characterIcon(nanokaId: string): string | null {
    return this.faces().get(nanokaId) ?? null;
  }

  /**
   * "indoor" or "outdoor", from the **leading letter** of nanoka's placement code.
   *
   * It compared the whole string, so `IG` and `OG` — 79 of the 109 sets — matched neither and
   * the row said nothing at all about where the set goes. See `placementFilter`.
   */
  protected placement(row: SuiteRow): string {
    const where = row.placement.charAt(0);
    return where === 'I' ? 'indoor' : where === 'O' ? 'outdoor' : '';
  }
}
