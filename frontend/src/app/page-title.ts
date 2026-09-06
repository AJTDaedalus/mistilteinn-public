import { Injectable, inject } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { RouterStateSnapshot, TitleStrategy } from '@angular/router';

/** The suffix every page carries, so a tab is identifiable at tab-strip width. */
const APP = 'mistilteinn';

/**
 * `<Page> · mistilteinn`, from each route's own `title`.
 *
 * **Every route used to set the same `<title>`.** All fourteen tabs read `mistilteinn`, so a
 * tab strip, a bookmark list and the browser history were fourteen identical entries, and a
 * screen reader announced the same words on every navigation. It was invisible in every
 * screenshot, which is why two visual audits went past it.
 *
 * The page part matches the page's own `h1` rather than its nav label: the nav says
 * `MY WEAPONS` and `SETS` where the headings say "My weapons" and "Artifact sets", and the
 * heading is what the reader sees on arrival.
 *
 * A strategy rather than a literal in each route, so the separator and the suffix are decided
 * once — sixteen routes spelling out `' · mistilteinn'` is sixteen chances to drift.
 */
@Injectable({ providedIn: 'root' })
export class PageTitle extends TitleStrategy {
  private readonly title = inject(Title);

  override updateTitle(snapshot: RouterStateSnapshot): void {
    const page = this.buildTitle(snapshot);
    this.title.setTitle(page ? `${page} · ${APP}` : APP);
  }
}
