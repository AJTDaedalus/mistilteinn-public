import { Component, computed, input, linkedSignal } from '@angular/core';

/** Where `scripts/download_icons.py` vendors them. */
const ICON_BASE = '/icons';

/**
 * A catalogue icon, or nothing at all.
 *
 * The basenames come from the seeded catalogue — `characters.icon` is `UI_AvatarIcon_Ayaka`
 * — and `scripts/download_icons.py` vendors the images under `public/icons/`.
 *
 * **A missing image must not take the row with it.** Three of the 475 are genuinely not
 * published upstream (an unreleased weapon's placeholder, two artifact sets). Art is
 * decoration; a name and a stat are the row. So a failed load hides the image and leaves
 * everything else standing.
 *
 * **The failure is per-basename, not per-instance.** `failed` used to latch and never reset,
 * which was invisible while every instance lived inside a `@for` keyed to a fixed row. It
 * stopped being invisible once long-lived instances arrived whose `[icon]` changes —
 * rotations' step art follows a `<select>`, and teams' slot art follows its picker. One step
 * set to a character with no published art latched the failure, and every character chosen
 * after it rendered blank until the page was re-navigated.
 */
@Component({
  selector: 'catalogue-icon',
  imports: [],
  template: `
    @if (visible()) {
      <img
        [src]="src()"
        [alt]="alt()"
        [attr.width]="size()"
        [attr.height]="size()"
        [style.object-fit]="fit()"
        [style.object-position]="fit() === 'cover' ? 'center 8%' : null"
        loading="lazy"
        (error)="hide()"
      />
    }
  `,
  // Bound on the host rather than written as a custom property, because a property that only
  // ever gets its value from TypeScript is invisible to `npm run check:tokens` — which reads
  // stylesheets — and would be reported as used-but-never-defined for the life of the file.
  host: {
    '[style.min-width.px]': 'size()',
    '[style.min-height.px]': 'size()',
  },
  styles: `
    /* **The box keeps its size when the image does not arrive.**

       This component hides a broken image so nothing renders as a torn placeholder, which is
       right — but it hid the *space* too, so a card whose icon 404s lost its icon's height
       and its title rose ~44px above every sibling in the row. Measured on /artifact-sets:
       UI_RelicIcon_15004_4.webp is missing, and "Glacier and Snowfield" renders as a
       visibly different component from the cards beside it.

       Reserving the box turns a missing icon into a gap, which is what "absent" should look
       like — and it is the difference between one card lacking art and a row looking broken. */
    :host {
      display: inline-flex;
      flex: 0 0 auto;
    }

    img { border-radius: 0.25rem; }

    /* A "fill" host class makes the image fill its box, and this rule has to live *here*.

       A page writing ".card__art img { width: 100% }" compiles to a selector carrying the
       page's _ngcontent attribute, which this element does not have — so the img kept the
       width/height attributes and rendered as a fixed square: measured 180x180 inside a
       176x235 card, overflowing sideways and short at the bottom. Third unreachable-selector
       bug in three PRs.

       The class is set by the caller rather than derived from the "fit" input: a host binding
       on the input silently applied nothing (measured: the host carried no classes), and the
       page is the thing that knows whether this icon is decorating a row or filling a card. */
    :host(.fill) { display: block; width: 100%; height: 100%; }
    :host(.fill) img { width: 100%; height: 100%; border-radius: 0; }
  `,
})
export class CatalogueIcon {
  /** The basename, straight from the catalogue row. Null renders nothing. */
  readonly icon = input<string | null | undefined>(null);
  /** What the image is of, for a screen reader. */
  readonly alt = input('');
  readonly size = input(40);
  /**
   * How the image fills its box. `contain` for an icon, `cover` for a portrait filling a card.
   *
   * An input rather than a page-level CSS rule, because this component uses Angular's default
   * emulated encapsulation: `.card__art img { object-fit: cover }` written on the page
   * compiles to a selector carrying the *page's* `_ngcontent` attribute, which this `<img>`
   * does not have, so it silently does nothing — the portraits letterboxed inside their
   * cards and nothing in the stylesheet looked wrong.
   *
   * `cover` also sets the crop, for the same unreachable-selector reason. The number is
   * measured, not guessed: the portraits are **320x1024** with the face between roughly 10%
   * and 40% of the height. A 3:4 frame shows 41.7% of that, so `center` (rows 29-71%) lands
   * on the torso and `top` (rows 0-42%) clips at the hairline. `8%` opens the window at
   * about row 5% and closes it near 47% — head and shoulders, which is what a card wants.
   */
  readonly fit = input<'contain' | 'cover'>('contain');

  /**
   * Reset whenever the basename changes: a new image deserves its own attempt.
   *
   * `linkedSignal` rather than an `effect`, so the reset happens as part of reading the
   * signal rather than one change-detection pass later — an effect would leave a frame in
   * which the *previous* icon's failure hides the new one.
   */
  protected readonly failed = linkedSignal<string | null | undefined, boolean>({
    source: () => this.icon(),
    computation: () => false,
  });

  protected readonly visible = computed(() => !!this.icon() && !this.failed());

  /**
   * The size to hold open even when nothing is drawn.
   *
   * `fill` icons size from their parent, so reserving a pixel box there would fight the card
   * that contains them; everything else gets its declared `size`.
   */
  protected readonly src = computed(() => `${ICON_BASE}/${this.icon()}.webp`);

  protected hide(): void {
    this.failed.set(true);
  }
}
