import { Routes } from '@angular/router';

import { requireApproved, requirePending, requireUnauthed } from './api/auth.guards';

export const routes: Routes = [
  {
    path: 'login',
    title: 'Sign in',
    loadComponent: () => import('./pages/auth/login').then((m) => m.LoginPage),
    canMatch: [requireUnauthed],
  },
  {
    // **No guard at all**, deliberately. The person arriving here has clicked a link in their
    // email and is by definition not signed in — but they might also be signed in on this
    // device already, or pending, and every one of those is a legitimate arrival. A
    // `requireUnauthed` here would bounce the exact user the link was sent to.
    path: 'verify',
    title: 'Verify your email',
    loadComponent: () => import('./pages/auth/verify').then((m) => m.VerifyPage),
  },
  {
    path: 'pending',
    title: 'Awaiting approval',
    loadComponent: () => import('./pages/auth/pending').then((m) => m.PendingPage),
    canMatch: [requirePending],
  },
  {
    // **`/` is the inventory** — now the Inventory tab of `/artifacts`. Owner, 2026-09-05: *"inventory is a good landing page"*, after
    // *"honestly landing page could just be blank and be better"* — the page it replaces sat
    // behind `requireApproved`, so its only reader was a signed-in user looking at a nav bar
    // that already carried all eleven links. It was the nav a second time, in prose.
    //
    // **No guard here, on purpose.** `/artifacts` carries `requireApproved`, and that guard
    // returns a `UrlTree`, so a signed-out arrival lands on `/login` and a pending one on
    // `/pending` exactly as before. Repeating the guard on a redirect would put the same rule
    // in two places, and the one that drifted would be the one nobody reads.
    //
    // `pathMatch: 'full'` is load-bearing: an empty path matches by *prefix* by default, so
    // without it this route would swallow every URL in the app.
    path: '',
    redirectTo: 'artifacts/inventory',
    pathMatch: 'full',
  },
  {
    // The first account surface this app has had. The header chip could sign you out and
    // nothing else — your own email appeared only inside it, truncated at 16 characters.
    path: 'account',
    title: 'Account',
    loadComponent: () => import('./pages/account/account').then((m) => m.AccountPage),
    canMatch: [requireApproved],
  },
  {
    // What it costs to take a character and a weapon where you want them.
    // `docs/DESIGN_planner.md`.
    path: 'planner',
    title: 'Planner',
    loadComponent: () => import('./pages/planner/planner').then((m) => m.PlannerPage),
    canMatch: [requireApproved],
  },
  {
    // Odds of reaching a constellation or refinement on a given budget.
    // `docs/DESIGN_wish_planner.md`. Its own route rather than a tab on /planner: Fribbels
    // puts the equivalent in its tools group, and familiarity is the point.
    path: 'wishes',
    title: 'Wish Planner',
    loadComponent: () => import('./pages/wishes/wishes').then((m) => m.WishesPage),
    canMatch: [requireApproved],
  },
  {
    // What this is, and whose work it is built on. Reached from the footer rather than the
    // nav: the nav is for things you do, and this is read once.
    //
    // **No `requireApproved`.** The licence notices it carries have to be reachable by
    // anyone who can load the page, including someone who has not signed in.
    path: 'about',
    title: 'About',
    loadComponent: () => import('./pages/about/about').then((m) => m.AboutPage),
  },
  {
    path: 'characters',
    title: 'Characters',
    loadComponent: () =>
      import('./pages/catalogue/characters').then((m) => m.CharactersPage),
    canMatch: [requireApproved],
  },
  {
    path: 'weapons',
    title: 'Weapons',
    loadComponent: () => import('./pages/catalogue/weapons').then((m) => m.WeaponsPage),
    canMatch: [requireApproved],
  },
  {
    // **Your** weapons, not the catalogue's. `/weapons` lists all 260 in the game; this lists
    // what the export says you own, with the holder's face on each and equipped ones first.
    path: 'my-weapons',
    title: 'My weapons',
    loadComponent: () =>
      import('./pages/weapons-inventory/weapons-inventory').then((m) => m.WeaponsInventoryPage),
    canMatch: [requireApproved],
  },
  {
    path: 'artifact-sets',
    title: 'Artifact sets',
    loadComponent: () =>
      import('./pages/catalogue/artifact-sets').then((m) => m.ArtifactSetsPage),
    canMatch: [requireApproved],
  },
  {
    // **One page, a tab per question** — `docs/DESIGN_upgrade_estimator.md` §11 (owner,
    // 2026-10-24). Inventory, Optimize, Rank and Upgrade all ask about the same pieces, three
    // of them for the same build; they were three nav entries that each re-asked for it.
    //
    // `/artifacts` used to be a redirect *to* `/inventory`; this reverses that pointer rather
    // than inventing a path. The set catalogue stays at `/artifact-sets` and its nav label
    // stays "Artifact sets", so the old ambiguity (two links reading "Artifacts") does not
    // come back.
    //
    // The guard is on the parent: `canMatch` failing here means no child can match either.
    path: 'artifacts',
    // A fallback only: each tab's own title is deeper and wins.
    title: 'Artifacts',
    loadComponent: () =>
      import('./pages/artifacts/artifacts-shell').then((m) => m.ArtifactsShell),
    canMatch: [requireApproved],
    children: [
      { path: '', redirectTo: 'inventory', pathMatch: 'full' },
      {
        path: 'inventory',
        title: 'Inventory',
        data: { mode: 'inventory' },
        loadComponent: () => import('./pages/artifacts/artifacts').then((m) => m.ArtifactsPage),
      },
      {
        path: 'optimize',
        title: 'Optimize',
        loadComponent: () => import('./pages/optimize/optimize').then((m) => m.OptimizePage),
      },
      {
        path: 'rank',
        title: 'Rank',
        data: { mode: 'rank' },
        loadComponent: () => import('./pages/artifacts/artifacts').then((m) => m.ArtifactsPage),
      },
      {
        path: 'upgrade',
        title: 'Upgrade',
        loadComponent: () => import('./pages/upgrade/upgrade').then((m) => m.UpgradePage),
      },
    ],
  },
  {
    // The old paths still resolve. Redirects rather than deletions: `/inventory` has been the
    // landing page and `/optimize` the search since they shipped, and a bookmark landing on
    // the catch-all would arrive somewhere with no indication why.
    path: 'inventory',
    redirectTo: 'artifacts/inventory',
    pathMatch: 'full',
  },
  {
    path: 'optimize',
    redirectTo: 'artifacts/optimize',
    pathMatch: 'full',
  },
  {
    path: 'builds',
    title: 'Builds',
    loadComponent: () => import('./pages/builds/builds').then((m) => m.BuildsPage),
    canMatch: [requireApproved],
  },
  {
    path: 'teams',
    title: 'Teams',
    loadComponent: () => import('./pages/teams/teams').then((m) => m.TeamsPage),
    canMatch: [requireApproved],
  },
  {
    // Renamed from `explain` (owner ruling): this page runs a whole rotation for a whole team,
    // where the old one explained one hit for one build. `/explain` still resolves so a
    // bookmark does not 404 — a rename that breaks links is a rename that loses readers.
    path: 'calculate',
    title: 'Calculate',
    loadComponent: () => import('./pages/calculate/calculate').then((m) => m.CalculatePage),
    canMatch: [requireApproved],
  },
  {
    path: 'rotations',
    title: 'Rotations',
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
    title: 'Teapot sets',
    loadComponent: () => import('./pages/teapot/teapot').then((m) => m.TeapotPage),
    canMatch: [requireApproved],
  },
  {
    path: 'enemies',
    title: 'Enemies',
    loadComponent: () => import('./pages/catalogue/enemies').then((m) => m.EnemiesPage),
    canMatch: [requireApproved],
  },
  {
    // **Straight to `/artifacts/inventory`, not via `''`.** It pointed at `''` while `''` rendered the
    // landing page. Now that `''` is itself a redirect, that was two hops — and Angular
    // resolves one redirect per recognition pass, so an unknown URL landed on `/` and stopped
    // there, on a path with no component, rendering nothing. Caught by walking the chain in a
    // test rather than assuming it; the guards' `createUrlTree(['/'])` *does* chain, because
    // a guard redirect starts a fresh navigation, and there is a test for that too.
    path: '**',
    redirectTo: 'artifacts/inventory',
  },
];
