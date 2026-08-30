import {
  ChangeDetectionStrategy, Component, ElementRef, computed, inject, input, output, signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../../api/api-error';
import { CardPicker } from '../../../shared/card-picker/card-picker';
import { ElementChip } from '../../../shared/element/element';
import { CatalogueIcon } from '../../../shared/icon/icon';
import { EntityToken } from '../../../shared/token/token';
import { rosterOptions } from '../../../shared/team-scope';
import { configError, sampleError, type GcsimModule } from '../../../sim/gcsim';
import { loadGcsim } from '../../../sim/gcsim-loader';
import { onFieldIntervals, type OnFieldInterval } from '../../../sim/sample-timeline';
import { RotationTimeline } from '../timeline/timeline';
import {
  RotationsService,
  type ActionOffer,
  type RosterCharacter,
  type RotationAction,
  type RotationRead,
  type RotationStep,
  type TeamRoster,
} from '../rotations.service';
import { regroup } from './regroup';

/**
 * Authoring one rotation: the palette, the timeline, the step list and one move's detail.
 *
 * The owner's ruling started this: *"gcsim uses a convoluted rotation syntax, something more
 * like fairy would be a big improvement."* The improvement is not a prettier text box — it is
 * that **the two mistakes gcsim makes silently cannot be expressed here.** A bare action list
 * runs once; `while 1` deadlocks on an ungated action. Both produce a config gcsim accepts and
 * reports on, with exactly one burst in it. The compiler emits the loop and the gating, and a
 * user cannot name a character who is not on the team, because the picker is populated from
 * the roster the write path validates against.
 *
 * The gcsim config is on screen for the same reason: a compiler nobody can inspect is a
 * compiler nobody can check, and the complaint was about a syntax that hides what it does.
 *
 * ## Three levels, two signals
 *
 * `DESIGN_rotation_builder_gui.md` §2 — timeline, then the rotation list, then the detail of
 * one move. All three are pure functions of `steps()` and `selection()`, and there is no third
 * source of truth to drift: the failure this repo keeps meeting is two representations that
 * can disagree, and #184 found every `<select>` in this very editor showing option zero with
 * 418 tests passing.
 */
@Component({
  selector: 'rotation-editor',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, CardPicker, CatalogueIcon, ElementChip, EntityToken, RotationTimeline],
  templateUrl: './editor.html',
  styleUrl: './editor.scss',
})
export class RotationEditor {
  /** Every team the caller has, with its roster. The editor never fetches them itself. */
  readonly teams = input.required<TeamRoster[]>();

  /** A rotation was created or updated. The page reloads its own list. */
  readonly saved = output<void>();

  private readonly rotations = inject(RotationsService);

  /** Non-null means one *action* failed — a save, a paste, a compile. */
  protected readonly actionError = signal<string | null>(null);
  protected readonly teamId = signal('');
  /**
   * A **signal**, because `canSave` reads it.
   *
   * As a plain field it was invisible to the computed: Angular tracks signal reads, so typing
   * a name never invalidated `canSave` and the button stayed disabled until something *else*
   * in it changed. Picking a slot after typing worked; typing after picking did not, which
   * reads as "the button does not work".
   */
  protected readonly name = signal('');
  protected readonly steps = signal<RotationStep[]>([]);
  /** The rotation being edited, or null while composing a new one. */
  protected readonly editing = signal<string | null>(null);
  protected readonly compiled = signal<string | null>(null);
  /** What the server holds for `editing()`, so unsaved edits are detectable. */
  private readonly stored = signal('');

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

  /** Name and steps as one comparable string. Order is part of it — order *is* the rotation. */
  private snapshot(): string {
    return JSON.stringify({ name: this.name().trim(), steps: this.steps() });
  }

  protected readonly teamOptions = computed(() => rosterOptions(this.teams()));

  protected pickTeam(ids: readonly string[]): void {
    this.selectTeam(ids[0] ?? '');
  }

  // ── the editor, as a pop-up (BACKLOG_frontend §1's second pattern) ────────
  //
  // "New rotation" is a button that opens one, and the saved teams are the page. The editor
  // used to hold two thirds of the width permanently, which is why the list beside it was a
  // narrow column — the same inversion Builds got in #170.

  private readonly dialog = viewChild<ElementRef<HTMLDialogElement>>('dialog');

  /**
   * Open the editor on a saved rotation, or on a blank one.
   *
   * Called by the page through a `viewChild`, so the `<dialog>` stays in the template that
   * fills it — a native dialog brings focus trapping, Escape and a backdrop, none of which a
   * hand-rolled panel gets for free.
   */
  open(rotation: RotationRead | null): void {
    if (rotation === null) this.newRotation();
    else this.load(rotation);
    // **A team, or the dialog opens claiming one has no builds.** The page used to default
    // this in `load()`; the split moved `teamId` here and left nothing setting it, so "New
    // rotation" opened on `teamId === ''`, `roster()` was empty, and the editor said *"That
    // team has no builds yet, so there is nobody to act"* about a team nobody had chosen.
    if (this.teamId() === '' && this.teams().length > 0) {
      this.teamId.set(this.teams()[0].id);
    }
    // `showModal?.()`: absent in jsdom, and a bare call is a TypeError thrown from a click
    // handler — which takes the page out rather than failing the one control.
    this.dialog()?.nativeElement.showModal?.();
  }

  protected close(): void {
    this.dialog()?.nativeElement.close?.();
  }

  protected selectTeam(id: string): void {
    if (id === this.teamId()) return;
    // Steps name characters on the old team, so keeping them would build a rotation the API
    // refuses on save — with the user's own selections cited back at them as invalid.
    this.teamId.set(id);
    this.steps.set([]);
    this.selection.set(null);
    this.measured.set(null);
    this.compiled.set(null);
  }

  // ── the measured timeline (T.8) ───────────────────────────────────────────

  /**
   * One `sample()` run's on-field intervals, or null for the authored view.
   *
   * **Behind a button, never automatic** (owner ruling). A sample costs 2.3 s for a real
   * four-character rotation — measured, and with no browser penalty — which is a spinner
   * rather than a job, but it is still someone's laptop and they decide when to spend it.
   */
  protected readonly measured = signal<OnFieldInterval[] | null>(null);
  protected readonly sampling = signal(false);
  protected readonly sampleError = signal<string | null>(null);

  /**
   * Compile the steps on screen, run them once, and draw what actually happened.
   *
   * The config comes from the **server's** preview — the same `compile_rotation` a save would
   * use — rather than from a second compiler in TypeScript. `DESIGN_rotation_builder.md` B.5
   * settled that: the readiness gates a client-side compiler would have to reimplement are
   * exactly what stop gcsim's two silent failures.
   */
  protected runSample(): Promise<void> {
    return this.runSampleWith(null);
  }

  /**
   * The body of `runSample`, with the wasm module as a seam.
   *
   * A unit test needs to drive gcsim's *failure* shapes, and loading a 40 MB binary to do it
   * would make the test slower than the feature. `runSample()` is what the template calls.
   */
  protected async runSampleWith(module: GcsimModule | null): Promise<void> {
    if (this.steps().length === 0 || !this.teamId()) return;
    this.sampling.set(true);
    this.sampleError.set(null);
    try {
      const config = await this.rotations.preview(this.teamId(), this.steps(), true);
      const mod = module ?? await loadGcsim();
      const rejected = configError(mod.validateConfig(config));
      if (rejected !== null) throw new Error(`gcsim rejected the config: ${rejected}`);
      // A fixed seed. gcsim rolls crit, so a run repeated at a different seed moves for a
      // reason that has nothing to do with the rotation — and the timeline's whole claim is
      // that what changed on it is what the author changed.
      const raw = mod.sample(config, '1');
      // **`sample()` reports failure by returning `{"error": …}`, not by throwing** —
      // `cmd/wasm/main.go` marshals the error like any other result. `JSON.parse` succeeds, the
      // parsed object has no `logs`, and the timeline would have entered measured mode and
      // said *"Nothing executed. Every step's readiness gate stayed closed"* about a run that
      // never started. That is the wrong sentence for the failure this repo has already been
      // bitten by — `requested next char X is not active and next action is not swap` — and it
      // is the same shape `simulationError` exists for on `simulate()`.
      const failure = sampleError(raw);
      if (failure !== null) throw new Error(`gcsim failed to run this rotation: ${failure}`);
      const parsed = JSON.parse(raw) as Parameters<typeof onFieldIntervals>[0];
      this.measured.set(onFieldIntervals(parsed));
    } catch (err) {
      // Surfaced, never swallowed — and **an `Error` is not an API error**. `apiErrorMessage`
      // understands FastAPI's `{detail}` and otherwise falls through to `JSON.stringify`,
      // whose answer for an `Error` is `"{}"`: its properties are not enumerable. So every
      // gcsim failure rendered as two braces in a red box.
      this.sampleError.set(err instanceof Error ? err.message : apiErrorMessage(err));
      this.measured.set(null);
    } finally {
      this.sampling.set(false);
    }
  }

  // ── copy and paste (T.7) ──────────────────────────────────────────────────
  //
  // `DESIGN_rotation.md` §2 refused nesting with a promise — *"the list is short and a UI can
  // duplicate a selection"* — that no UI had ever kept. This keeps it. Groups (§27) are the
  // other half and do a different job: a group says *this chunk repeats*, copy/paste says
  // *this fragment is reusable somewhere else*.

  /** The copied steps. Survives switching rotations, which is most of the point. */
  protected readonly clipboard = signal<RotationStep[]>([]);

  protected copySelection(): void {
    const span = this.selection();
    if (!span) return;
    const chunk = this.steps().slice(span.start, span.end + 1).map((s) => ({ ...s }));
    this.clipboard.set(chunk);
    // The system clipboard as well as the internal one, so a chunk pastes into another tab.
    // Best-effort: `navigator.clipboard` is absent in jsdom and blocked without a user
    // gesture in some browsers, and failing to copy internally because of that would be the
    // convenience breaking the feature.
    void navigator.clipboard?.writeText?.(JSON.stringify({ mistilteinnSteps: chunk }))
      ?.catch(() => undefined);
  }

  /**
   * Paste after the selection, or at the end.
   *
   * A pasted step naming a character the destination team does not have is **kept and
   * flagged**, never silently dropped — `DESIGN_rotation.md` OQ-R2's ruling for every
   * unresolvable reference in this repo. Dropping it would delete the user's work to make a
   * save succeed.
   */
  protected pasteClipboard(): void {
    const chunk = this.clipboard();
    if (chunk.length === 0) return;
    const span = this.selection();
    const at = span ? span.end + 1 : this.steps().length;
    // Pasted steps land ungrouped. A fragment lifted out of a group is not that group, and
    // carrying the id across would silently extend a repeat the user did not ask for — or
    // split one, which the schema refuses on save.
    const pasted = chunk.map((step) => ({ ...step, group: '', group_repeat: 1 }));
    // `regroup` for the same reason a drag needs it: pasting into the middle of a group leaves
    // it in two places, which the save refuses and the preview would compile as the chunk
    // repeated twice. The pasted fragment stays ungrouped — a fragment lifted out of a group
    // is not that group, and joining would silently extend a repeat nobody asked for — so it
    // is the *host* group that is released.
    this.steps.update((steps) =>
      regroup([...steps.slice(0, at), ...pasted, ...steps.slice(at)]),
    );
    this.selection.set({ start: at, end: at + pasted.length - 1 });
    const absent = pasted
      .map((s) => s.character)
      .filter((id) => !this.roster().some((c) => c.nanoka_id === id));
    this.actionError.set(
      absent.length === 0
        ? null
        : `${absent.length} pasted step${absent.length === 1 ? '' : 's'} name a character `
          + `this team does not have. They are kept as pasted — remove them, or paste into a `
          + `rotation for the right team.`,
    );
    this.touched();
  }

  /** Ctrl/Cmd+C and Ctrl/Cmd+V. The buttons exist too — a chord is invisible and phoneless. */
  protected onEditorKey(event: KeyboardEvent): void {
    if (!event.ctrlKey && !event.metaKey) return;
    const target = event.target as HTMLElement | null;
    // Never steal a chord from a field the user is typing in: copying a rotation when they
    // meant to copy the text of a note would be the editor overriding the browser.
    const tag = target?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return;
    if (event.key === 'c') {
      // **And never when there is text selected.** The compiled gcsim config is a `<pre>`
      // inside this same dialog and is the main artifact of the page; a user who highlights it
      // and presses Ctrl+C was copying that, not their step selection. Cancelling the
      // browser's copy *and* overwriting the clipboard with step JSON is the worst of both,
      // and it left no keyboard way to copy the config at all.
      if (!document.getSelection()?.isCollapsed) return;
      if (this.selection() === null) return;
      event.preventDefault();
      this.copySelection();
    } else if (event.key === 'v') {
      if (this.clipboard().length === 0) return;
      event.preventDefault();
      this.pasteClipboard();
    }
  }

  // ── groups (T.7b) ─────────────────────────────────────────────────────────

  /** Whether the selection is exactly one whole group, so the button can say "ungroup". */
  protected readonly selectionIsGroup = computed(() => {
    const span = this.selection();
    if (!span) return false;
    const steps = this.steps();
    const group = steps[span.start]?.group;
    if (!group) return false;
    return steps.every((step, i) =>
      (i >= span.start && i <= span.end) === (step.group === group),
    );
  });

  /**
   * The selected group's repeat count, or 1.
   *
   * **Not `selectedStep()?.group_repeat`.** That is null unless exactly one step is selected,
   * and a group needs at least two — so the one control that edits this value could never
   * display it. It showed 1, and snapped back to 1 the moment you typed, while the timeline's
   * badge showed what you had actually set.
   */
  protected readonly selectedGroupRepeat = computed(() => {
    const span = this.selection();
    if (!span) return 1;
    return this.steps()[span.start]?.group_repeat ?? 1;
  });

  protected readonly canGroup = computed(() => {
    const span = this.selection();
    if (!span || span.start === span.end) return false;
    return this.steps().slice(span.start, span.end + 1).every((s) => !s.group);
  });

  /** Wrap the selection in a group that repeats. `DECISIONS.md` §27. */
  protected groupSelection(repeat = 2): void {
    const span = this.selection();
    if (!span || !this.canGroup()) return;
    // The id has to be unique within the rotation and stable across a save. A counter over
    // the ids already present avoids both a collision and a dependency on a clock.
    const used = new Set(this.steps().map((s) => s.group).filter(Boolean));
    let n = 1;
    while (used.has(`g${n}`)) n += 1;
    const id = `g${n}`;
    this.steps.update((steps) => steps.map((step, i) =>
      i >= span.start && i <= span.end
        ? { ...step, group: id, group_repeat: repeat }
        : step,
    ));
    this.touched();
  }

  protected ungroupSelection(): void {
    const span = this.selection();
    if (!span) return;
    const group = this.steps()[span.start]?.group;
    if (!group) return;
    this.steps.update((steps) => steps.map((step) =>
      step.group === group ? { ...step, group: '', group_repeat: 1 } : step,
    ));
    this.touched();
  }

  /** Change how many times the selected group repeats. Every member carries the count. */
  protected setGroupRepeat(repeat: number): void {
    const span = this.selection();
    if (!span) return;
    const group = this.steps()[span.start]?.group;
    if (!group) return;
    const bounded = Math.min(20, Math.max(1, Math.trunc(repeat) || 1));
    this.steps.update((steps) => steps.map((step) =>
      step.group === group ? { ...step, group_repeat: bounded } : step,
    ));
    this.touched();
  }

  // ── inserting at a position (T.6) ─────────────────────────────────────────

  /** The ability being dragged out of the palette, or null. */
  protected readonly dragOffer = signal<{ character: string; action: RotationAction } | null>(null);

  protected onOfferDragStart(character: string, action: RotationAction): void {
    this.dragOffer.set({ character, action });
  }

  /**
   * A drop on the timeline: insert a new step there, or move an existing one.
   *
   * Two drag *sources* over one list. A drag from the palette **inserts**; a drag of a tile
   * **moves**. Which one is in flight is the only thing that decides, so the handler asks
   * rather than guessing from the drop position.
   */
  protected onTimelineDrop(index: number): void {
    const offer = this.dragOffer();
    if (offer) {
      this.insertStep(index, offer.character, offer.action);
      this.dragOffer.set(null);
      return;
    }
    this.onDrop(index);
  }

  /**
   * Insert a step at a position. The keyboard path and the drag path share it.
   *
   * `quickAdd` appends, and a drag has no keyboard equivalent — so without this, inserting in
   * the middle would be mouse-only. That is the gap #184 left when it added drag-to-reorder
   * and kept the arrows for exactly this reason.
   */
  protected insertStep(index: number, character: string, action: RotationAction): void {
    const steps = this.steps();
    const at = Math.max(0, Math.min(index, steps.length));
    // **A step dropped inside a group joins it.** Inserting an ungrouped step in the middle of
    // `g1` would leave `[g1, '', g1]` — a group in two places, which the save refuses with a
    // 422 the user cannot trace back to a drag, and which the preview would meanwhile compile
    // as the chunk repeated twice. Joining is what the drop looks like it does.
    const inside = steps[at - 1]?.group && steps[at - 1].group === steps[at]?.group
      ? steps[at]
      : null;
    this.steps.update((current) => [
      ...current.slice(0, at),
      {
        character,
        action,
        repeat: 1,
        note: '',
        group: inside?.group ?? '',
        group_repeat: inside?.group_repeat ?? 1,
      },
      ...current.slice(at),
    ]);
    this.selection.set({ start: at, end: at });
    this.touched();
  }

  /**
   * Add from the palette: **insert at the selection**, or append when nothing is selected.
   *
   * The keyboard equivalent of dragging an ability onto the timeline, and it has to be *these*
   * buttons rather than a separate "insert here" control — a single control can only carry one
   * action, and the one it carried was always `skill`, so no other move could be placed
   * mid-rotation without a mouse.
   */
  protected addOffer(action: RotationAction): void {
    const character = this.addingFor();
    if (!character) return;
    const span = this.selection();
    if (span) this.insertStep(span.start, character, action);
    else this.appendStep(character, action);
    this.addingFor.set(null);
  }

  // ── selection: one signal, three renderers ────────────────────────────────
  //
  // The owner's hierarchy is timeline → rotation list → move detail, and all three are pure
  // functions of `steps()` and this. The recurring failure in this repo is two representations
  // that can disagree — #184 found every `<select>` in this very editor showing option zero —
  // so there is no second source of truth to drift.

  /** The selected span, inclusive, or null. `start <= end` always. */
  protected readonly selection = signal<{ start: number; end: number } | null>(null);

  /** The one selected step, or null when the selection is empty or spans several. */
  protected readonly selectedStep = computed(() => {
    const span = this.selection();
    if (!span || span.start !== span.end) return null;
    return this.steps()[span.start] ?? null;
  });

  protected readonly selectedCount = computed(() => {
    const span = this.selection();
    return span ? span.end - span.start + 1 : 0;
  });

  protected onPick(event: { index: number; extend: boolean }): void {
    this.selection.update((current) => {
      if (!event.extend || !current) return { start: event.index, end: event.index };
      // Extend from the anchor, whichever side the new index falls on.
      const anchor = current.start;
      return {
        start: Math.min(anchor, event.index),
        end: Math.max(anchor, event.index),
      };
    });
  }

  /**
   * Everything that changes the steps goes through here.
   *
   * Three things must happen together and forgetting one is how a screen starts lying: the
   * cached compile is stale, the preview must be re-fetched, and **the measured timeline is
   * now of a rotation that no longer exists** (owner ruling, 2026-08-30). Dropping it on the
   * first edit is the same rule the gcsim preview has followed since #184.
   */
  private touched(): void {
    this.compiled.set(null);
    this.measured.set(null);
    this.schedulePreview();
  }

  /**
   * "Add step" — the first roster member's first move.
   *
   * It used to read a **global** action list off `/rotations/options`. Since T.3 the
   * vocabulary is per character, so that list was the only remaining consumer of a field the
   * editor no longer has any use for: `firstOfferFor` asks the character what they can do.
   */
  protected addStep(): void {
    const first = this.roster()[0];
    if (!first || (first.actions ?? []).length === 0) return;
    this.appendStep(first.nanoka_id, this.firstOfferFor(first));
  }

  /**
   * Append one step. The shared path, so the two ways to add one cannot drift.
   *
   * `DESIGN_rotation_builder.md` B.2 adds a second entry point — click a face, click an
   * action — and two `steps.update` calls would eventually initialise a step differently.
   */
  protected appendStep(character: string, action: RotationAction): void {
    this.steps.update((steps) => [
      ...steps, { character, action, repeat: 1, note: '', group: '', group_repeat: 1 },
    ]);
    this.touched();
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

  /**
   * What this character can be given, as the palette draws it.
   *
   * From `/rotations/options`, per character, so the picker and the validator cannot disagree
   * — the guarantee `RotationOptions` has always made, now made per character because a hold-E
   * exists for 55 of gcsim's 117 characters and not for the rest.
   */
  protected offersFor(member: RosterCharacter): ActionOffer[] {
    return member.actions ?? [];
  }

  protected offersForId(nanokaId: string): ActionOffer[] {
    return this.roster().find((c) => c.nanoka_id === nanokaId)?.actions ?? [];
  }

  /** The first offer, for the keyboard insert's default. */
  protected firstOfferFor(member: RosterCharacter): RotationAction {
    return (member.actions?.[0]?.action ?? 'attack') as RotationAction;
  }

  /** The move in words — the channel the badge and the colour are not. */
  protected offerLabel(offer: ActionOffer): string {
    return offer.variant ? `${offer.name} (${offer.variant.replace('_', ' ')})` : offer.name;
  }

  /** `hold` → `h`, `short_hold` → `s`, `recast` → `r`. */
  protected variantBadge(variant: string): string {
    return variant === 'short_hold' ? 's' : variant.charAt(0);
  }

  /** The acting character's name, or their id when the team no longer holds them. */
  protected characterName(nanokaId: string): string {
    return this.roster().find((c) => c.nanoka_id === nanokaId)?.name ?? nanokaId;
  }

  /** What this step does, named the way the player knows it — with the variant spelled out. */
  protected actionLabel(step: RotationStep): string {
    const offer = this.offersForId(step.character).find((o) => o.action === step.action);
    return offer ? this.offerLabel(offer) : step.action;
  }

  /** The whole row as one sentence, for the accessible name on the select button. */
  protected stepLabel(step: RotationStep): string {
    const repeat = step.repeat > 1 ? ` ×${step.repeat}` : '';
    return `${this.characterName(step.character)} — ${this.actionLabel(step)}${repeat}`;
  }

  protected isSelected(index: number): boolean {
    const span = this.selection();
    return span !== null && index >= span.start && index <= span.end;
  }

  /** Duplicate a step in place — what `DESIGN_rotation.md` §2 promised a UI would do. */
  protected duplicateStep(index: number): void {
    this.steps.update((steps) => [
      ...steps.slice(0, index + 1),
      { ...steps[index] },
      ...steps.slice(index + 1),
    ]);
    this.touched();
  }

  protected removeStep(index: number): void {
    this.steps.update((steps) => steps.filter((_, i) => i !== index));
    this.selection.set(null);
    this.touched();
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
    this.steps.set(regroup(next));
    this.touched();
  }

  /**
   * Move a step to an arbitrary index — what a drag reports (B.4).
   *
   * The arrows stay and are not a fallback: a drag has no keyboard equivalent, and this list
   * is reorderable with one hand on a phone and with a keyboard because both exist. Sharing
   * the tail of `move` would need `move` to take a destination, which is the same function
   * spelled twice; this is the general one and `move` is the ±1 case.
   */
  protected reorder(from: number, to: number): void {
    const steps = this.steps();
    if (from === to || from < 0 || to < 0 || from >= steps.length || to >= steps.length) return;
    const next = [...steps];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    this.steps.set(regroup(next));
    this.touched();
  }

  /** The step being dragged, or null. A signal so the row can show it is in flight. */
  protected readonly dragging = signal<number | null>(null);

  protected onDragStart(index: number): void {
    this.dragging.set(index);
  }

  protected onDrop(index: number): void {
    const from = this.dragging();
    this.dragging.set(null);
    if (from !== null) this.reorder(from, index);
  }

  protected setStep(index: number, patch: Partial<RotationStep>): void {
    this.steps.update((steps) =>
      steps.map((step, i) => (i === index ? { ...step, ...patch } : step)),
    );
    this.touched();
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
      this.saved.emit();
    } catch (err) {
      // The API's refusal is shown verbatim: it names the offending characters and lists who
      // the team actually has, which is more useful than anything this page could invent.
      this.actionError.set(apiErrorMessage(err));
    }
  }

  /** Fill the editor from a saved rotation. `open` shows the dialog around it. */
  private load(rotation: RotationRead): void {
    this.editing.set(rotation.id);
    this.name.set(rotation.name);
    this.teamId.set(rotation.team_id);
    // Copied defensively. Nothing here mutates a step in place today — `setStep`, `move`
    // and `removeStep` all rebuild — so **removing this copy changes nothing observable**,
    // and there is deliberately no test for it: the mutation survived, which means any test
    // claiming to hold it would be one that cannot fail.
    this.steps.set(rotation.steps.map((step) => ({ ...step })));
    this.stored.set(this.snapshot());
    // Select the first step rather than nothing. The detail pane is level three of the
    // hierarchy and it renders only for a selection, so opening on an empty one both hid the
    // level and made the dialog jump the first time anything was clicked.
    this.selection.set(rotation.steps.length > 0 ? { start: 0, end: 0 } : null);
    this.measured.set(null);
    this.compiled.set(null);
    this.actionError.set(null);
  }

  protected newRotation(): void {
    this.editing.set(null);
    this.name.set('');
    this.steps.set([]);
    this.stored.set('');
    this.selection.set(null);
    this.measured.set(null);
    this.compiled.set(null);
    this.actionError.set(null);
  }


  // ── the live preview (DESIGN_rotation_builder B.5) ───────────────────────
  //
  // The gates are what `DESIGN_rotation.md` §3.4 calls "the whole point" — they are what stops
  // a bare action list running once and `while 1` deadlocking on an ungated action. Seeing
  // them appear as the rotation is written is the difference between a compiler you trust and
  // one you hope about.

  /** Whether the preview pane is open. Off by default: it costs a request per edit. */
  protected readonly previewing = signal(false);
  protected readonly previewError = signal<string | null>(null);

  protected togglePreview(): void {
    this.previewing.update((on) => !on);
    if (this.previewing()) void this.refreshPreview();
    else this.compiled.set(null);
  }

  /**
   * Recompile the **unsaved** steps.
   *
   * Debounced, because it fires on every step edit and each call is a round trip that
   * validates a roster. 300 ms is long enough that holding an arrow key does not queue a
   * request per repeat, and short enough to feel like it is keeping up.
   */
  private previewTimer: ReturnType<typeof setTimeout> | null = null;

  protected schedulePreview(): void {
    if (!this.previewing()) return;
    if (this.previewTimer !== null) clearTimeout(this.previewTimer);
    this.previewTimer = setTimeout(() => void this.refreshPreview(), 300);
  }

  protected async refreshPreview(): Promise<void> {
    const teamId = this.teamId();
    if (!teamId) return;
    this.previewError.set(null);
    try {
      this.compiled.set(await this.rotations.preview(teamId, this.steps()));
    } catch (err) {
      // **Shown, not swallowed.** A refusal here names the step that cannot compile, which is
      // the most useful thing the preview can say — and a stale config left on screen beside
      // an edit that broke it would be the preview lying.
      this.compiled.set(null);
      this.previewError.set(apiErrorMessage(err));
    }
  }

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

}
