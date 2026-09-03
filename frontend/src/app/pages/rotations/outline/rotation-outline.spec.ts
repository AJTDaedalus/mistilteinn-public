import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { RotationTree } from '../rotations.service';
import { RotationOutline, keyOf, labelOf, rowsOf, wouldDetach } from './rotation-outline';

const action = (over: Record<string, unknown> = {}) => ({
  kind: 'action', character: 'noelle', action: 'skill', repeat: 1, note: '', params: {}, ...over,
});

const loop = (body: unknown[], over: Record<string, unknown> = {}) => ({
  kind: 'loop', loop: 'counted', variable: 'i', label: '',
  bound: { kind: 'literal', value: 6 }, body, ...over,
});

const branch = (arms: unknown[], otherwise: unknown[] | null = null) => ({
  kind: 'branch', label: '', arms, otherwise,
});

const ready = { kind: 'state', segments: ['noelle', 'burst', 'ready'] };

describe('outline rows', () => {
  it('flattens nested nodes with a depth', () => {
    const rows = rowsOf([loop([action(), action({ action: 'burst' })])] as never, new Set());

    expect(rows.map((r) => r.depth)).toEqual([0, 1, 1]);
  });

  it('gives every row the path the backend uses for diagnostics', () => {
    const rows = rowsOf([loop([action()])] as never, new Set());

    expect(rows[1].path).toEqual([0, 'body', 0]);
  });

  it('walks both arms of a branch and its else', () => {
    const tree = [branch([[ready, [action()]]], [action({ action: 'attack' })])];
    const rows = rowsOf(tree as never, new Set());

    expect(rows.map((r) => keyOf(r.path)))
      .toEqual(['0', '0/arms/0/0', '0/otherwise/0']);
  });

  it('skips the contents of a collapsed block but keeps the block', () => {
    const rows = rowsOf([loop([action(), action()])] as never, new Set(['0']));

    expect(rows.length).toBe(1);
    expect(rows[0].children).toBe(2);
  });

  it('counts every descendant, not only direct children', () => {
    const rows = rowsOf([loop([loop([action()])])] as never, new Set(['0']));

    expect(rows[0].children).toBe(2);
  });
});

describe('outline labels', () => {
  it('reads an action as the move it is', () => {
    expect(labelOf(action({ repeat: 3 }) as never)).toBe('noelle skill ×3');
  });

  it('shows a variant, because it is a different move', () => {
    expect(labelOf(action({ params: { hold: '1' } }) as never)).toContain('[hold=1]');
  });

  it('omits a repeat of one rather than writing ×1', () => {
    expect(labelOf(action() as never)).toBe('noelle skill');
  });

  it('reads a counted loop as a repeat', () => {
    expect(labelOf(loop([]) as never)).toBe('repeat 6');
  });

  it('reads a branch as its first condition', () => {
    expect(labelOf(branch([[ready, []]]) as never)).toBe('if .noelle.burst.ready');
  });

  it('reads a carried node as its first line, not its whole source', () => {
    const raw = { kind: 'raw', source: 'fn f() {\n  999;\n}', reason: 'a user function' };

    expect(labelOf(raw as never)).toBe('fn f() {');
  });
});

describe('RotationOutline', () => {
  let fixture: ComponentFixture<RotationOutline>;

  function build(tree: unknown): void {
    fixture = TestBed.createComponent(RotationOutline);
    fixture.componentRef.setInput('tree', tree as RotationTree);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [RotationOutline] }).compileComponents();
  });

  it('renders one row per node', () => {
    build({ nodes: [action(), action({ action: 'burst' })] });

    expect(fixture.nativeElement.querySelectorAll('.outline__row').length).toBe(2);
  });

  it('marks a carried node so it is obvious it is not editable here', () => {
    build({ nodes: [{ kind: 'raw', source: '999;', reason: 'unmodelled' }] });

    expect(fixture.nativeElement.querySelector('.outline__row--carried')).toBeTruthy();
    expect(fixture.nativeElement.textContent).toContain('as written');
  });

  it('selects a row when it is clicked', () => {
    build({ nodes: [action(), action({ action: 'burst' })] });
    fixture.nativeElement.querySelectorAll('.outline__row')[1].click();
    fixture.detectChanges();

    expect(fixture.componentInstance.selected()).toBe('1');
  });

  it('moves the selection with the arrow keys', () => {
    // A rotation with 180 steps is not one to mouse through.
    build({ nodes: [action(), action(), action()] });
    const list: HTMLElement = fixture.nativeElement.querySelector('.outline');

    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    fixture.detectChanges();
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    fixture.detectChanges();

    expect(fixture.componentInstance.selected()).toBe('1');
  });

  it('collapses a block to one line with a count', () => {
    build({ nodes: [loop([action(), action()])] });
    fixture.nativeElement.querySelector('.outline__twist').click();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelectorAll('.outline__row').length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('2 inside');
  });

  it('says so when there is nothing yet', () => {
    build({ nodes: [] });

    expect(fixture.nativeElement.textContent).toContain('No steps yet');
  });
});

describe('outline drag targets', () => {
  it('refuses a drop into the block being dragged', () => {
    // **The one drop that must be refused.** A block moved into its own body becomes its own
    // ancestor, and everything inside it leaves the tree with it.
    expect(wouldDetach([0], [0, 'body', 1])).toBe(true);
  });

  it('refuses a drop onto the node itself', () => {
    expect(wouldDetach([0, 'body', 1], [0, 'body', 1])).toBe(true);
  });

  it('allows a drop onto a sibling', () => {
    expect(wouldDetach([0], [1])).toBe(false);
  });

  it('allows a drop onto a node outside the dragged block', () => {
    expect(wouldDetach([1, 'body', 0], [0])).toBe(false);
  });

  it('does not confuse a sibling index that starts with the same digit', () => {
    // `[1]` is not an ancestor of `[10]`, though `'1'` is a prefix of `'10'` as a string.
    expect(wouldDetach([1], [10])).toBe(false);
  });
});
