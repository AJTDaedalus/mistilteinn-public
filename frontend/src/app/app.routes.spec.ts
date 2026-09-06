import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
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
function shell(me: Record<string, unknown> = { label: 'Tester', email: 't@example.com' }) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [App],
    providers: [
      provideRouter([]),
      {
        provide: AuthService,
        useValue: { status: signal('approved'), me: signal(me), logout: vi.fn() },
      },
    ],
  });
  const fixture = TestBed.createComponent(App);
  fixture.detectChanges();
  return fixture;
}

function renderedShell(): string {
  const el = shell().nativeElement as HTMLElement;
  // **The header, not `.shell__nav`.** The property these assertions are about is that every
  // linkable route is reachable from the shell chrome. `/account` is reached through the
  // identity chip, which now sits beside the brand rather than inside `<nav>` — the header is
  // two rows that way at every width, instead of three whenever the sign-in email is long.
  // Scoping to the nav would have made this a test of where the markup puts a link rather
  // than of whether the link is there.
  return el.querySelector('.shell__header')?.innerHTML ?? '';
}

/** Paths that are deliberately not in the nav, and why each one is exempt. */
const NOT_IN_NAV: Record<string, string> = {
  '': 'a redirect to /inventory — the brand link goes there, and the nav already links the canonical path',
  login: 'reached by being signed out, not by clicking',
  pending: 'reached by having a pending account',
  '**': 'the catch-all redirect',
  artifacts: 'a redirect to /inventory, kept so old bookmarks resolve — the nav links the '
    + 'canonical path, and linking both would put the same page in the bar twice',
  explain: 'a redirect to /calculate, for the same reason: the page was renamed when it grew '
    + 'from explaining one hit to calculating a whole rotation, and a rename that breaks '
    + 'links is a rename that loses readers',
  verify: 'reached only from a link in a confirmation email, never from the nav — the person '
    + 'arriving is finishing a signup, and a nav entry would offer every signed-in user a '
    + 'page that can only tell them their link is invalid',
};

/**
 * `/` is a redirect, and redirects are the routes that fail silently.
 *
 * The empty path matches by **prefix** unless `pathMatch: 'full'` is set, so the difference
 * between this working and the whole app redirecting to `/inventory` is one property. Nothing
 * else here would notice: the config compiles either way, and every other route's own test
 * asserts on the shell's nav rather than on navigation.
 *
 * So this navigates for real, through the router, with the guards live.
 */
describe('the front door', () => {
  async function routerWith(status: 'approved' | 'pending' | 'unauthed') {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideRouter(routes),
        {
          provide: AuthService,
          useValue: { status: signal(status), me: signal({ email: 't@example.com' }), logout: vi.fn() },
        },
      ],
    });
    return TestBed.inject(Router);
  }

  it('sends an approved user from / to the inventory', async () => {
    const router = await routerWith('approved');

    await router.navigateByUrl('/');

    expect(router.url).toBe('/inventory');
  });

  it('leaves every other url alone', async () => {
    // The `pathMatch: 'full'` assertion, made where it bites. Without it the empty path
    // matches by prefix and this comes back '/inventory'.
    const router = await routerWith('approved');

    await router.navigateByUrl('/builds');

    expect(router.url).toBe('/builds');
  });

  it('still sends a signed-out arrival to the login page', async () => {
    // The redirect carries no guard of its own; `/inventory` carries `requireApproved` and
    // that guard returns a UrlTree. Repeating the rule on the redirect would be a second copy
    // of it, and this asserts the single copy still reaches someone arriving at `/`.
    const router = await routerWith('unauthed');

    await router.navigateByUrl('/');

    expect(router.url).toBe('/login');
  });

  it('sends a pending account to the pending page', async () => {
    const router = await routerWith('pending');

    await router.navigateByUrl('/');

    expect(router.url).toBe('/pending');
  });

  it('sends an approved user away from the login page', async () => {
    // `requireUnauthed` returns a UrlTree for `/`, which is now itself a redirect. A guard
    // redirect starts a fresh navigation, so this chain does resolve — asserted rather than
    // assumed, because the catch-all's did not.
    const router = await routerWith('approved');

    await router.navigateByUrl('/login');

    expect(router.url).toBe('/inventory');
  });

  it('resolves an unknown url rather than looping through the catch-all', async () => {
    // `**` redirects to `''`, and `''` now redirects again. Two hops is fine and three would
    // not be, so the chain is walked rather than assumed.
    const router = await routerWith('approved');

    await router.navigateByUrl('/no-such-page');

    expect(router.url).toBe('/inventory');
  });
});

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

/**
 * The face beside your name in the header.
 *
 * `CatalogueIcon` hides itself when art is missing, so an account with no avatar and one whose
 * image 404s render identically — which is deliberate, and is also why the presence of the
 * image is asserted here rather than assumed from the field being set.
 */
describe('the identity chip', () => {
  const chip = (me: Record<string, unknown>) =>
    (shell(me).nativeElement as HTMLElement).querySelector('.identity-chip')!;

  it('draws the chosen character', () => {
    const el = chip({
      label: 'Tester', email: 't@example.com',
      avatar: { character_id: 'c1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka' },
    });

    const img = el.querySelector('img')!;
    expect(img.getAttribute('src')).toBe('/icons/UI_AvatarIcon_Ayaka.webp');
    expect(img.getAttribute('alt')).toBe('Kamisato Ayaka');
  });

  it('is the name alone when nobody has been chosen', () => {
    // Every account that existed before this feature is in this state, and it is the state
    // the chip has always been in. It must not gain a hole.
    const el = chip({ label: 'Tester', email: 't@example.com', avatar: null });

    expect(el.querySelector('img')).toBeNull();
    expect(el.textContent).toContain('Tester');
  });

  it('takes you to the account page', () => {
    const el = chip({ label: 'Tester', email: 't@example.com', avatar: null });

    expect(el.querySelector('a')?.getAttribute('href')).toBe('/account');
  });
});
