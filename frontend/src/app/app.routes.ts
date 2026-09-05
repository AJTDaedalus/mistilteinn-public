import { Routes } from '@angular/router';

import { requireApproved, requirePending, requireUnauthed } from './api/auth.guards';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./pages/auth/login').then((m) => m.LoginPage),
    canMatch: [requireUnauthed],
  },
  {
    // **No guard at all**, deliberately. The person arriving here has clicked a link in their
    // email and is by definition not signed in — but they might also be signed in on this
    // device already, or pending, and every one of those is a legitimate arrival. A
    // `requireUnauthed` here would bounce the exact user the link was sent to.
    path: 'verify',
    loadComponent: () => import('./pages/auth/verify').then((m) => m.VerifyPage),
  },
  {
    path: 'pending',
    loadComponent: () => import('./pages/auth/pending').then((m) => m.PendingPage),
    canMatch: [requirePending],
  },
  {
    // **`/` is the inventory.** Owner, 2026-09-05: *"inventory is a good landing page"*, after
    // *"honestly landing page could just be blank and be better"* — the page it replaces sat
    // behind `requireApproved`, so its only reader was a signed-in user looking at a nav bar
    // that already carried all eleven links. It was the nav a second time, in prose.
    //
    // **No guard here, on purpose.** `/inventory` carries `requireApproved`, and that guard
    // returns a `UrlTree`, so a signed-out arrival lands on `/login` and a pending one on
    // `/pending` exactly as before. Repeating the guard on a redirect would put the same rule
    // in two places, and the one that drifted would be the one nobody reads.
    //
    // `pathMatch: 'full'` is load-bearing: an empty path matches by *prefix* by default, so
    // without it this route would swallow every URL in the app.
    path: '',
    redirectTo: 'inventory',
    pathMatch: 'full',
  },
  {
    // The first account surface this app has had. The header chip could sign you out and
    // nothing else — your own email appeared only inside it, truncated at 16 characters.
    path: 'account',
    loadComponent: () => import('./pages/account/account').then((m) => m.AccountPage),
    canMatch: [requireApproved],
  },
  {
    path: 'characters',
    loadComponent: () =>
      import('./pages/catalogue/characters').then((m) => m.CharactersPage),
    canMatch: [requireApproved],
  },
  {
    path: 'weapons',
    loadComponent: () => import('./pages/catalogue/weapons').then((m) => m.WeaponsPage),
    canMatch: [requireApproved],
  },
  {
    // **Your** weapons, not the catalogue's. `/weapons` lists all 260 in the game; this lists
    // what the export says you own, with the holder's face on each and equipped ones first.
    path: 'my-weapons',
    loadComponent: () =>
      import('./pages/weapons-inventory/weapons-inventory').then((m) => m.WeaponsInventoryPage),
    canMatch: [requireApproved],
  },
  {
    path: 'artifact-sets',
    loadComponent: () =>
      import('./pages/catalogue/artifact-sets').then((m) => m.ArtifactSetsPage),
    canMatch: [requireApproved],
  },
  {
    // `inventory`, not `artifacts`. The nav carried two links reading "Artifacts" — the
    // game's set catalogue at `/artifact-sets` and the caller's own pieces here — and the
    // only way to tell them apart was to click one. Renaming the label alone would leave a
    // path that disagrees with it.
    path: 'inventory',
    loadComponent: () => import('./pages/artifacts/artifacts').then((m) => m.ArtifactsPage),
    canMatch: [requireApproved],
  },
  {
    // The old path still resolves. A redirect rather than a deletion because this URL has
    // been the inventory since the artifacts chunk shipped, and a bookmark landing on the
    // catch-all would take the user to the landing page with no indication why.
    path: 'artifacts',
    redirectTo: 'inventory',
    pathMatch: 'full',
  },
  {
    path: 'builds',
    loadComponent: () => import('./pages/builds/builds').then((m) => m.BuildsPage),
    canMatch: [requireApproved],
  },
  {
    path: 'teams',
    loadComponent: () => import('./pages/teams/teams').then((m) => m.TeamsPage),
    canMatch: [requireApproved],
  },
  {
    path: 'optimize',
    loadComponent: () => import('./pages/optimize/optimize').then((m) => m.OptimizePage),
    canMatch: [requireApproved],
  },
  {
    // Renamed from `explain` (owner ruling): this page runs a whole rotation for a whole team,
    // where the old one explained one hit for one build. `/explain` still resolves so a
    // bookmark does not 404 — a rename that breaks links is a rename that loses readers.
    path: 'calculate',
    loadComponent: () => import('./pages/calculate/calculate').then((m) => m.CalculatePage),
    canMatch: [requireApproved],
  },
  {
    path: 'rotations',
    loadComponent: () => import('./pages/rotations/rotations').then((m) => m.RotationsPage),
    canMatch: [requireApproved],
  },
  {
    path: 'explain',
    redirectTo: 'calculate',
    pathMatch: 'full',
  },
  {
    path: 'teapot',
    loadComponent: () => import('./pages/teapot/teapot').then((m) => m.TeapotPage),
    canMatch: [requireApproved],
  },
  {
    path: 'enemies',
    loadComponent: () => import('./pages/catalogue/enemies').then((m) => m.EnemiesPage),
    canMatch: [requireApproved],
  },
  {
    // **Straight to `/inventory`, not via `''`.** It pointed at `''` while `''` rendered the
    // landing page. Now that `''` is itself a redirect, that was two hops — and Angular
    // resolves one redirect per recognition pass, so an unknown URL landed on `/` and stopped
    // there, on a path with no component, rendering nothing. Caught by walking the chain in a
    // test rather than assuming it; the guards' `createUrlTree(['/'])` *does* chain, because
    // a guard redirect starts a fresh navigation, and there is a test for that too.
    path: '**',
    redirectTo: 'inventory',
  },
];
