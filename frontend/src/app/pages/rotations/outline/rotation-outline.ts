import { Component, computed, input, model, output, signal } from '@angular/core';

import type { RotationTree } from '../rotations.service';

/** One node flattened for display, with the depth it sits at and the path that reaches it. */
export interface OutlineRow {
  /** `[0]`, `[1, 'body', 0]` — the same path shape the backend's diagnostics carry. */
  path: (number | string)[];
  depth: number;
  kind: string;
  /** What the row reads as: `"noelle skill ×3"`, `"repeat 6"`, `"if .x.burst.ready"`. */
  label: string;
  /** A block's own children count, for the collapsed form. */
  children: number;
  /** Carried rather than understood — read-only, and marked as such. */
  carried: boolean;
}

type Node = Record<string, unknown>;

/**
 * Is `target` inside `source`, or the same node?
 *
 * **The one drop that must be refused.** Moving a block into its own body would detach the
 * subtree from the tree entirely — the node would become its own ancestor, and the rotation
 * that came back would be missing everything inside it. A path prefix check answers it
 * exactly: a descendant's path begins with its ancestor's.
 */
export function wouldDetach(
  source: (number | string)[], target: (number | string)[],
): boolean {
  if (source.length > target.length) return false;
  return source.every((part, index) => part === target[index]);
}


/** `path.join('/')` — a stable key for selection and collapse state. */
export function keyOf(path: (number | string)[]): string {
  return path.join('/');
}

function expressionText(expression: unknown): string {
  const node = expression as Node | null;
  if (!node) return '';
  switch (node['kind']) {
    case 'literal':
      return String(node['value']);
    case 'identifier':
      return String(node['name']);
    case 'state':
      return '.' + (node['segments'] as string[]).join('.');
    case 'unary':
      return `${node['op']}${expressionText(node['operand'])}`;
    case 'binary':
      return `${expressionText(node['left'])} ${node['op']} ${expressionText(node['right'])}`;
    default:
      return '';
  }
}

/** The one line a node reads as. Deliberately short: the outline is a record, not a form. */
export function labelOf(node: Node): string {
  switch (node['kind']) {
    case 'action': {
      const repeat = Number(node['repeat'] ?? 1);
      const params = node['params'] as Record<string, string> | undefined;
      const variant = params && Object.keys(params).length
        ? ` [${Object.entries(params).map(([k, v]) => `${k}=${v}`).join(',')}]`
        : '';
      return `${node['character']} ${node['action']}${variant}` +
        (repeat > 1 ? ` ×${repeat}` : '');
    }
    case 'loop':
      return node['loop'] === 'counted'
        ? `repeat ${expressionText(node['bound'])}`
        : `while ${expressionText(node['condition'])}`;
    case 'branch': {
      const arms = node['arms'] as [unknown, unknown][];
      const first = arms.length ? expressionText(arms[0][0]) : '';
      return `if ${first}`;
    }
    case 'wait':
      return `${node['mode']} ${node['frames']}f`;
    case 'swap':
      return `swap to ${node['character']}`;
    case 'let':
      return `let ${node['name']} = ${expressionText(node['value'])}`;
    case 'assign':
      return `${node['name']} = ${expressionText(node['value'])}`;
    case 'call':
      return `${node['function']}()`;
    case 'fn':
      return `function ${node['name']}(${(node['parameters'] as string[]).join(', ')})`;
    case 'raw':
      return String(node['source']).split('\n')[0].trim().slice(0, 60);
    default:
      return String(node['kind']);
  }
}

function childrenOf(node: Node): { key: (number | string)[]; nodes: Node[] }[] {
  if (node['kind'] === 'loop' || node['kind'] === 'fn') {
    return [{ key: ['body'], nodes: (node['body'] as Node[]) ?? [] }];
  }
  if (node['kind'] === 'branch') {
    const arms = (node['arms'] as [unknown, Node[]][]) ?? [];
    const out = arms.map((arm, index) => ({
      key: ['arms', index] as (number | string)[], nodes: arm[1] ?? [],
    }));
    const otherwise = node['otherwise'] as Node[] | null;
    if (otherwise) out.push({ key: ['otherwise'], nodes: otherwise });
    return out;
  }
  return [];
}

function countAll(nodes: Node[]): number {
  return nodes.reduce(
    (total, node) => total + 1 + childrenOf(node)
      .reduce((sub, child) => sub + countAll(child.nodes), 0),
    0,
  );
}

/** Flatten a tree into display rows, skipping the contents of collapsed blocks. */
export function rowsOf(
  nodes: Node[], collapsed: ReadonlySet<string>, prefix: (number | string)[] = [], depth = 0,
): OutlineRow[] {
  const rows: OutlineRow[] = [];
  nodes.forEach((node, index) => {
    const path = [...prefix, index];
    const children = childrenOf(node);
    rows.push({
      path,
      depth,
      kind: String(node['kind']),
      label: labelOf(node),
      children: children.reduce((total, child) => total + countAll(child.nodes), 0),
      carried: node['kind'] === 'raw',
    });
    if (collapsed.has(keyOf(path))) return;
    for (const child of children) {
      rows.push(...rowsOf(child.nodes, collapsed, [...path, ...child.key], depth + 1));
    }
  });
  return rows;
}

/**
 * The rotation as a dense indented outline — one line per node.
 *
 * `TASKS_rotation_language.md` Phase 8. The owner's reading of the old builder was that *"the
 * move list [is] the biggest element and [has] the least important features"*, and this is
 * the half of the answer that makes the list smaller: it is a **record** of decisions already
 * made, so it gets density rather than space. Nothing about a node is edited in its row —
 * that is the inspector's job, and it is what keeps a row one line.
 *
 * A `raw` node renders plainly marked and read-only. It has to be obvious that it is carried
 * rather than understood, because that is the difference between editing this rotation in the
 * builder and editing it as text.
 */
@Component({
  selector: 'app-rotation-outline',
  standalone: true,
  templateUrl: './rotation-outline.html',
  styleUrl: './rotation-outline.scss',
})
export class RotationOutline {
  readonly tree = input.required<RotationTree>();
  /** The selected node's path key, shared with the inspector. */
  readonly selected = model<string>('');
  readonly activated = output<(number | string)[]>();
  /** A requested move: take the node at `from` and put it before the node at `to`. */
  readonly moved = output<{ from: (number | string)[]; to: (number | string)[] }>();

  protected readonly dragging = signal<(number | string)[] | null>(null);
  protected readonly over = signal<string>('');

  /**
   * Which blocks are collapsed, as a signal of path keys.
   *
   * A signal of a new `Set` rather than a mutated one plus a version counter: a `Set` the
   * component mutates in place is invisible to change detection, and pairing it with a
   * counter is two things that can disagree about the same state.
   */
  protected readonly collapsed = signal<ReadonlySet<string>>(new Set());

  protected readonly rows = computed<OutlineRow[]>(() => {
    const nodes = (this.tree()?.nodes ?? []) as unknown as Node[];
    return rowsOf(nodes, this.collapsed());
  });

  protected isCollapsed(row: OutlineRow): boolean {
    return this.collapsed().has(keyOf(row.path));
  }

  protected toggle(row: OutlineRow): void {
    const key = keyOf(row.path);
    this.collapsed.update((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  protected select(row: OutlineRow): void {
    this.selected.set(keyOf(row.path));
    this.activated.emit(row.path);
  }

  /** Arrow keys move the selection; a rotation with 180 steps is not one to mouse through. */
  protected onKey(event: KeyboardEvent): void {
    const rows = this.rows();
    if (!rows.length) return;
    const at = rows.findIndex((row) => keyOf(row.path) === this.selected());
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.select(rows[Math.min(at + 1, rows.length - 1)] ?? rows[0]);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.select(rows[Math.max(at - 1, 0)] ?? rows[0]);
    } else if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && at >= 0) {
      const row = rows[at];
      if (row.children && this.isCollapsed(row) === (event.key === 'ArrowRight')) {
        event.preventDefault();
        this.toggle(row);
      }
    }
  }

  protected onDragStart(row: OutlineRow): void {
    this.dragging.set(row.path);
  }

  protected onDragOver(row: OutlineRow, event: DragEvent): void {
    const from = this.dragging();
    if (!from || wouldDetach(from, row.path)) {
      // No `preventDefault`, so the browser shows "no drop" rather than this refusing
      // silently after the user has already let go.
      this.over.set('');
      return;
    }
    event.preventDefault();
    this.over.set(keyOf(row.path));
  }

  protected onDrop(row: OutlineRow, event: DragEvent): void {
    event.preventDefault();
    const from = this.dragging();
    this.dragging.set(null);
    this.over.set('');
    if (!from || wouldDetach(from, row.path)) return;
    this.moved.emit({ from, to: row.path });
  }

  protected onDragEnd(): void {
    this.dragging.set(null);
    this.over.set('');
  }

  protected keyFor = keyOf;
}
