import { Component, computed, effect, inject, input, output, signal } from '@angular/core';

import type {
  DeclaredFunction, Diagnostic, RotationSourceRead, RotationTree,
} from '../rotations.service';
import { RotationsService } from '../rotations.service';
import { FunctionPalette } from './function-palette';

/**
 * The rotation as gcsim text, editable, with its diagnostics underneath.
 *
 * `TASKS_rotation_language.md` Phase 7 — **the phase that makes every rotation editable**.
 * Under the owner's earlier "buttons only" ruling the last 16 % of real configs were
 * uneditable and gated on a hard question; with text as a first-class surface
 * (`DECISIONS.md` §32) everything becomes editable as soon as parse and emit exist, and the
 * builder phases after this move work from typing to clicking rather than deciding whether a
 * rotation can be edited at all.
 *
 * Three rules the design turns on:
 *
 * - **The tree is the source of truth.** Text is parsed into one; the tree is what gets
 *   saved, compiled and scored. Nothing reads this textarea's value directly.
 * - **The last good tree is never destroyed.** Unparseable text is held as a draft and the
 *   previous tree stands until the source parses again. Losing a user's rotation because
 *   they were mid-word is the one failure this must not have.
 * - **It is a surface a user opens, not one they land in.** `available` is a fact about the
 *   rotation — whether the builder can render every node — rather than a preference.
 */
@Component({
  selector: 'app-source-view',
  standalone: true,
  imports: [FunctionPalette],
  templateUrl: './source-view.html',
  styleUrl: './source-view.scss',
})
export class SourceView {
  /** The team whose roster resolves character names. */
  readonly teamId = input.required<string>();
  /** The source to start from — usually `emit(tree)` for the rotation being edited. */
  readonly source = input<string>('');
  /** True when the builder cannot render every node, so this surface is the only way in. */
  readonly required = input<boolean>(false);

  /** A tree that parsed. Emitted only when the source is readable. */
  readonly parsed = output<RotationTree>();
  /**
   * The functions this rotation declares, so the builder can offer them as buttons.
   *
   * Owner's split, 2026-09-03: **authoring an `fn` stays text; calling one is a click.** A
   * body is control flow, which is why it needs text at all; a call is a name and some
   * arguments, which is exactly what the picker already deals in.
   */
  readonly functions = output<DeclaredFunction[]>();

  protected readonly text = signal('');
  /** What this rotation declares, kept so the palette can offer it beside the editor. */
  protected readonly declared = signal<DeclaredFunction[]>([]);
  protected readonly diagnostics = signal<Diagnostic[]>([]);
  protected readonly checking = signal(false);
  /** The last source that produced a tree, so a draft can be told apart from a saved state. */
  private readonly settled = signal('');

  private timer: ReturnType<typeof setTimeout> | undefined;

  private readonly rotations = inject(RotationsService);

  constructor() {
    effect(() => {
      const incoming = this.source();
      this.text.set(incoming);
      this.settled.set(incoming);
    });
  }

  /** Problems that stop the rotation running, as opposed to ones that only warn. */
  protected readonly errors = computed(
    () => this.diagnostics().filter((d) => d.severity === 'error'),
  );

  protected readonly warnings = computed(
    () => this.diagnostics().filter((d) => d.severity === 'warning'),
  );

  /** True while the editor holds text that has not parsed into a tree. */
  protected readonly draft = computed(() => this.text() !== this.settled());

  /**
   * Append a call at the end of the source.
   *
   * **Appended rather than inserted at a cursor.** A textarea's selection is not part of this
   * component's state, and guessing at it would put a call somewhere the user was not
   * looking. The end of the rotation is the one position that is never a surprise.
   */
  protected addCall(call: string): void {
    const current = this.text();
    const joined = current.endsWith('\n') || current === '' ? current : `${current}\n`;
    this.onInput(`${joined}${call}\n`);
  }

  protected onInput(value: string): void {
    this.text.set(value);
    // **Debounced, because every keystroke is a round trip.** The parser is Python and
    // deliberately not reimplemented here, so the cost of a keystroke is a request; 300 ms is
    // slow enough not to send one per letter and fast enough that a pause feels answered.
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.check(), 300);
  }

  private async check(): Promise<void> {
    const source = this.text();
    this.checking.set(true);
    try {
      const read = await this.rotations.validateSource(this.teamId(), source);
      // **Only accept the answer if it is still about what is on screen.** Responses can
      // arrive out of order, and applying a stale one would show diagnostics for text the
      // user has already changed — which reads as the editor being wrong rather than late.
      if (this.text() !== source) return;
      this.diagnostics.set(read.diagnostics ?? []);
      // Emitted even when the source has errors: a rotation can declare a usable function and
      // still have a problem elsewhere, and withholding the offer would punish the wrong half.
      this.declared.set(read.functions ?? []);
      this.functions.emit(read.functions ?? []);
      this.apply(read, source);
    } catch {
      // A failed request says nothing about the rotation. The last good tree stands.
      this.diagnostics.set([]);
    } finally {
      this.checking.set(false);
    }
  }

  private apply(read: RotationSourceRead, source: string): void {
    const blocking = (read.diagnostics ?? []).some((d) => d.severity === 'error');
    if (blocking) return;   // held as a draft; the previous tree stands
    this.settled.set(source);
    this.parsed.emit(read.tree);
  }
}
