import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';
import { signal } from '@angular/core';

import { AuthService } from './api/auth.service';
import { App } from './app';
import { routes } from './app.routes';

/**
 * Every catalogue route must be reachable from the shell.
 *
 * A route with no link is a page nobody can get to, and it looks completely healthy: it
 * compiles, it is tested, it renders when you visit it by hand. This project has met that
 * shape twice — `search.ts` is a library no page calls (which is why C.6 is deferred), and
 * A.3's three new pages shipped with routes and no nav until this test was written.
 *
 * The shell is **rendered**, with auth stubbed to an approved user, because the nav only
 * exists in that state. Reading the template as text would have been simpler and would also
 * have passed had the links been placed outside the `@if`, where nobody would see them.
 */
function renderedShell(): string {
  TestBed.configureTestingModule({
    imports: [App],
    providers: [
      provideRouter([]),
      {
        provide: AuthService,
        useValue: {
          status: signal('approved'),
          me: signal({ label: 'Tester', email: 't@example.com' }),
          logout: vi.fn(),
        },
      },
    ],
  });
  const fixture = TestBed.createComponent(App);
  fixture.detectChanges();
  return (fixture.nativeElement as HTMLElement).querySelector('.shell__nav')?.innerHTML ?? '';
}

/** Paths that are deliberately not in the nav, and why each one is exempt. */
const NOT_IN_NAV: Record<string, string> = {
  '': 'the landing page is the brand link',
  login: 'reached by being signed out, not by clicking',
  pending: 'reached by having a pending account',
  '**': 'the catch-all redirect',
};

describe('app routes', () => {
  const linkable = routes
    .map((route) => route.path ?? '')
    .filter((path) => !(path in NOT_IN_NAV));

  it('has routes to link to', () => {
    // Guards the guard: if `routes` were ever restructured so this list came back empty,
    // every assertion below would pass vacuously.
    expect(linkable.length).toBeGreaterThan(0);
  });

  it.each(linkable)('links to /%s from the shell nav', (path) => {
    const nav = renderedShell();
    expect(nav).toBeTruthy();
    // `href`, not `routerLink`: the attribute is what a rendered link actually carries, and
    // asserting on the directive name would pass for a link the router never resolved.
    expect(nav).toContain(`href="/${path}"`);
  });

  it('exempts only paths with a stated reason', () => {
    for (const [path, reason] of Object.entries(NOT_IN_NAV)) {
      expect(reason.length).toBeGreaterThan(10);
      expect(routes.some((route) => (route.path ?? '') === path)).toBe(true);
    }
  });
});
