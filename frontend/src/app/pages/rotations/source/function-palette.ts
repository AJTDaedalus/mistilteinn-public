import { Component, input, output } from '@angular/core';

import type { DeclaredFunction } from '../rotations.service';

/**
 * The functions a rotation declares, as buttons that draw a call onto it.
 *
 * Owner, 2026-09-03: *"fn stays text only, but can't hurt to have a nice spot to enter it and
 * a way to treat user defined functions (in a rotation's scope) as buttons to draw onto the
 * rotation."*
 *
 * **That split is the whole design.** A function *body* is control flow — the reason `fn`
 * needs text at all, and the reason `DECISIONS.md` §32 allows one. A function *call* is a name
 * and some arguments, which is exactly the shape the move picker already deals in. So writing
 * one stays in the source view and using one becomes a click.
 *
 * The vocabulary comes from the rotation itself and cannot drift: rename or delete a
 * declaration and it stops being offered, because the tree stopped declaring it. That is the
 * same argument `/options` makes for per-character moves.
 */
@Component({
  selector: 'app-function-palette',
  standalone: true,
  templateUrl: './function-palette.html',
  styleUrl: './function-palette.scss',
})
export class FunctionPalette {
  readonly functions = input<DeclaredFunction[]>([]);

  /** A call to draw onto the rotation, already rendered as gcsim source. */
  readonly called = output<string>();

  /**
   * `opener(30)` — or `opener(delay)` when the argument is not known yet.
   *
   * **The parameter name is the placeholder**, rather than a `0` that would look like an
   * answer. A call with the wrong number of arguments is refused by the validator with the
   * arity named, so a half-filled call fails loudly rather than simulating something else.
   */
  protected preview(declared: DeclaredFunction): string {
    return `${declared.name}(${declared.parameters.join(', ')})`;
  }

  protected draw(declared: DeclaredFunction): void {
    this.called.emit(`${this.preview(declared)};`);
  }
}
