import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { CatalogueIcon } from '../icon/icon';

/**
 * A named catalogue entity — character, weapon or artifact set — with its art.
 *
 * The pattern was written inline in six places before it was a component, which is how the
 * catalogue pages ended up being the only ones with art at all: each page decided
 * separately, and the pages people actually work in decided no. One component means adding
 * art to a new surface is an import rather than a judgement call.
 *
 * `icon` is passed straight through to {@link CatalogueIcon}, which renders nothing for a
 * null basename and hides itself on a failed load. So a token degrades to its name, and a
 * row without art is a row, not a gap.
 */
@Component({
  selector: 'entity-token',
  imports: [CatalogueIcon],
  template: `
    <catalogue-icon [icon]="icon()" [alt]="''" [size]="size()" />
    <span class="body">
      <span class="name">{{ name() }}</span>
      @if (meta()) {
        <span class="meta">{{ meta() }}</span>
      }
    </span>
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-width: 0;
    }

    .body {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .meta {
      font-size: var(--text-xs);
      color: var(--ink-dim);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EntityToken {
  /** The catalogue basename — `UI_AvatarIcon_Ayaka`. Null renders the name alone. */
  readonly icon = input<string | null | undefined>(null);
  readonly name = input('');
  /** A second line: constellation, rarity, whatever the surface wants. Optional. */
  readonly meta = input<string | null>(null);
  readonly size = input(32);
}
