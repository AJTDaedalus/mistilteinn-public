import { inject } from '@angular/core';
import { Router, type CanMatchFn } from '@angular/router';

import { AuthService } from './auth.service';

export const requireApproved: CanMatchFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const s = auth.status();
  if (s === 'approved') return true;
  if (s === 'pending') return router.createUrlTree(['/pending']);
  return router.createUrlTree(['/login']);
};

export const requireUnauthed: CanMatchFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (auth.status() === 'approved') return router.createUrlTree(['/']);
  return true;
};

export const requirePending: CanMatchFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const s = auth.status();
  if (s === 'pending' || s === 'unauthed') return true;
  return router.createUrlTree(['/']);
};
