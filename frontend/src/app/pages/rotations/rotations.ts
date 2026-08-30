import { Component, ElementRef, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { ElementChip } from '../../shared/element/element';
import { CatalogueIcon } from '../../shared/icon/icon';
import { EntityToken } from '../../shared/token/token';
import { CardPicker } from '../../shared/card-picker/card-picker';
import { rosterOptions } from '../../shared/team-scope';
import {
  RotationsService,
  type LibraryRotationRead,
  type RotationAction,
  type RotationRead,
  type RotationStep,
  type TeamRoster,
} from './rotations.service';

/**
 * The rotation editor.
 *
 * The owner's ruling started this chunk: *"gcsim uses a convoluted rotation syntax, something
 * more like fairy would be a big improvement."* The improvement is not a prettier text box —
 * it is that **the two mistakes gcsim makes silently cannot be expressed here**. A bare action
 * list runs once; `while 1` deadlocks on an ungated action. Both produce a config gcsim
 * accepts, runs, and reports on, with exactly one burst in it. The compiler emits the gating
 * and the loop; a user picks a character and an action, and cannot pick a character who is not
 * on the team, because the picker is populated from the same roster the write path validates
 * against.
 *
 * `Compile` is on the page for the same reason. A compiler nobody can inspect is a compiler
 * nobody can check, and the complaint was precisely about a syntax that hides what it does.
 */
@Component({
  selector: 'page-rotations',
  imports: [
    FormsModule, RouterLink, CardPicker, CatalogueIcon, ElementChip, EntityToken,
  ],
  templateUrl: './rotations.html',
  styleUrl: './rotations.scss',
})
export class RotationsPage implements OnInit {
  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no rotations". */
  protected readonly error = signal<string | null>(null);
  /** Non-null means one *action* failed — a save, a delete, a compile. */
  protected readonly actionError = signal<string | null>(null);

  protected readonly actions = signal<RotationAction[]>([]);
  protected readonly teams = signal<TeamRoster[]>([]);
  protected readonly saved = signal<RotationRead[]>([]);

  protected readonly teamId = signal('');
  /**
   * A **signal**, because `canSave` reads it.
   *
   * As a plain field it was invisible to the computed: Angular tracks signal reads, so
   * typing a name never invalidated `canSave` and the button stayed disabled until something
   * *else* in it changed. Picking a slot after typing worked; typing after picking did not,
   * which is why it reads as "the button does not work".
   */
  protected readonly name = signal('');
  protected readonly steps = signal<RotationStep[]>([]);
  /** The rotation being edited, or null while composing a new one. */
  protected readonly editing = signal<string | null>(null);
  protected readonly compiled = signal<string | null>(null);
  /** What the server holds for `editing()`, so unsaved edits are detectable. */
  private readonly stored = signal('');

  /**
   * The screen no longer matches what was saved.
   *
   * `/compile` reads the **stored** steps. Compiling while this is true would print the
   * config for the last save beside a screen showing something else — "a number that looks
   * right but refers to something else", which is the failure mode this project has met
   * most often. So Compile is offered only when the two agree.
   */
  // ── the saved list, by team ────────────────────────────────────────────────

  /**
   * Which team's rotations are open. Empty means none.
   *
   * The audit asks for two levels: *"The cards should be teams, with the number of rotations
   * saved for them listed. Clicking on one should expand a list of rotations."* A flat list
   * mixes rotations for teams that share no characters, and the first thing anyone does with
   * it is look for the ones that belong to a team.
   */
  protected readonly openTeam = signal('');

  /** **Search is over teams, not rotations** — the audit says so, and it is the outer level. */
  protected readonly teamSearch = signal('');

  protected readonly byTeam = computed(() => {
    const query = this.teamSearch().trim().toLowerCase();
    const counts = new Map<string, RotationRead[]>();
    for (const rotation of this.saved()) {
      const list = counts.get(rotation.team_id) ?? [];
      list.push(rotation);
      counts.set(rotation.team_id, list);
    }
    return this.teams()
      .filter((team) => {
        if (!query) return true;
        // The characters too: "which of my teams has Nahida" is how someone looks for a team
        // they named "Bloom 2".
        const who = team.characters.map((c) => c.name).join(' ');
        return `${team.name} ${who}`.toLowerCase().includes(query);
      })
      .map((team) => ({ team, rotations: counts.get(team.id) ?? [] }));
  });

  protected toggleTeam(id: string): void {
    this.openTeam.update((current) => (current === id ? '' : id));
  }

  // ── the library (BACKLOG_frontend §5, TASKS_rotation_library L.8) ─────────
  //
  // The owner's audit: *"It belongs as the last option inside an expanded team, opening a
  // card-and-filter pop-up."* So it is not a page, and not a tab — it is the answer to a
  // question you are already asking when you have a team open in front of you.

  protected readonly libraryTeam = signal<TeamRoster | null>(null);
  protected readonly libraryRows = signal<LibraryRotationRead[]>([]);
  protected readonly libraryLoading = signal(false);
  protected readonly libraryError = signal<string | null>(null);
  protected readonly libraryNote = signal<string | null>(null);
  /**
   * Whether the search is narrowed to the open team's characters.
   *
   * **Starts narrowed**, because that is the question being asked — a library reached from
   * inside a team is asking "what do people run on *this*". Widening has to be possible or
   * the control is a list rather than a search.
   */
  protected readonly libraryForThisTeam = signal(true);

  protected readonly libraryDialog =
    viewChild<ElementRef<HTMLDialogElement>>('libraryDialog');

  protected async openLibrary(team: TeamRoster): Promise<void> {
    this.libraryTeam.set(team);
    this.libraryForThisTeam.set(true);
    this.libraryNote.set(null);
    // `showModal?.()`: `HTMLDialogElement` is absent in jsdom, so a bare call is a TypeError
    // thrown from a click handler — which takes the page out rather than failing one control.
    this.libraryDialog()?.nativeElement.showModal?.();
    await this.loadLibrary();
  }

  protected closeLibrary(): void {
    this.libraryDialog()?.nativeElement.close?.();
  }

  protected async setLibraryScope(forThisTeam: boolean): Promise<void> {
    this.libraryForThisTeam.set(forThisTeam);
    await this.loadLibrary();
  }

  protected async loadLibrary(): Promise<void> {
    const team = this.libraryTeam();
    if (!team) return;
    this.libraryLoading.set(true);
    this.libraryError.set(null);
    try {
      const page = await this.rotations.library({
        characters: this.libraryForThisTeam()
          ? team.characters.map((c) => c.nanoka_id)
          : undefined,
      });
      this.libraryRows.set(page.items);
    } catch {
      // Surfaced, not swallowed: an empty library and a failed request look identical on
      // screen, and only one of them means nobody has published anything.
      this.libraryError.set('Could not load the rotation library.');
      this.libraryRows.set([]);
    } finally {
      this.libraryLoading.set(false);
    }
  }

  /**
   * Toggle a like, updating the row in place.
   *
   * Optimistic, and reverted on failure. A like is a one-bit opinion; making the user wait a
   * round trip to see it register is the wrong trade, and re-fetching the whole page to show
   * one number changing is the other wrong one.
   */
  protected async toggleLike(row: LibraryRotationRead): Promise<void> {
    const liked = !row.liked_by_me;
    const apply = (value: boolean) => this.libraryRows.update((rows) =>
      rows.map((r) => (r.id === row.id
        ? { ...r, liked_by_me: value, like_count: r.like_count + (value ? 1 : -1) }
        : r)),
    );
    apply(liked);
    try {
      await this.rotations.setLiked(row.id, liked);
    } catch {
      apply(!liked);
      this.libraryError.set('Could not save that.');
    }
  }

  /**
   * Copy a shared rotation onto the team the library was opened from.
   *
   * The server re-resolves every step against that team and **refuses, naming the character**,
   * when it does not field one. That message is shown verbatim: it names what is missing,
   * which is more useful than anything this page could invent — and it is the reason the
   * "all teams" scope is safe to offer at all.
   */
  protected async copyFromLibrary(row: LibraryRotationRead): Promise<void> {
    const team = this.libraryTeam();
    if (!team) return;
    this.libraryError.set(null);
    this.libraryNote.set(null);
    try {
      const copied = await this.rotations.copy(row.id, team.id);
      this.libraryNote.set(`Copied as "${copied.name}".`);
      await this.load();
    } catch (err) {
      this.libraryError.set(apiErrorMessage(err));
    }
  }

  /**
   * A rotation's shape at a glance: how many hits it lands, and how long a cycle it is.
   *
   * **Steps, not hits, and it says so.** The audit asks for *"x hits, y seconds"*; a step's
   * `repeat` is how many times an action is taken, which is the closest thing this model
   * holds — actual hits and seconds are gcsim's answer and need a run. Naming it "steps"
   * rather than "hits" is the difference between a summary and a claim.
   */
  protected summarise(rotation: RotationRead): string {
    const steps = rotation.steps.length;
    const actions = rotation.steps.reduce((total, step) => total + (step.repeat ?? 1), 0);
    return `${steps} step${steps === 1 ? '' : 's'} · ${actions} actions`;
  }

  protected readonly dirty = computed(
    () => this.editing() !== null && this.snapshot() !== this.stored(),
  );

  /** Who the chosen team holds. An empty roster is why `addStep` refuses. */
  protected readonly roster = computed(
    () => this.teams().find((team) => team.id === this.teamId())?.characters ?? [],
  );

  /** Art by the id a step names, so a step can show who is acting. */
  private readonly rosterArt = computed(
    () => new Map(this.roster().map((m) => [m.nanoka_id, m.icon ?? null])),
  );

  /**
   * The acting character's art for one step.
   *
   * A step can name somebody the roster no longer holds — a build removed from the team
   * after the rotation was saved — so a miss returns null rather than throwing, and
   * `CatalogueIcon` renders nothing.
   */
  protected rosterIcon(nanokaId: string): string | null {
    return this.rosterArt().get(nanokaId) ?? null;
  }

  protected readonly canSave = computed(
    () => this.name().trim().length > 0 && this.teamId() !== '' && this.steps().length > 0,
  );

  private readonly rotations = inject(RotationsService);

  /** Name and steps as one comparable string. Order is part of it — order *is* the rotation. */
  private snapshot(): string {
    return JSON.stringify({ name: this.name().trim(), steps: this.steps() });
  }

  ngOnInit(): void {
    void this.load();
  }

  /** Options and saved rotations together — the page is not usable without both. */
  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [options, list] = await Promise.all([
        this.rotations.options(),
        this.rotations.list(),
      ]);
      this.actions.set(options.actions as RotationAction[]);
      this.teams.set(options.teams);
      this.saved.set(list.items);
      if (this.teamId() === '' && options.teams.length > 0) {
        this.teamId.set(options.teams[0].id);
      }
    } catch {
      // Surfaced, not swallowed. An empty editor and a failed load look identical on screen,
      // and only one of them means "you have no teams yet".
      this.error.set('Could not load the rotation editor.');
      this.teams.set([]);
      this.saved.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  /** Team cards, built by the shared projection so all four faces are on every one. */
  protected readonly teamOptions = computed(() => rosterOptions(this.teams()));

  protected pickTeam(ids: readonly string[]): void {
    this.selectTeam(ids[0] ?? '');
  }

  // ── the editor, as a pop-up (BACKLOG_frontend §1's second pattern) ────────
  //
  // "New rotation" is a button that opens one, and the saved teams are the page. The editor
  // used to hold two thirds of the width permanently, which is why the list beside it was a
  // narrow column — the same inversion Builds got in #170.

  protected readonly editorDialog = viewChild<ElementRef<HTMLDialogElement>>('editorDialog');

  protected startNew(): void {
    this.newRotation();
    // `showModal?.()`: absent in jsdom, and a bare call is a TypeError thrown from a click
    // handler — which takes the page out rather than failing the one control.
    this.editorDialog()?.nativeElement.showModal?.();
  }

  protected closeEditor(): void {
    this.editorDialog()?.nativeElement.close?.();
  }

  protected selectTeam(id: string): void {
    if (id === this.teamId()) return;
    // Steps name characters on the old team, so keeping them would build a rotation the API
    // refuses on save — with the user's own selections cited back at them as invalid.
    this.teamId.set(id);
    this.steps.set([]);
    this.compiled.set(null);
  }

  protected addStep(): void {
    const first = this.roster()[0];
    if (!first || this.actions().length === 0) return;
    this.appendStep(first.nanoka_id, this.actions()[0]);
  }

  /**
   * Append one step. The shared path, so the two ways to add one cannot drift.
   *
   * `DESIGN_rotation_builder.md` B.2 adds a second entry point — click a face, click an
   * action — and two `steps.update` calls would eventually initialise a step differently.
   */
  protected appendStep(character: string, action: RotationAction): void {
    this.steps.update((steps) => [...steps, { character, action, repeat: 1, note: '' }]);
    this.compiled.set(null);
  }

  /**
   * The character whose actions the quick-add row is offering, or null for none.
   *
   * A two-click add: pick a face, pick an action, and the step appends. The roster is already
   * drawn on this page and was not clickable — B.2 measured the old path at five to seven
   * interactions per step, most of them spent in two `<select>`s.
   */
  protected readonly addingFor = signal<string | null>(null);

  protected toggleAddingFor(nanokaId: string): void {
    this.addingFor.update((current) => (current === nanokaId ? null : nanokaId));
  }

  protected quickAdd(action: RotationAction): void {
    const character = this.addingFor();
    if (!character) return;
    this.appendStep(character, action);
    this.addingFor.set(null);
  }

  /**
   * This character's own name for an action, or the action key.
   *
   * **A gcsim config says `nahida skill`, and that is the complaint that started the chunk.**
   * Only the three levelled talents have names; `dash`, `jump` and `walk` are not abilities,
   * so they keep their key — as does a character whose talents are not seeded.
   */
  protected abilityName(nanokaId: string, action: string): string {
    const member = this.roster().find((c) => c.nanoka_id === nanokaId);
    return member?.abilities?.[action] ?? action;
  }

  /** Duplicate a step in place — what `DESIGN_rotation.md` §2 promised a UI would do. */
  protected duplicateStep(index: number): void {
    this.steps.update((steps) => [
      ...steps.slice(0, index + 1),
      { ...steps[index] },
      ...steps.slice(index + 1),
    ]);
    this.compiled.set(null);
  }

  protected removeStep(index: number): void {
    this.steps.update((steps) => steps.filter((_, i) => i !== index));
    this.compiled.set(null);
  }

  /**
   * Move a step one position. `delta` is -1 or +1; out-of-range is a no-op.
   *
   * Order is the rotation. Silently clamping a move at the ends would be indistinguishable
   * from a reorder that did nothing, so it does nothing visibly instead.
   */
  protected move(index: number, delta: number): void {
    const target = index + delta;
    const steps = this.steps();
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    this.steps.set(next);
    this.compiled.set(null);
  }

  protected setStep(index: number, patch: Partial<RotationStep>): void {
    this.steps.update((steps) =>
      steps.map((step, i) => (i === index ? { ...step, ...patch } : step)),
    );
    this.compiled.set(null);
  }

  protected async save(): Promise<void> {
    if (!this.canSave()) return;
    this.actionError.set(null);
    try {
      const id = this.editing();
      const rotation = id
        ? await this.rotations.update(id, { name: this.name().trim(), steps: this.steps() })
        : await this.rotations.create({
            name: this.name().trim(),
            team_id: this.teamId(),
            steps: this.steps(),
          });
      this.editing.set(rotation!.id);
      this.stored.set(this.snapshot());
      await this.refreshList();
    } catch (err) {
      // The API's refusal is shown verbatim: it names the offending characters and lists who
      // the team actually has, which is more useful than anything this page could invent.
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected edit(rotation: RotationRead): void {
    this.editorDialog()?.nativeElement.showModal?.();
    this.editing.set(rotation.id);
    this.name.set(rotation.name);
    this.teamId.set(rotation.team_id);
    // Copied defensively. Nothing here mutates a step in place today — `setStep`, `move`
    // and `removeStep` all rebuild — so **removing this copy changes nothing observable**,
    // and there is deliberately no test for it: the mutation survived, which means any test
    // claiming to hold it would be one that cannot fail.
    this.steps.set(rotation.steps.map((step) => ({ ...step })));
    this.stored.set(this.snapshot());
    this.compiled.set(null);
    this.actionError.set(null);
  }

  protected newRotation(): void {
    this.editing.set(null);
    this.name.set('');
    this.steps.set([]);
    this.stored.set('');
    this.compiled.set(null);
    this.actionError.set(null);
  }

  protected async remove(rotation: RotationRead): Promise<void> {
    this.actionError.set(null);
    try {
      await this.rotations.remove(rotation.id);
      if (this.editing() === rotation.id) this.newRotation();
      await this.refreshList();
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  /**
   * Show the gcsim config this rotation became.
   *
   * Only a *saved and unmodified* rotation can be compiled — the endpoint reads the stored
   * steps. Offering it on unsaved edits would show the config for the last save while the
   * screen displayed something else, which is the "a number that looks right but refers to
   * something else" failure this project keeps meeting. The first version of this guard
   * covered only a brand-new rotation and left that hole open for edits to a saved one.
   */
  protected async compile(): Promise<void> {
    const id = this.editing();
    if (!id || this.dirty()) return;
    this.actionError.set(null);
    try {
      this.compiled.set(await this.rotations.compile(id));
    } catch (err) {
      this.compiled.set(null);
      this.actionError.set(apiErrorMessage(err));
    }
  }

  private async refreshList(): Promise<void> {
    this.saved.set((await this.rotations.list()).items);
  }
}
