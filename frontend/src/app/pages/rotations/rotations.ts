import {
  ChangeDetectionStrategy, Component, OnInit, computed, inject, signal, viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { CatalogueIcon } from '../../shared/icon/icon';
import { RotationEditor } from './editor/editor';
import { RotationLibrary } from './library/library';
import {
  RotationsService,
  type RotationRead,
  type TeamRoster,
} from './rotations.service';

/**
 * The saved rotations, grouped by the team they belong to.
 *
 * `BACKLOG_frontend.md` §1's second pattern: **the saved things are the page**, and "New
 * rotation" is a button that opens one. The editor used to hold two thirds of the width
 * permanently, which is why the list beside it was a narrow column — the same inversion Builds
 * got in #170.
 *
 * ## Three components, because there are three surfaces
 *
 * This class was 993 lines and held all of them: the list, the editor and the library, with
 * nothing but a comment saying which signal belonged to which. They share almost nothing —
 * the editor needs the teams, the library needs one team, and both tell this page when they
 * have written something so it can reload the list. That is the whole interface, and it is
 * two inputs and two outputs.
 */
@Component({
  selector: 'page-rotations',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, CatalogueIcon, RotationEditor, RotationLibrary],
  templateUrl: './rotations.html',
  styleUrl: './rotations.scss',
})
export class RotationsPage implements OnInit {
  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no rotations". */
  protected readonly error = signal<string | null>(null);
  /** Non-null means one *action* failed — a delete. Saves are the editor's to report. */
  protected readonly actionError = signal<string | null>(null);

  protected readonly teams = signal<TeamRoster[]>([]);
  /** Which row the editor is open on, so the list can mark it. The editor owns the rest. */
  protected readonly editing = signal<string | null>(null);
  protected readonly saved = signal<RotationRead[]>([]);

  private readonly rotations = inject(RotationsService);
  private readonly editor = viewChild.required(RotationEditor);
  private readonly library = viewChild.required(RotationLibrary);

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


  protected summarise(rotation: RotationRead): string {
    const steps = rotation.steps.length;
    const actions = rotation.steps.reduce((total, step) => total + (step.repeat ?? 1), 0);
    return `${steps} step${steps === 1 ? '' : 's'} · ${actions} actions`;
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
      this.teams.set(options.teams);
      this.saved.set(list.items);
    } catch {
      // Surfaced, not swallowed. An empty page and a broken one look identical on screen, and
      // only one of them means "you have no teams yet".
      this.error.set('Could not load the rotation editor.');
      this.teams.set([]);
      this.saved.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  protected startNew(): void {
    this.editing.set(null);
    this.editor().open(null);
  }

  protected edit(rotation: RotationRead): void {
    this.editing.set(rotation.id);
    this.editor().open(rotation);
  }

  protected openLibrary(team: TeamRoster): void {
    void this.library().open(team);
  }

  protected async remove(rotation: RotationRead): Promise<void> {
    this.actionError.set(null);
    try {
      await this.rotations.remove(rotation.id);
      if (this.editing() === rotation.id) this.editing.set(null);
      await this.refreshList();
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  /**
   * Reload after the editor saved or the library copied. Both say so; neither reaches in.
   *
   * **Caught, because this is fired from the template and nothing awaits it.** `save()` used
   * to call it inside its own `try`, so a failed reload surfaced; called as `(saved)="…"` an
   * unhandled rejection is all that happens, and the list quietly keeps showing the state
   * before the save — a rotation the server has, looking like it was never written.
   */
  protected async refreshList(): Promise<void> {
    try {
      this.saved.set((await this.rotations.list()).items);
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }
}
