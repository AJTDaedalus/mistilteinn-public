import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import type { ConditionGroup } from '../../sim/formula-calibration';
import {
  defaultWhy, hitMove, type ConditionValue, type FormulaCondition,
} from '../../sim/formula-recipe';
import type { FormulaMove } from '../../sim/recipe';
import {
  FormulaEstimateService,
  type TargetRow,
} from '../../pages/optimize/formula-estimate.service';
import type { AvailableHit, RefusedHit } from '../../pages/explain/explain.service';
import { RefusedHits } from '../refused-hits/refused-hits';

const MOVES: { value: FormulaMove; label: string }[] = [
  { value: 'normal', label: 'Normal attack' },
  { value: 'charged', label: 'Charged / aimed' },
  { value: 'plunge', label: 'Plunge' },
  { value: 'skill', label: 'Skill' },
  { value: 'burst', label: 'Burst' },
];

/** `normal_attack` → `Normal attack`. */
function talentName(raw: string): string {
  const spaced = raw.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The formula target and the assumptions it rests on — one panel, shared by Optimize, Rank and
 * Upgrade (math-fallback P1, task 8; `DESIGN_team_math_fallback.md` §2.5).
 *
 * **The target** is one or more abilities, each with a count (GO's multi-target: Σ count × hit)
 * and the move it is, which decides which move-scoped bonuses reach it. Refused rows are shown
 * disabled in each picker and named with their reason below it, never dropped (owner,
 * 2026-11-13).
 *
 * **The assumptions** are every conditional from the team's resonance, the sets in scope and
 * each member's kit sheet (P2: a kit says whether it is verified against GO, and a member with
 * no sheet is named as contributing no kit buffs),
 * each a visible control showing its default and why — self-triggered on (at max), situational
 * off (owner, 2026-11-13) — and the source it is cited to; then, after a run, every assumption
 * the recipe itself listed. A number that cannot say what it assumed is the thing this repo
 * refuses.
 */
@Component({
  selector: 'formula-panel',
  imports: [RefusedHits],
  templateUrl: './formula-panel.html',
  styleUrl: './formula-panel.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FormulaPanel {
  private readonly service = inject(FormulaEstimateService);

  readonly hits = input<readonly AvailableHit[]>([]);
  readonly refusedHits = input<readonly RefusedHit[]>([]);
  /** The conditions the team and sets in scope expose. */
  readonly groups = input<readonly ConditionGroup[]>([]);
  /** The last estimate's own assumptions; empty before a run. */
  readonly assumptions = input<readonly string[]>([]);
  /** Sets whose 4-piece the estimate could not score, already named. */
  readonly withheld = input<readonly string[]>([]);

  protected readonly moves = MOVES;
  protected readonly rows = this.service.rows;
  protected readonly teamState = this.service.conditionals;

  protected readonly hitGroups = computed(() => {
    const groups: { talent: string; items: AvailableHit[]; refused: RefusedHit[] }[] = [];
    const groupFor = (raw: string) => {
      const talent = talentName(raw);
      let group = groups.find((g) => g.talent === talent);
      if (!group) groups.push((group = { talent, items: [], refused: [] }));
      return group;
    };
    for (const hit of this.hits()) groupFor(hit.talent).items.push(hit);
    for (const row of this.refusedHits()) groupFor(row.talent).refused.push(row);
    return groups;
  });

  /** Whether the groups say anything about kits (P2): then they, not a blanket line, do. */
  protected readonly hasKits = computed(() => this.groups().some((g) => g.kind !== undefined));

  /** Groups that carry a control, for the per-row overrides. */
  protected readonly conditional = computed(
    () => this.groups().filter((g) => g.conditions.length > 0),
  );

  /**
   * A hit's identity in the picker. **All three parts**: `index` is the part within one
   * labelled row (`2-Hit DMG` has parts 0 and 1), so `talent#index` collided across every row
   * of a talent and the closed select showed whichever colliding option came last — found
   * driving Kachina, whose target read "Low/High Plunge DMG" over a 1-Hit row.
   */
  protected hitKey(hit: { talent: string; label: string; index: number }): string {
    return `${hit.talent}#${hit.label}#${hit.index}`;
  }

  protected pickHit(row: TargetRow, key: string): void {
    const hit = this.hits().find((h) => this.hitKey(h) === key);
    if (!hit) return;
    const fresh = { talent: hit.talent, label: hit.label, index: hit.index };
    // **The move belongs to the hit it was set for.** Kept across a change of ability, a row
    // first made for a 1-Hit DMG and switched to a burst's slash stayed a normal attack, so a
    // burst-scoped kit buff (Skirk's Serpent's Subtlety) silently missed it — found driving it.
    this.service.updateRow(row.id, {
      hit: fresh, label: hit.label, move: hitMove(hit),
    });
  }

  protected pickMove(row: TargetRow, value: string): void {
    this.service.updateRow(row.id, {
      move: MOVES.some((m) => m.value === value) ? value as FormulaMove : null,
    });
  }

  /**
   * On `change`, and an emptied or non-positive box keeps the last value: `Number('')` is 0,
   * and a count of 0 is refused by the recipe rather than read as "this row does nothing".
   */
  protected setCount(row: TargetRow, box: HTMLInputElement): void {
    const value = Number(box.value);
    if (box.value.trim() !== '' && Number.isFinite(value) && value > 0) {
      this.service.updateRow(row.id, { count: value });
    } else {
      box.value = String(row.count);
    }
  }

  protected add(): void {
    const first = this.hits()[0];
    if (first) this.service.addRow(first);
  }

  protected remove(row: TargetRow): void {
    this.service.removeRow(row.id);
  }

  protected key(group: ConditionGroup, condition: FormulaCondition): string {
    return `${group.sourceId}/${condition.key}`;
  }

  protected valueOf(group: ConditionGroup, condition: FormulaCondition): ConditionValue {
    return this.teamState()[this.key(group, condition)] ?? condition.default;
  }

  protected isDefault(group: ConditionGroup, condition: FormulaCondition): boolean {
    return this.valueOf(group, condition) === condition.default;
  }

  protected defaultText(condition: FormulaCondition, group?: ConditionGroup): string {
    const shown = condition.kind === 'toggle'
      ? (condition.default ? 'on' : 'off')
      : condition.default === '' ? 'none' : String(condition.default);
    // A kit's own condition is triggered by the character, not by whoever wears a set.
    const who = group?.kind === 'kit' ? 'the character triggers it' : 'the wearer triggers it';
    return `Default ${shown} — ${defaultWhy(condition, who)}`;
  }

  protected stackChoices(condition: FormulaCondition): number[] {
    const max = condition.max ?? 0;
    return Array.from({ length: Math.max(max, 0) + 1 }, (_, i) => i);
  }

  protected setToggle(group: ConditionGroup, condition: FormulaCondition, on: boolean): void {
    this.service.setCondition(this.key(group, condition), on ? 1 : 0);
  }

  protected setChoice(group: ConditionGroup, condition: FormulaCondition, raw: string): void {
    const value = condition.kind === 'choice' ? raw : Number(raw);
    this.service.setCondition(this.key(group, condition), value);
  }

  protected setNumber(group: ConditionGroup, condition: FormulaCondition, box: HTMLInputElement): void {
    const value = Number(box.value);
    const max = condition.max ?? Infinity;
    if (box.value.trim() !== '' && Number.isFinite(value) && value >= 0 && value <= max) {
      this.service.setCondition(this.key(group, condition), value);
    } else {
      box.value = String(this.valueOf(group, condition));
    }
  }

  protected reset(): void {
    this.service.resetConditions();
  }

  /** A row's override as the select reads it: `''` for "team setting". */
  protected overrideOf(row: TargetRow, group: ConditionGroup, condition: FormulaCondition): string {
    const value = row.overrides[this.key(group, condition)];
    return value === undefined ? '' : `v:${value}`;
  }

  /** The values one override select offers, as `[value, label]`. */
  protected overrideChoices(condition: FormulaCondition): [string, string][] {
    switch (condition.kind) {
      case 'toggle':
        return [['v:1', 'On'], ['v:0', 'Off']];
      case 'choice':
        return [['v:', 'None'], ...(condition.options ?? []).map(
          (o): [string, string] => [`v:${o}`, o],
        )];
      default:
        return this.stackChoices(condition).map((n): [string, string] => [`v:${n}`, String(n)]);
    }
  }

  protected setOverride(
    row: TargetRow, group: ConditionGroup, condition: FormulaCondition, raw: string,
  ): void {
    if (raw === '') {
      this.service.overrideRow(row.id, this.key(group, condition), undefined);
      return;
    }
    const text = raw.slice(2);
    const value = condition.kind === 'choice' ? text : Number(text);
    this.service.overrideRow(row.id, this.key(group, condition), value);
  }
}
