import { Component, computed, input, output } from '@angular/core';

import type { RosterCharacter } from '../rotations.service';

type Node = Record<string, unknown>;

/** One row of a condition, as the dropdowns hold it. */
export interface ConditionRow {
  /** `&&` or `||`; empty on the first row. */
  join: string;
  subject: string;
  property: string;
  comparison: string;
  value: string;
}

/** What a character's state can be asked about, in the vocabulary the parser accepts. */
export interface PropertyOffer {
  /** `burst.ready`, `energy`, `status.manifest-flame`. */
  path: string;
  label: string;
  /** True when the property is a number and takes a comparison and a value. */
  numeric: boolean;
}

/** The base ten actions a readiness gate can name. Derived from the roster, never restated. */
export function propertiesFor(character: RosterCharacter | undefined): PropertyOffer[] {
  // **From the roster's own `actions`, never a list restated here.** `/options` publishes the
  // per-character vocabulary for exactly this reason: a hand-written copy would be the one
  // offering a readiness gate on a move the character does not have.
  const bases = [...new Set((character?.actions ?? []).map((offer) => offer.base))];
  const readiness = (bases.length ? bases : ['skill', 'burst']).map((action) => ({
    path: `${action}.ready`,
    label: `${action} is ready`,
    numeric: false,
  }));
  // **Energy is the one numeric property the parser accepts**, and it is the one that matters:
  // `DESIGN_conditional_steps.md`'s whole worked example is `.flins.energy >= 30`.
  return [...readiness, { path: 'energy', label: 'energy', numeric: true }];
}

const COMPARISONS = ['>=', '>', '==', '!=', '<', '<='];

/** Render the rows as the gcsim expression they mean. */
export function conditionText(rows: ConditionRow[]): string {
  return rows
    .filter((row) => row.subject && row.property)
    .map((row, index) => {
      const path = `.${row.subject}.${row.property}`;
      const test = row.comparison && row.value !== ''
        ? `${path} ${row.comparison} ${row.value}`
        : path;
      return index === 0 ? test : `${row.join || '&&'} ${test}`;
    })
    .join(' ');
}

/**
 * Everything about the selected node, in one place.
 *
 * `TASKS_rotation_language.md` Phase 10. This is the other half of the outline's density:
 * **nothing about a node is edited in its row**, which is what keeps a row one line and lets
 * a 180-step rotation fit on screen.
 *
 * The condition editor is dropdowns rather than a text field — subject, property, comparison,
 * value. That is still "buttons only" in the sense `DECISIONS.md` §32 preserves: nothing is
 * typed that could drift from a clickable vocabulary. A condition outside this vocabulary is
 * edited in the source view, which is what the source view is for.
 */
@Component({
  selector: 'app-node-inspector',
  standalone: true,
  templateUrl: './node-inspector.html',
  styleUrl: './node-inspector.scss',
})
export class NodeInspector {
  readonly node = input<Node | null>(null);
  readonly roster = input<RosterCharacter[]>([]);

  readonly repeatChange = output<number>();
  readonly noteChange = output<string>();
  readonly conditionChange = output<string>();
  readonly boundChange = output<number>();

  protected readonly comparisons = COMPARISONS;

  protected readonly kind = computed(() => String(this.node()?.['kind'] ?? ''));

  /** A carried node is read-only here, and the panel has to say why rather than look broken. */
  protected readonly carried = computed(() => this.kind() === 'raw');

  protected readonly repeat = computed(() => Number(this.node()?.['repeat'] ?? 1));
  protected readonly note = computed(() => String(this.node()?.['note'] ?? ''));

  /** gcsim parameters this builder offers no control for — shown, never edited. */
  protected readonly params = computed<[string, string][]>(() => {
    const params = this.node()?.['params'] as Record<string, string> | undefined;
    return Object.entries(params ?? {});
  });

  protected readonly bound = computed(() => {
    const bound = this.node()?.['bound'] as Node | undefined;
    return bound && bound['kind'] === 'literal' ? Number(bound['value']) : null;
  });

  protected readonly rows = computed<ConditionRow[]>(() => {
    const node = this.node();
    if (!node) return [];
    const source = node['kind'] === 'branch'
      ? (node['arms'] as [unknown, unknown][] | undefined)?.[0]?.[0]
      : node['condition'];
    return source ? flatten(source as Node) : [];
  });

  protected propertiesForRow(row: ConditionRow): PropertyOffer[] {
    return propertiesFor(this.roster().find((c) => keyOf(c) === row.subject));
  }

  protected isNumeric(row: ConditionRow): boolean {
    return this.propertiesForRow(row).find((p) => p.path === row.property)?.numeric ?? false;
  }

  protected keyOf = keyOf;

  protected setRow(index: number, patch: Partial<ConditionRow>): void {
    const rows = this.rows().map((row, i) => (i === index ? { ...row, ...patch } : row));
    this.conditionChange.emit(conditionText(rows));
  }

  protected addRow(): void {
    const rows = [
      ...this.rows(),
      { join: '&&', subject: '', property: '', comparison: '', value: '' },
    ];
    this.conditionChange.emit(conditionText(rows));
  }

  protected removeRow(index: number): void {
    this.conditionChange.emit(conditionText(this.rows().filter((_, i) => i !== index)));
  }
}

/** gcsim's key for a roster character, which is what a condition names. */
function keyOf(character: RosterCharacter): string {
  return character.name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/** Split an expression tree into the flat rows the dropdowns hold. */
function flatten(expression: Node, join = ''): ConditionRow[] {
  if (expression['kind'] === 'binary' && ['&&', '||'].includes(String(expression['op']))) {
    return [
      ...flatten(expression['left'] as Node, join),
      ...flatten(expression['right'] as Node, String(expression['op'])),
    ];
  }
  if (expression['kind'] === 'binary') {
    const left = expression['left'] as Node;
    const segments = (left['segments'] as string[]) ?? [];
    return [{
      join,
      subject: segments[0] ?? '',
      property: segments.slice(1).join('.'),
      comparison: String(expression['op']),
      value: String((expression['right'] as Node)?.['value'] ?? ''),
    }];
  }
  if (expression['kind'] === 'state') {
    const segments = (expression['segments'] as string[]) ?? [];
    return [{
      join,
      subject: segments[0] ?? '',
      property: segments.slice(1).join('.'),
      comparison: '',
      value: '',
    }];
  }
  return [];
}
