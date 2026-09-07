import { TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { RouterStateSnapshot } from '@angular/router';
import { describe, expect, it } from 'vitest';

import { PageTitle } from './page-title';
import { routes } from './app.routes';

/**
 * **Every route set the same `<title>`.** Fourteen tabs read `mistilteinn`, so a tab strip, a
 * bookmark list and the browser history were fourteen identical entries — and no screenshot
 * could show it, which is how two visual audits went past it. These are the guard.
 */
describe('page titles', () => {
  it('gives every routed page its own title', () => {
    const routed = routes.filter((r) => r.loadComponent);
    expect(routed.length).toBeGreaterThan(10);
    const missing = routed.filter((r) => !r.title).map((r) => r.path);
    expect(missing).toEqual([]);
  });

  it('does not reuse one title for two pages', () => {
    const titles = routes.filter((r) => r.title).map((r) => r.title);
    expect(new Set(titles).size).toBe(titles.length);
  });

  // A redirect renders nothing, so a title on one would name a page nobody is looking at.
  it('leaves redirects untitled', () => {
    const titled = routes.filter((r) => r.redirectTo && r.title);
    expect(titled).toEqual([]);
  });

  it('appends the app name, so a tab is identifiable at tab-strip width', () => {
    const strategy = TestBed.configureTestingModule({}).inject(PageTitle);
    const title = TestBed.inject(Title);
    strategy.updateTitle({ root: { children: [], data: {} } } as unknown as RouterStateSnapshot);
    // No route title resolved: the bare app name rather than " · mistilteinn".
    expect(title.getTitle()).toBe('mistilteinn');
  });
});
