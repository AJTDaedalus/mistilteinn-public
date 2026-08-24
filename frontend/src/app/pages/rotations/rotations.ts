import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../api/api-error';
import {
  RotationsService,
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
  imports: [FormsModule],
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
  protected name = '';
  protected readonly steps = signal<RotationStep[]>([]);
  /** The rotation being edited, or null while composing a new one. */
  protected readonly editing = signal<string | null>(null);
  protected readonly compiled = signal<string | null>(null);

  /** Who the chosen team holds. An empty roster is why `addStep` refuses. */
  protected readonly roster = computed(
    () => this.teams().find((team) => team.id === this.teamId())?.characters ?? [],
  );

  protected readonly canSave = computed(
    () => this.name.trim().length > 0 && this.teamId() !== '' && this.steps().length > 0,
  );

  private readonly rotations = inject(RotationsService);

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
    this.steps.update((steps) => [
      ...steps,
      { character: first.nanoka_id, action: this.actions()[0], repeat: 1, note: '' },
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
        ? await this.rotations.update(id, { name: this.name.trim(), steps: this.steps() })
        : await this.rotations.create({
            name: this.name.trim(),
            team_id: this.teamId(),
            steps: this.steps(),
          });
      this.editing.set(rotation!.id);
      await this.refreshList();
    } catch (err) {
      // The API's refusal is shown verbatim: it names the offending characters and lists who
      // the team actually has, which is more useful than anything this page could invent.
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected edit(rotation: RotationRead): void {
    this.editing.set(rotation.id);
    this.name = rotation.name;
    this.teamId.set(rotation.team_id);
    // Copied defensively. Nothing here mutates a step in place today — `setStep`, `move`
    // and `removeStep` all rebuild — so **removing this copy changes nothing observable**,
    // and there is deliberately no test for it: the mutation survived, which means any test
    // claiming to hold it would be one that cannot fail.
    this.steps.set(rotation.steps.map((step) => ({ ...step })));
    this.compiled.set(null);
    this.actionError.set(null);
  }

  protected newRotation(): void {
    this.editing.set(null);
    this.name = '';
    this.steps.set([]);
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
   * Only a *saved* rotation can be compiled — the endpoint reads the stored steps. Offering
   * it on unsaved edits would show the config for the last save while the screen displayed
   * something else, which is the "a number that looks right but refers to something else"
   * failure this project keeps meeting.
   */
  protected async compile(): Promise<void> {
    const id = this.editing();
    if (!id) return;
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
