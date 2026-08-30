import {
  ChangeDetectionStrategy, Component, ElementRef, inject, output, signal, viewChild,
} from '@angular/core';

import { apiErrorMessage } from '../../../api/api-error';
import {
  RotationsService,
  type LibraryRotationRead,
  type TeamRoster,
} from '../rotations.service';

/**
 * Published rotations, as a pop-up over the team you are looking at.
 *
 * The owner's audit (`BACKLOG_frontend.md` §5): *"It belongs as the last option inside an
 * expanded team, opening a card-and-filter pop-up."* So it is not a page and not a tab — it is
 * the answer to a question you are already asking with a team open in front of you.
 *
 * **Its own component because it is its own surface.** It has six signals, a dialog, a scope
 * filter and two write paths of its own, and none of them is anything the rotation list or the
 * editor reads. Sharing a class with them meant three unrelated screens' state in one place,
 * where the only thing telling you which signal belonged to which was a comment.
 */
@Component({
  selector: 'rotation-library',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './library.html',
  styleUrl: './library.scss',
})
export class RotationLibrary {
  /** A copy landed. The page reloads its list rather than this guessing at its contents. */
  readonly copied = output<void>();

  private readonly rotations = inject(RotationsService);

  // question you are already asking when you have a team open in front of you.

  protected readonly team = signal<TeamRoster | null>(null);
  protected readonly rows = signal<LibraryRotationRead[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly note = signal<string | null>(null);
  /**
   * Whether the search is narrowed to the open team's characters.
   *
   * **Starts narrowed**, because that is the question being asked — a library reached from
   * inside a team is asking "what do people run on *this*". Widening has to be possible or
   * the control is a list rather than a search.
   */
  protected readonly forThisTeam = signal(true);

  private readonly dialog = viewChild<ElementRef<HTMLDialogElement>>('dialog');

  /** Opened by the page — `viewChild` on the parent, so the dialog stays with its content. */
  async open(team: TeamRoster): Promise<void> {
    this.team.set(team);
    this.forThisTeam.set(true);
    this.note.set(null);
    // `showModal?.()`: `HTMLDialogElement` is absent in jsdom, so a bare call is a TypeError
    // thrown from a click handler — which takes the page out rather than failing one control.
    this.dialog()?.nativeElement.showModal?.();
    await this.load();
  }

  protected close(): void {
    this.dialog()?.nativeElement.close?.();
  }

  protected async setScope(forThisTeam: boolean): Promise<void> {
    this.forThisTeam.set(forThisTeam);
    await this.load();
  }

  protected async load(): Promise<void> {
    const team = this.team();
    if (!team) return;
    this.loading.set(true);
    this.error.set(null);
    try {
      const page = await this.rotations.library({
        characters: this.forThisTeam()
          ? team.characters.map((c) => c.nanoka_id)
          : undefined,
      });
      this.rows.set(page.items);
    } catch {
      // Surfaced, not swallowed: an empty library and a failed request look identical on
      // screen, and only one of them means nobody has published anything.
      this.error.set('Could not load the rotation library.');
      this.rows.set([]);
    } finally {
      this.loading.set(false);
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
    const apply = (value: boolean) => this.rows.update((rows) =>
      rows.map((r) => (r.id === row.id
        ? { ...r, liked_by_me: value, like_count: r.like_count + (value ? 1 : -1) }
        : r)),
    );
    apply(liked);
    try {
      await this.rotations.setLiked(row.id, liked);
    } catch {
      apply(!liked);
      this.error.set('Could not save that.');
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
  protected async copy(row: LibraryRotationRead): Promise<void> {
    const team = this.team();
    if (!team) return;
    this.error.set(null);
    this.note.set(null);
    try {
      const made = await this.rotations.copy(row.id, team.id);
      this.note.set(`Copied as "${made.name}".`);
      // The page owns the saved list; telling it beats this component reaching into it.
      this.copied.emit();
      await this.load();
    } catch (err) {
      this.error.set(apiErrorMessage(err));
    }
  }
}
