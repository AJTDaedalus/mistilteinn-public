import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../api/api-error';
import { MAX_PAGE_LIMIT } from '../../api/page-size';
import { CatalogueService } from '../catalogue/catalogue.service';
import {
  BuildsService,
  type BuildFields,
  type BuildRead,
  type CharacterSummary,
  type WeaponSummary,
} from './builds.service';

/** What a new build starts as. Matches the server's own defaults, which bound each field. */
function blank(talents: string[]): BuildFields {
  return {
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
  imports: [FormsModule],
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
  protected readonly editing = signal<BuildRead | null>(null);
  protected readonly characterId = signal('');
  protected readonly weaponId = signal<string | null>(null);
  protected fields: BuildFields = blank([]);

  protected readonly character = computed(
    () => this.characters().find((c) => c.id === this.characterId()) ?? null,
  );

  protected readonly canSave = computed(() => this.characterId() !== '');

  private readonly service = inject(BuildsService);
  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [options, builds, characters] = await Promise.all([
        this.service.options(),
        this.service.list(),
        this.catalogue.listCharacters({ limit: MAX_PAGE_LIMIT }),
      ]);
      this.talents.set(options.talents);
      this.maxTalent.set(options.max_talent_level);
      this.builds.set(builds);
      this.characters.set(characters.items as CharacterSummary[]);
      if (this.editing() === null) this.fields = blank(options.talents);
    } catch {
      // Surfaced, not swallowed: an empty list and a failed request look identical on
      // screen, and only one of them means the account has no builds.
      this.error.set('Could not load the build editor.');
      this.builds.set([]);
      this.characters.set([]);
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
  protected async selectCharacter(id: string): Promise<void> {
    this.characterId.set(id);
    this.weaponId.set(null);
    this.weapons.set([]);
    const chosen = this.characters().find((c) => c.id === id);
    if (!chosen) return;
    try {
      const page = await this.catalogue.listWeapons({
        weapon_type: chosen.weapon_type,
        limit: MAX_PAGE_LIMIT,
      });
      this.weapons.set(page.items as WeaponSummary[]);
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
        this.newBuild();
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
    this.fields = {
      character_level: build.character_level,
      ascension_phase: build.ascension_phase,
      weapon_level: build.weapon_level,
      refinement: build.refinement,
      constellation_level: build.constellation_level,
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
