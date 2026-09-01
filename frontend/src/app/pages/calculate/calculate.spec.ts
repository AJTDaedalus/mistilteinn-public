import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { CalculatePage } from './calculate';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { BuildsService } from '../builds/builds.service';
import { CatalogueService } from '../catalogue/catalogue.service';
import { RecipeOptimizeService } from '../optimize/recipe-optimize.service';
import { RotationsService } from '../rotations/rotations.service';
import type { Recipe, RecipeHit } from '../../sim/recipe';

/**
 * **This page had no spec, and three defects lived in it at once.**
 *
 * Reported by the owner: *"I'm not confident it's calculating the rotation the same way
 * Optimize is, the damage is very different. It also only shows one character's icon."*
 * Measured against gcsim on the same seed and rotation, the page read **58,082,172** for a
 * rotation that deals **15,737,381**.
 *
 * All three were one-liners, and none of them could fail a test that did not exist.
 */

const NO_TRIPLE = { atk: 0, hp: 0, def: 0 };

/** A hit shaped like the parser's, minimal but complete enough for `evaluateHit`. */
function hit(mine: boolean, damage: number): RecipeHit {
  return {
    abil: mine ? 'skill' : 'teammate skill',
    element: 'cryo',
    attackTag: 1,
    talent: 0,
    mine,
    owner: mine ? 0 : 1,
    scaling: 'atk',
    flatDamage: 0,
    conversions: {},
    calibratedBase: { ...NO_TRIPLE, atk: damage },
    calibratedPercent: { ...NO_TRIPLE },
    calibratedFlat: { ...NO_TRIPLE },
    critRate: 0,
    critDmg: 0,
    gcsimAverageDamage: damage,
  } as unknown as RecipeHit;
}

function page() {
  TestBed.configureTestingModule({
    providers: [
      { provide: RotationsService, useValue: {} },
      { provide: BuildsService, useValue: {} },
      { provide: ArtifactsService, useValue: {} },
      { provide: CatalogueService, useValue: {} },
      { provide: RecipeOptimizeService, useValue: {} },
    ],
  });
  return TestBed.runInInjectionContext(
    () => new CalculatePage(),
  ) as unknown as Record<string, never>;
}

describe('CalculatePage contribution', () => {
  it("counts only the character's own hits", () => {
    // A recipe carries the *rotation's* hits. Counting a teammate's charged every character
    // for the whole team, so four rows each reported roughly the team total and the page
    // summed them — 3.7x on the owner's data.
    const recipe = {
      hits: [hit(true, 100), hit(false, 900), hit(true, 50)],
      meta: {},
    } as unknown as Recipe;
    const p = page();

    const row = (p['contribution'] as unknown as (b: unknown, r: Recipe, s: unknown) => {
      total: number; hits: unknown[];
    })({ id: 'b1', character: { name: 'Skirk' } }, recipe, {
      atkPercent: 0, atkFlat: 0, hpPercent: 0, hpFlat: 0, defPercent: 0, defFlat: 0,
      elementalMastery: 0, critRate: 0, critDmg: 0, elementBonus: {}, allElementBonus: 0,
    });

    // **Which hits are counted** is what this page decides; what one is *worth* belongs to
    // `recipe-eval`, which has its own suite. Asserting a number here would need a fully
    // shaped hit and would be testing the evaluator twice.
    expect(row.hits.length).toBe(2);
    expect(row.hits.map((h) => (h as { ability: string }).ability))
      .not.toContain('teammate skill');
  });
});

describe('CalculatePage team cards', () => {
  it('shows every face on the team, not the first', () => {
    // `icon: team.characters[0]?.icon` drew one character for a party of four.
    const p = page();
    (p['teams'] as unknown as { set: (v: unknown[]) => void }).set([
      {
        id: 't1',
        name: 'Freeze',
        characters: [
          { name: 'Skirk', icon: 'a.webp' }, { name: 'Furina', icon: 'b.webp' },
          { name: 'Citlali', icon: 'c.webp' }, { name: 'Escoffier', icon: 'd.webp' },
        ],
      },
    ]);

    const options = (p['teamOptions'] as unknown as () => { icons?: unknown[] }[])();

    expect(options[0].icons).toEqual(['a.webp', 'b.webp', 'c.webp', 'd.webp']);
  });
});

describe('CalculatePage calibration targets', () => {
  const p = () => page();

  it('reads a 4-piece recipe when the character wears one', () => {
    const recipe = { hits: [], meta: {} } as unknown as Recipe;
    const got = (p()['recipeFor'] as unknown as (t: unknown, c: unknown) => Recipe | null)(
      { artifactSetIds: ['u1'], setIds: [15026], label: '' },
      { byFourPieceSet: new Map([[15026, recipe]]), byPair: new Map(), noFourPiece: null },
    );

    expect(got).toBe(recipe);
  });

  it('reads a pair recipe for a 2+2', () => {
    const recipe = { hits: [], meta: {} } as unknown as Recipe;
    const got = (p()['recipeFor'] as unknown as (t: unknown, c: unknown) => Recipe | null)(
      { artifactSetIds: ['u1', 'u2'], setIds: [15026, 15003], label: '' },
      { byFourPieceSet: new Map(), byPair: new Map([['15003+15026', recipe]]), noFourPiece: null },
    );

    expect(got).toBe(recipe);
  });

  it('falls back to the baseline when nothing reaches a bonus', () => {
    // Not a failure: with no set bonus in play the baseline *is* the honest calibration.
    const recipe = { hits: [], meta: {} } as unknown as Recipe;
    const got = (p()['recipeFor'] as unknown as (t: unknown, c: unknown) => Recipe | null)(
      { artifactSetIds: [], setIds: [], label: '' },
      { byFourPieceSet: new Map(), byPair: new Map(), noFourPiece: recipe },
    );

    expect(got).toBe(recipe);
  });
});
