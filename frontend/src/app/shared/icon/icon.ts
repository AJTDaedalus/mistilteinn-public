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
        loading="lazy"
        (error)="hide()"
      />
    }
  `,
  styles: `
    :host { display: inline-flex; }
    img { border-radius: 0.25rem; object-fit: contain; }
  `,
})
export class CatalogueIcon {
  /** The basename, straight from the catalogue row. Null renders nothing. */
  readonly icon = input<string | null | undefined>(null);
  /** What the image is of, for a screen reader. */
  readonly alt = input('');
  readonly size = input(40);

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
  protected readonly src = computed(() => `${ICON_BASE}/${this.icon()}.webp`);

  protected hide(): void {
    this.failed.set(true);
  }
}
