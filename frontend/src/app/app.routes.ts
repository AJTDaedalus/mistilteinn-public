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
    path: 'artifacts',
    loadComponent: () => import('./pages/artifacts/artifacts').then((m) => m.ArtifactsPage),
    canMatch: [requireApproved],
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
