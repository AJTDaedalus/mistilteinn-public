import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { CatalogueIcon } from '../../shared/icon/icon';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import { TEAM_SLOTS, TeamsService, type TeamRead, type TeamSlot } from './teams.service';

function emptySlots(): Record<TeamSlot, string | null> {
  return Object.fromEntries(TEAM_SLOTS.map((s) => [s, null])) as Record<
    TeamSlot,
    string | null
  >;
}

/**
 * The team builder.
 *
 * A team is up to four of the caller's builds, and it is what a rotation's steps are
 * validated against. Two server rules shape the pickers, and the page's job is to make both
 * unreachable rather than to explain them:
 *
 * - **the same build cannot fill two slots** — `assert_slots_distinct`, because every
 *   index-based support selection would otherwise hand the primary back to itself;
 * - **the same character cannot appear twice** — T.1a. A user may *own* a C0 and a C6 of one
 *   character, and gcsim refuses a party holding both (`pkg/simulation/setup.go:94` at the
 *   pin returns `duplicated character`).
 *
 * Each slot therefore offers only builds that break neither rule. A picker offering one would
 * let a user select it and then be told their own choice is invalid.
 */
@Component({
  selector: 'page-teams',
  imports: [FormsModule, RouterLink, CatalogueIcon],
  templateUrl: './teams.html',
  styleUrl: './teams.scss',
})
export class TeamsPage implements OnInit {
  protected readonly slots = TEAM_SLOTS;
  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no teams". */
  protected readonly error = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);

  protected readonly teams = signal<TeamRead[]>([]);
  protected readonly builds = signal<BuildRead[]>([]);

  protected readonly editing = signal<TeamRead | null>(null);
  /**
   * A **signal**, because `canSave` reads it.
   *
   * As a plain field it was invisible to the computed: Angular tracks signal reads, so
   * typing a name never invalidated `canSave` and the button stayed disabled until something
   * *else* in it changed. Picking a slot after typing worked; typing after picking did not,
   * which is why it reads as "the button does not work".
   */
  protected readonly name = signal('');
  protected readonly picked = signal<Record<TeamSlot, string | null>>(emptySlots());

  /**
   * A team needs a name and a **first** member.
   *
   * `build1_id` is the one required slot in `TeamCreate` — a team with nobody in it is not a
   * team. Requiring "at least one member" instead let a user fill slot 2 and leave slot 1
   * empty, which the picker allowed and the server refused with a schema error about a field
   * the page never showed them. Found in the T.4 self-review.
   */
  protected readonly canSave = computed(
    () => this.name().trim().length > 0 && this.picked().build1_id !== null,
  );

  private readonly teamsService = inject(TeamsService);
  private readonly buildsService = inject(BuildsService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [teams, builds] = await Promise.all([
        this.teamsService.list(),
        this.buildsService.list(),
      ]);
      this.teams.set(teams);
      this.builds.set(builds);
    } catch {
      // Surfaced, not swallowed: an empty list and a failed request look identical on screen,
      // and only one of them means the account has no teams.
      this.error.set('Could not load the team builder.');
      this.teams.set([]);
      this.builds.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  protected build(id: string | null | undefined): BuildRead | undefined {
    return id ? this.builds().find((b) => b.id === id) : undefined;
  }

  /** The slots that currently hold someone, in party order. */
  protected filled(): TeamSlot[] {
    return TEAM_SLOTS.filter((slot) => this.picked()[slot] !== null);
  }

  /**
   * What `slot` may be set to: every build that would not break a rule the server enforces.
   *
   * Excludes builds already in *another* slot, and builds whose character is already on the
   * team. The slot's own current value is always kept — dropping it would leave the
   * `<select>` with nothing matching its value, which renders as an empty slot that is in
   * fact filled.
   */
  protected availableFor(slot: TeamSlot): BuildRead[] {
    const current = this.picked()[slot];
    const takenBuilds = new Set(
      TEAM_SLOTS.filter((s) => s !== slot)
        .map((s) => this.picked()[s])
        .filter((id): id is string => id !== null),
    );
    const takenCharacters = new Set(
      [...takenBuilds]
        .map((id) => this.build(id)?.character_id)
        .filter((id): id is string => !!id),
    );
    return this.builds().filter(
      (b) =>
        b.id === current ||
        (!takenBuilds.has(b.id) && !(b.character_id && takenCharacters.has(b.character_id))),
    );
  }

  protected pick(slot: TeamSlot, buildId: string): void {
    this.picked.update((slots) => ({ ...slots, [slot]: buildId || null }));
    this.actionError.set(null);
  }

  protected async save(): Promise<void> {
    if (!this.canSave()) return;
    this.actionError.set(null);
    try {
      const picked = this.picked();
      const existing = this.editing();
      if (existing) {
        const body = { name: this.name().trim(), ...picked };
        const saved = await this.teamsService.update(existing.id, body);
        await this.load();
        // Stay in what was just saved, as the build editor does — being thrown out of an
        // edit is indistinguishable on screen from the edit having vanished.
        this.editing.set(saved ?? existing);
      } else {
        // `canSave` guarantees the first slot, which is what makes this typed rather than
        // cast: the cast was hiding the mismatch this self-review found.
        await this.teamsService.create({
          ...picked,
          name: this.name().trim(),
          build1_id: picked.build1_id!,
        });
        await this.load();
        this.newTeam();
      }
    } catch (err) {
      // Verbatim: the API names the character it saw twice, and which slots hold it.
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected edit(team: TeamRead): void {
    this.editing.set(team);
    this.name.set(team.name);
    this.picked.set(
      Object.fromEntries(TEAM_SLOTS.map((slot) => [slot, team[slot] ?? null])) as Record<
        TeamSlot,
        string | null
      >,
    );
    this.actionError.set(null);
  }

  protected newTeam(): void {
    this.editing.set(null);
    this.name.set('');
    this.picked.set(emptySlots());
    this.actionError.set(null);
  }

  protected async remove(team: TeamRead): Promise<void> {
    this.actionError.set(null);
    try {
      await this.teamsService.remove(team.id);
      if (this.editing()?.id === team.id) this.newTeam();
      await this.load();
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  /** How a team reads in the saved list. */
  protected members(team: TeamRead): string[] {
    return TEAM_SLOTS.map((slot) => this.build(team[slot])?.character?.name).filter(
      (name): name is string => !!name,
    );
  }

  /**
   * The party as drawable members, or **null** when there are none.
   *
   * Null rather than `[]` deliberately: `@if` treats an empty array as truthy, so returning
   * one would render an empty `.party` strip and skip the "nobody" branch entirely — a team
   * whose builds have all been deleted would show as a blank space rather than as empty.
   */
  protected party(team: TeamRead): { buildId: string; name: string; icon: string | null }[] | null {
    const roster = TEAM_SLOTS.map((slot) => ({ slot, build: this.build(team[slot]) }))
      .filter((entry): entry is { slot: TeamSlot; build: BuildRead } => !!entry.build)
      .map(({ slot, build }) => ({
        // The slot, not the build id: a team cannot hold one build twice, but keying on the
        // build would still be keying on a value the row does not own.
        buildId: slot,
        name: build.character?.name ?? 'No character',
        icon: build.character?.icon ?? null,
      }));
    return roster.length ? roster : null;
  }

  /** The art for whoever is in `slot`, for the adornment beside its `<select>`. */
  protected slotIcon(slot: TeamSlot): string | null {
    return this.build(this.picked()[slot])?.character?.icon ?? null;
  }
}
