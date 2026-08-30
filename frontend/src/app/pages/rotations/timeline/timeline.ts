import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { CatalogueIcon } from '../../../shared/icon/icon';
import type { OnFieldInterval } from '../../../sim/sample-timeline';
import type { RosterCharacter, RotationStep } from '../rotations.service';

/** One step, with everything a tile needs to draw it, and its index in the rotation. */
export interface Tile {
  index: number;
  step: RotationStep;
  name: string;
  ability: string;
  icon: string | null;
  variant: string | null;
  selected: boolean;
}

/** Consecutive steps by one character — a stretch of field time, and an implied swap at each edge. */
export interface Run {
  character: string;
  name: string;
  element: string;
  icon: string | null;
  tiles: Tile[];
  /** The group these steps belong to, or `''`. Uniform within a run by construction. */
  group: string;
  groupRepeat: number;
}

/** A measured stretch, as the band draws it. */
export interface MeasuredRun {
  key: string;
  start: number;
  end: number;
  actions: number;
  /** Percent of the run's width, so the band needs no pixel arithmetic in the template. */
  width: number;
  offset: number;
}

/**
 * The rotation as a timeline: who is on field, across the cycle.
 *
 * `DESIGN_rotation_builder_gui.md` §2. Level one of the owner's hierarchy — timeline, then the
 * rotation list, then the detail of one move.
 *
 * ## Two states, one component
 *
 * **Authored** — equal-width tiles, ordinal x-axis, instant, derived from `steps()` alone.
 * **Measured** — the same tiles' *runs* sized by real frames from one `sample()` call.
 *
 * They are one component with two inputs rather than two components, and that is the point: a
 * user pressing Run should watch their rotation *become* the real one. Two components would
 * drift into a second, prettier renderer that agreed with the first only by accident.
 *
 * The measured band draws **character stretches, not steps**, because that is what `sample()`
 * reports — on-field intervals derived from `char_index` transitions. Pretending it mapped
 * frames onto individual authored steps would be inventing a correspondence gcsim does not
 * give, and this repo's recurring failure is exactly a number that looks right and refers to
 * something else.
 *
 * ## Colour is never the only channel
 *
 * `ElementChip`'s rule, and it binds harder here: seven Genshin element hues include two blues
 * and two greens. Every run carries the element colour, the character's art **and** their name,
 * and every tile carries the ability's sprite with its name as a title and screen-reader text.
 *
 * ## What it deliberately does not do
 *
 * It does not draw a time axis in authored mode. `DESIGN_rotation.md` §2 removed timing so the
 * user is not put back into frame counting, and a tile's width in the authored view would be a
 * guess anyway: every step compiles to a `.ready` gate, so a step that is not ready is skipped
 * and has no length at all.
 */
@Component({
  selector: 'rotation-timeline',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CatalogueIcon],
  template: `
    <div class="timeline" [class.timeline--measured]="measured() !== null">
      @if (measured(); as intervals) {
        <p class="timeline__eyebrow">
          <!-- Stretches, not swaps: N stretches of field time are N-1 transitions, and the
               first one is not a swap. Checked against the run itself — gcsim logged 26
               explicit swap actions for the 27 stretches this derives. -->
          One run · {{ intervals.length }} stretch{{ intervals.length === 1 ? '' : 'es' }} ·
          {{ swaps() }} swap{{ swaps() === 1 ? '' : 's' }} ·
          {{ cycleCount() }} cycle{{ cycleCount() === 1 ? '' : 's' }}
        </p>
        <div class="band" role="img" [attr.aria-label]="measuredLabel()">
          @for (run of measuredRuns(); track $index) {
            <span
              class="band__run"
              [style.--element]="'var(--element-none)'"
              [style.width.%]="run.width"
              [attr.title]="run.key + ' · frames ' + run.start + '–' + run.end"
            >
              <span class="band__who">{{ run.key }}</span>
              <span class="band__frames mono">f{{ run.start }}</span>
            </span>
          } @empty {
            <!-- Not a blank box. A rotation whose every gate stayed closed is a real answer,
                 and saying so is the whole reason to run it. -->
            <p class="muted">
              Nothing executed. Every step's readiness gate stayed closed for the whole run.
            </p>
          }
        </div>
      } @else {
        <!-- Labelled in both states, because they are one component in two conditions and the
             difference matters: one is what you wrote, the other is what happened. -->
        <p class="timeline__eyebrow">As written · {{ steps().length }} steps</p>
        <ol class="runs" role="list">
          @for (run of runs(); track $index) {
            <li class="run" [style.--element]="elementVar(run.element)">
              <span class="run__who">
                <catalogue-icon [icon]="run.icon" [alt]="''" [size]="26" />
                <span class="run__name">{{ run.name }}</span>
                @if (run.group) {
                  <!-- The terseness a group buys, drawn. DECISIONS.md §27. -->
                  <span class="run__group">×{{ run.groupRepeat }}</span>
                }
              </span>
              <span class="run__tiles">
                @for (tile of run.tiles; track tile.index) {
                  <button
                    type="button"
                    class="tile"
                    [class.tile--selected]="tile.selected"
                    [attr.aria-pressed]="tile.selected"
                    [attr.aria-label]="tileLabel(tile)"
                    [attr.title]="tileLabel(tile)"
                    draggable="true"
                    (dragstart)="dragFrom.emit(tile.index)"
                    (dragover)="$event.preventDefault()"
                    (drop)="onDrop($event, tile.index)"
                    (click)="onPick($event, tile.index)"
                    (keydown)="onKey($event, tile.index)"
                  >
                    @if (tile.icon) {
                      <catalogue-icon [icon]="tile.icon" [alt]="''" [size]="38" />
                    } @else {
                      <span class="tile__word">{{ tile.ability }}</span>
                    }
                    @if (tile.variant) {
                      <!-- The owner's t/h. A badge, never the only channel: the word is in
                           the tile's label and in the detail pane below. -->
                      <span class="tile__badge" aria-hidden="true">{{ badge(tile.variant) }}</span>
                    }
                    @if (tile.step.repeat > 1) {
                      <span class="tile__repeat mono" aria-hidden="true">×{{ tile.step.repeat }}</span>
                    }
                  </button>
                }
              </span>
            </li>
          } @empty {
            <li class="muted">No steps yet — pick a character below to add one.</li>
          }
        </ol>
      }
    </div>
  `,
  styles: `
    :host { display: block; }

    .timeline { display: flex; flex-direction: column; gap: var(--space-2); }

    .timeline__eyebrow {
      margin: 0;
      color: var(--ink-dim);
      font-size: var(--text-xs);
      letter-spacing: 0.04em;
    }

    /* Wide content scrolls inside its own box; the dialog must never scroll sideways. */
    .runs, .band { display: flex; gap: var(--space-2); overflow-x: auto; padding-bottom: 2px; }
    .runs { list-style: none; margin: 0; padding: 0 0 2px; }

    .run {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      flex: 0 0 auto;
      padding: var(--space-2) var(--space-3);
      border: 1px solid color-mix(in srgb, var(--element) 45%, transparent);
      border-radius: var(--radius-2);
      background: color-mix(in srgb, var(--element) 10%, transparent);
    }

    .run__who { display: flex; align-items: center; gap: var(--space-1); min-width: 0; }
    .run__name { color: var(--ink); font-size: var(--text-sm); white-space: nowrap; }
    .run__group {
      padding: 0 var(--space-1);
      border-radius: var(--radius-1);
      background: var(--element);
      color: var(--surface);
      font-size: var(--text-xs);
    }

    .run__tiles { display: flex; gap: var(--space-1); }

    .tile {
      position: relative;
      display: grid;
      place-items: center;
      min-width: 52px;
      min-height: 52px;
      padding: 3px;
      border: 1px solid var(--surface-rule);
      border-radius: var(--radius-1);
      background: var(--surface);
      cursor: grab;
    }
    .tile--selected { outline: 2px solid var(--brass); outline-offset: 1px; }
    .tile__word {
      font-size: var(--text-xs);
      color: var(--ink-dim);
      padding: 0 3px;
      text-align: center;
      line-height: 1.2;
    }
    /* **Inside the tile, not hanging off it.** .runs scrolls horizontally, and
       overflow-x: auto makes the block axis a scroll container too — so a badge at
       inset: -4px was clipped away and rendered nowhere. The DOM had it, the spec asserted
       its text, and on screen there was nothing: found by taking a screenshot (T.9), which is
       the check this repo does not automate. */
    .tile__badge {
      position: absolute;
      inset-block-start: 0;
      inset-inline-end: 0;
      min-width: 13px;
      border-end-start-radius: var(--radius-1);
      background: var(--brass);
      color: var(--bg-deep);
      font-size: 10px;
      line-height: 13px;
      text-align: center;
    }
    .tile__repeat {
      position: absolute;
      inset-block-end: 0;
      inset-inline-end: 2px;
      font-size: 10px;
      line-height: 1;
      color: var(--ink-dim);
    }

    .band__run {
      flex: 0 0 auto;
      display: flex;
      flex-direction: column;
      min-width: 3ch;
      padding: var(--space-1);
      border-radius: var(--radius-1);
      background: color-mix(in srgb, var(--ink-faint) 25%, transparent);
      font-size: var(--text-xs);
    }
    .band__who { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .band__frames { color: var(--ink-dim); }
  `,
})
export class RotationTimeline {
  readonly steps = input.required<RotationStep[]>();
  readonly roster = input.required<RosterCharacter[]>();
  /** The selected span, inclusive, or `null`. One signal, three renderers read it. */
  readonly selection = input<{ start: number; end: number } | null>(null);
  /**
   * One run's on-field intervals, or `null` for the authored view.
   *
   * The page sets this to `null` on every edit (owner ruling): nothing on screen is ever
   * untrue, and the alternative was a dimmed band that is wrong on purpose.
   */
  readonly measured = input<OnFieldInterval[] | null>(null);

  readonly pick = output<{ index: number; extend: boolean }>();
  readonly dragFrom = output<number>();
  readonly dropOn = output<number>();

  protected readonly runs = computed<Run[]>(() => {
    const roster = this.roster();
    const selected = this.selection();
    const runs: Run[] = [];
    this.steps().forEach((step, index) => {
      const member = roster.find((c) => c.nanoka_id === step.character);
      const offer = member?.actions?.find((a) => a.action === step.action);
      const tile: Tile = {
        index,
        step,
        name: member?.name ?? step.character,
        ability: offer?.name ?? step.action,
        icon: offer?.icon ?? null,
        variant: offer?.variant ?? null,
        selected: selected !== null && index >= selected.start && index <= selected.end,
      };
      const last = runs[runs.length - 1];
      // A run breaks on a character change **or** a group boundary: a group is a chunk, and a
      // bracket drawn across two characters would suggest the repeat belonged to one of them.
      const continues =
        last
        && last.character === step.character
        && last.group === (step.group ?? '')
        && last.groupRepeat === (step.group_repeat ?? 1);
      if (continues) {
        last.tiles.push(tile);
        return;
      }
      runs.push({
        character: step.character,
        name: tile.name,
        element: member?.element ?? '',
        icon: member?.icon ?? null,
        tiles: [tile],
        group: step.group ?? '',
        groupRepeat: step.group_repeat ?? 1,
      });
    });
    return runs;
  });

  protected readonly measuredRuns = computed<MeasuredRun[]>(() => {
    const intervals = this.measured() ?? [];
    if (intervals.length === 0) return [];
    const last = intervals[intervals.length - 1];
    const span = Math.max(1, last.end - intervals[0].start);
    return intervals.map((interval) => ({
      key: interval.key || `character ${interval.character}`,
      start: interval.start,
      end: interval.end,
      actions: interval.actions,
      // A stretch of one action has zero span and would otherwise be invisible. `min-width`
      // in the stylesheet backs this up for the same reason.
      width: Math.max(4, ((interval.end - interval.start) / span) * 100),
      offset: interval.start,
    }));
  });

  /** Transitions between stretches. One stretch is no swap; the first is where you started. */
  protected readonly swaps = computed(() => Math.max(0, (this.measured() ?? []).length - 1));

  protected readonly cycleCount = computed(() => {
    const intervals = this.measured() ?? [];
    if (intervals.length === 0) return 0;
    const first = intervals[0].character;
    return intervals.filter((i) => i.character === first).length;
  });

  protected measuredLabel(): string {
    return this.measuredRuns()
      .map((r) => `${r.key} frames ${r.start} to ${r.end}`)
      .join(', ');
  }

  /** The tile's whole meaning as words — the channel the badge and the colour are not. */
  protected tileLabel(tile: Tile): string {
    const variant = tile.variant ? ` (${tile.variant.replace('_', ' ')})` : '';
    const repeat = tile.step.repeat > 1 ? ` ×${tile.step.repeat}` : '';
    return `Step ${tile.index + 1}: ${tile.name} — ${tile.ability}${variant}${repeat}`;
  }

  /** `hold` → `h`, `short_hold` → `s`, `recast` → `r`; a tap has none. */
  protected badge(variant: string): string {
    return variant === 'short_hold' ? 's' : variant.charAt(0);
  }

  protected elementVar(element: string): string {
    const known = ['anemo', 'cryo', 'dendro', 'electro', 'geo', 'hydro', 'pyro'];
    const name = element.toLowerCase();
    return known.includes(name) ? `var(--element-${name})` : 'var(--element-none)';
  }

  protected onPick(event: MouseEvent, index: number): void {
    this.pick.emit({ index, extend: event.shiftKey });
  }

  protected onKey(event: KeyboardEvent, index: number): void {
    // Shift-arrow extends, matching the mouse. A drag has no keyboard equivalent and this
    // list has to be selectable both ways — the reason #184 kept the reorder arrows.
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const next = index + (event.key === 'ArrowRight' ? 1 : -1);
    if (next < 0 || next >= this.steps().length) return;
    this.pick.emit({ index: next, extend: event.shiftKey });
  }

  protected onDrop(event: DragEvent, index: number): void {
    event.preventDefault();
    this.dropOn.emit(index);
  }
}
