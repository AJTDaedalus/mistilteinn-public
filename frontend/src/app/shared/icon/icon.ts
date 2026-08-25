import { Component, computed, input, signal } from '@angular/core';

/** Where `scripts/download_icons.py` vendors them. */
const ICON_BASE = '/icons';

/**
 * A catalogue icon, or nothing at all.
 *
 * The basenames come from the seeded catalogue — `characters.icon` is `UI_AvatarIcon_Ayaka`
 * — and `scripts/download_icons.py` vendors the images under `public/icons/`.
 *
 * **A missing image must not take the row with it.** Three of the 475 are genuinely not
 * published upstream (an unreleased weapon's placeholder, two artifact sets), and a vendored
 * directory can be absent entirely — nothing commits it, so a fresh clone that has not run the
 * script has none. Art is decoration; a name and a stat are the row. So a failed load hides
 * the image and leaves everything else standing.
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

  protected readonly failed = signal(false);

  protected readonly visible = computed(() => !!this.icon() && !this.failed());
  protected readonly src = computed(() => `${ICON_BASE}/${this.icon()}.webp`);

  protected hide(): void {
    this.failed.set(true);
  }
}
