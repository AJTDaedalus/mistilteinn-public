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
    path: 'calculate',
    loadComponent: () => import('./pages/calculate/calculate').then((m) => m.CalculatePage),
    canMatch: [requireApproved],
  },
  {
    path: 'builds',
    loadComponent: () => import('./pages/builds/builds-list').then((m) => m.BuildsListPage),
    canMatch: [requireApproved],
  },
  {
    path: 'builds/new',
    loadComponent: () => import('./pages/builds/build-editor').then((m) => m.BuildEditorPage),
    canMatch: [requireApproved],
  },
  {
    path: 'builds/:id',
    loadComponent: () => import('./pages/builds/build-editor').then((m) => m.BuildEditorPage),
    canMatch: [requireApproved],
  },
  {
    path: 'optimize',
    loadComponent: () => import('./pages/optimize/optimize-page').then((m) => m.OptimizePage),
    canMatch: [requireApproved],
  },
  {
    path: 'discs',
    loadComponent: () => import('./pages/discs/disc-inventory').then((m) => m.DiscInventoryPage),
    canMatch: [requireApproved],
  },
  {
    path: 'import',
    loadComponent: () => import('./pages/import/import-page').then((m) => m.ImportPage),
    canMatch: [requireApproved],
  },
  {
    path: 'rank',
    loadComponent: () => import('./pages/rank/rank-page').then((m) => m.RankPage),
    canMatch: [requireApproved],
  },
  {
    path: 'teams',
    loadComponent: () => import('./pages/teams/teams-list').then((m) => m.TeamsListPage),
    canMatch: [requireApproved],
  },
  {
    path: 'teams/new',
    loadComponent: () => import('./pages/teams/team-editor').then((m) => m.TeamEditorPage),
    canMatch: [requireApproved],
  },
  {
    path: 'teams/:id',
    loadComponent: () => import('./pages/teams/team-editor').then((m) => m.TeamEditorPage),
    canMatch: [requireApproved],
  },
  {
    path: '**',
    redirectTo: '',
  },
];
