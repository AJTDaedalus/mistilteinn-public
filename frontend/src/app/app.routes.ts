import { Routes } from '@angular/router';

import { requireApproved, requirePending, requireUnauthed } from './api/auth.guards';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./pages/auth/login').then((m) => m.LoginPage),
    canMatch: [requireUnauthed],
  },
  {
    path: 'pending',
    loadComponent: () => import('./pages/auth/pending').then((m) => m.PendingPage),
    canMatch: [requirePending],
  },
  {
    path: '',
    loadComponent: () => import('./pages/landing/landing').then((m) => m.LandingPage),
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
    path: 'compare',
    loadComponent: () => import('./pages/compare/compare').then((m) => m.ComparePage),
    canMatch: [requireApproved],
  },
  {
    path: 'explain',
    loadComponent: () => import('./pages/explain/explain').then((m) => m.ExplainPage),
    canMatch: [requireApproved],
  },
  {
    path: 'rotations',
    loadComponent: () => import('./pages/rotations/rotations').then((m) => m.RotationsPage),
    canMatch: [requireApproved],
  },
  {
    path: 'enemies',
    loadComponent: () => import('./pages/catalogue/enemies').then((m) => m.EnemiesPage),
    canMatch: [requireApproved],
  },
  {
    path: '**',
    redirectTo: '',
  },
];
