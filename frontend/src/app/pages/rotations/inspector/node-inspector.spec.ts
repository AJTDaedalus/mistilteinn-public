import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { RosterCharacter } from '../rotations.service';
import { NodeInspector, conditionText, propertiesFor } from './node-inspector';

const member = (name: string, bases: string[]): RosterCharacter => ({
  nanoka_id: name, name, element: 'geo', abilities: {},
  actions: bases.map((base) => ({ action: base, base, variant: null, name: base, icon: null })),
} as unknown as RosterCharacter);

const state = (segments: string[]) => ({ kind: 'state', segments });
const binary = (op: string, left: unknown, right: unknown) =>
  ({ kind: 'binary', op, left, right });
const literal = (value: number) => ({ kind: 'literal', value });

describe('condition text', () => {
  it('renders a bare readiness gate', () => {
    expect(conditionText([
      { join: '', subject: 'noelle', property: 'burst.ready', comparison: '', value: '' },
    ])).toBe('.noelle.burst.ready');
  });

  it('renders a numeric comparison', () => {
    expect(conditionText([
      { join: '', subject: 'flins', property: 'energy', comparison: '>=', value: '30' },
    ])).toBe('.flins.energy >= 30');
  });

  it('joins two rows with the operator the second carries', () => {
    expect(conditionText([
      { join: '', subject: 'a', property: 'burst.ready', comparison: '', value: '' },
      { join: '||', subject: 'b', property: 'energy', comparison: '<', value: '10' },
    ])).toBe('.a.burst.ready || .b.energy < 10');
  });

  it('drops a row that names nothing yet, rather than emitting a broken condition', () => {
    // A half-filled dropdown row is the normal state while someone is building one.
    expect(conditionText([
      { join: '', subject: 'a', property: 'burst.ready', comparison: '', value: '' },
      { join: '&&', subject: '', property: '', comparison: '', value: '' },
    ])).toBe('.a.burst.ready');
  });
});

describe('property offers', () => {
  it('comes from the character\'s own published actions', () => {
    // A hand-written list would be the one offering a readiness gate on a move they lack.
    const offers = propertiesFor(member('noelle', ['skill', 'burst']));

    expect(offers.map((o) => o.path)).toEqual(['skill.ready', 'burst.ready', 'energy']);
  });

  it('marks energy as the numeric one, because it takes a comparison', () => {
    const energy = propertiesFor(member('x', ['burst'])).find((o) => o.path === 'energy');

    expect(energy?.numeric).toBe(true);
  });

  it('does not repeat a base that has several variants', () => {
    const offers = propertiesFor(member('razor', ['skill', 'skill', 'burst']));

    expect(offers.filter((o) => o.path === 'skill.ready').length).toBe(1);
  });
});

describe('NodeInspector', () => {
  let fixture: ComponentFixture<NodeInspector>;

  function build(node: unknown, roster: RosterCharacter[] = []): void {
    fixture = TestBed.createComponent(NodeInspector);
    fixture.componentRef.setInput('node', node);
    fixture.componentRef.setInput('roster', roster);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [NodeInspector] }).compileComponents();
  });

  it('says what to do when nothing is selected', () => {
    build(null);

    expect(fixture.nativeElement.textContent).toContain('Select a step');
  });

  it('offers repeat and note for an action', () => {
    build({ kind: 'action', character: 'noelle', action: 'skill', repeat: 3, note: 'opener' });

    expect(fixture.nativeElement.textContent).toContain('Repeat');
    expect(fixture.nativeElement.textContent).toContain('Note');
  });

  it('shows an unoffered gcsim parameter without letting it be edited', () => {
    build({ kind: 'action', character: 'x', action: 'charge', repeat: 1, params: { final: '1' } });

    expect(fixture.nativeElement.textContent).toContain('final=1');
    expect(fixture.nativeElement.textContent).toContain('Carried exactly as written');
  });

  it('says a carried node is edited elsewhere rather than looking broken', () => {
    build({ kind: 'raw', source: '999;', reason: 'unmodelled' });

    expect(fixture.nativeElement.textContent).toContain('source view');
  });

  it('reads an existing condition back into its dropdowns', () => {
    build(
      { kind: 'branch', arms: [[binary('>=', state(['flins', 'energy']), literal(30)), []]] },
      [member('Flins', ['burst'])],
    );

    const selects: HTMLSelectElement[] =
      Array.from(fixture.nativeElement.querySelectorAll('select'));
    expect(selects.some((s) => s.value === 'flins')).toBe(true);
    expect(selects.some((s) => s.value === '>=')).toBe(true);
  });

  it('splits a compound condition into one row each', () => {
    build(
      {
        kind: 'branch',
        arms: [[binary('&&', state(['a', 'burst', 'ready']), state(['b', 'burst', 'ready'])), []]],
      },
      [member('A', ['burst']), member('B', ['burst'])],
    );

    expect(fixture.nativeElement.querySelectorAll('.inspector__row').length).toBe(2);
  });

  it('offers a block repeat for a counted loop', () => {
    build({ kind: 'loop', loop: 'counted', variable: 'i', bound: literal(6), body: [] });

    expect(fixture.nativeElement.textContent).toContain('Repeat this block');
  });
});
