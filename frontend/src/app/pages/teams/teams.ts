import {
  Component, ElementRef, OnInit, computed, inject, signal, viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { Combobox, type ComboboxOption } from '../../shared/combobox/combobox';
import { CatalogueService, type ReactionRead } from '../catalogue/catalogue.service';
import { CatalogueIcon } from '../../shared/icon/icon';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import { TEAM_SLOTS, TeamsService, type TeamRead, type TeamSlot } from './teams.service';

function emptySlots(): Record<TeamSlot, string | null> {
  return Object.fromEntries(TEAM_SLOTS.map((s) => [s, null])) as Record<
    TeamSlot,
    string | null
  >;
}

/** One member as a saved-team card draws them. */
interface TeamMember {
  buildId: string;
  name: string;
  icon: string | null;
  element: string | null;
  elementIcon: string | null;
  level: number;
  weapon: string;
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
  imports: [FormsModule, RouterLink, CatalogueIcon, Combobox],
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
  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [teams, builds, reactions] = await Promise.all([
        this.teamsService.list(),
        this.buildsService.list(),
        // Never fatal: the reaction filter is an extra way to narrow a list that is already on
        // screen, and losing it should not take the page's error state with it.
        this.catalogue.listReactions().catch(() => []),
      ]);
      this.teams.set(teams);
      this.builds.set(builds);
      this.reactions.set(reactions);
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
        // Closed, not reset — the same ruling as the build editor (#170). The form used to
        // sit permanently on the page, so blanking it was the only way to say "saved"; in a
        // dialog, closing says it, and an empty editor left open reads as a save that did
        // not take.
        this.newTeam();
        this.closeEditor();
      }
    } catch (err) {
      // Verbatim: the API names the character it saw twice, and which slots hold it.
      this.actionError.set(apiErrorMessage(err));
    }
  }

  /* ── The builder, as a pop-up ────────────────────────────────────────────────
     `BACKLOG_frontend.md` §4. Same shape as the build editor (#170) and the rotation editor:
     a native `<dialog>` for the focus trapping, Escape and backdrop a hand-rolled panel would
     have to reimplement. */
  /** The reactions a saved team could produce, in the shape `mist-combobox` reads. */
  protected readonly reactionOptions = computed<ComboboxOption[]>(() =>
    this.reactionsPresent().map((r) => ({ value: r.id, label: r.name })),
  );

  protected readonly editor = viewChild<ElementRef<HTMLDialogElement>>('editor');

  /** Open on a blank team.
   *
   * **`showModal?.()`, deliberately** — `HTMLDialogElement` is absent in jsdom, so a bare
   * call throws in every TestBed spec that touches this path.
   */
  protected startNew(): void {
    this.newTeam();
    this.editor()?.nativeElement.showModal?.();
  }

  protected closeEditor(): void {
    this.editor()?.nativeElement.close?.();
  }

  /** Escape and the backdrop close the dialog without going through `closeEditor`. */
  protected onEditorClosed(): void {
    this.newTeam();
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
    this.editor()?.nativeElement.showModal?.();
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
  /**
   * Filter the saved teams by the visions they field, or by a reaction they could produce.
   *
   * **The reaction table is the server's**, from `GET /reactions` — committed and cited in
   * `docs/RESEARCH_elemental_reactions.md`, which records the source URL, the retrieval date
   * and the wiki's own wording per reaction. Reading it here rather than restating it is the
   * same rule every other vocabulary on this page follows.
   *
   * **Could produce, not will.** Four elements can field Hyperbloom; whether a rotation
   * actually triggers it is the simulator's question, and a filter claiming otherwise would be
   * answering something it cannot see.
   */
  protected readonly elementFilter = signal('');
  /** Reactions the saved teams could produce, from the server's committed table. */
  protected readonly reactions = signal<ReactionRead[]>([]);
  protected readonly reactionFilter = signal('');

  /** A reaction is possible when the party has everything it needs. */
  private canReact(elements: Set<string>, reaction: ReactionRead): boolean {
    if (!reaction.required.every((element) => elements.has(element))) return false;
    // Swirl and Crystallize need one *more* element from a fixed four — and the two Lunar
    // variants that look similar do not, which is why this is data on the row rather than a
    // rule about the name.
    return !reaction.one_of.length || reaction.one_of.some((e) => elements.has(e));
  }

  /** Reactions at least one saved team could produce. Offering the rest is offering nothing. */
  protected readonly reactionsPresent = computed(() => {
    const parties = this.teams().map(
      (team) => new Set((this.party(team) ?? []).map((m) => m.element ?? '')),
    );
    return this.reactions().filter(
      (reaction) => parties.some((elements) => this.canReact(elements, reaction)),
    );
  });

  protected readonly elementsPresent = computed(() => {
    const seen = new Map<string, string | null>();
    for (const team of this.teams()) {
      for (const member of this.party(team) ?? []) {
        if (member.element && !seen.has(member.element)) {
          seen.set(member.element, member.elementIcon);
        }
      }
    }
    return [...seen].map(([element, icon]) => ({ element, icon }))
      .sort((a, b) => a.element.localeCompare(b.element));
  });

  protected readonly shownTeams = computed(() => {
    const element = this.elementFilter();
    const reactionId = this.reactionFilter();
    const reaction = this.reactions().find((r) => r.id === reactionId) ?? null;
    if (!element && !reaction) return this.teams();

    return this.teams().filter((team) => {
      const members = this.party(team) ?? [];
      if (element && !members.some((m) => m.element === element)) return false;
      if (!reaction) return true;
      return this.canReact(new Set(members.map((m) => m.element ?? '')), reaction);
    });
  });

  protected party(team: TeamRead): TeamMember[] | null {
    const roster = TEAM_SLOTS.map((slot) => ({ slot, build: this.build(team[slot]) }))
      .filter((entry): entry is { slot: TeamSlot; build: BuildRead } => !!entry.build)
      .map(({ slot, build }) => ({
        // The slot, not the build id: a team cannot hold one build twice, but keying on the
        // build would still be keying on a value the row does not own.
        buildId: slot,
        name: build.character?.name ?? 'No character',
        icon: build.character?.icon ?? null,
        // **The character's level, and the weapon without its own.** Together they rendered
        // "Lv90 · Mappa Mare · R5 · Lv90" — two different levels reading as one repeated — and
        // the character's is the one worth the space (owner ruling).
        //
        // So this is the one place that does *not* use `weapon_display`, which exists so three
        // surfaces cannot disagree about a build's gear and deliberately ends in the weapon's
        // level. Composed from the same two fields it is built from, and only because the
        // omission is the point.
        element: build.character?.element ?? null,
        elementIcon: build.character?.element_icon ?? null,
        level: build.character_level,
        weapon: build.weapon
          ? `${build.weapon.name} · R${build.refinement}`
          : 'no weapon',
      }));
    return roster.length ? roster : null;
  }

  /** The art for whoever is in `slot`, for the adornment beside its `<select>`. */
  /**
   * The builds this slot may take, as combobox options with the character's face.
   *
   * Wraps `availableFor` rather than replacing it: that method holds the two server rules —
   * no build in two slots, no two builds of the same character — and duplicating them here to
   * shape an option list is how a client-side filter starts offering what the API refuses.
   */
  protected optionsFor(slot: TeamSlot): ComboboxOption[] {
    return this.availableFor(slot).map((b) => ({
      value: b.id,
      label: b.character?.name || 'No character',
      icon: b.character?.icon ?? null,
      detail: `C${b.constellation_level} · ${b.weapon_display || 'no weapon'}`,
    }));
  }

}
