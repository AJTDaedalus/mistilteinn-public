import { Injectable, Signal, computed, signal } from '@angular/core';
import { injectApi } from './api.client';
import type { components } from './api.types';

type MeResponse = components['schemas']['MeResponse'];

const STORAGE_KEY = 'fairy.token';

export class PendingUserError extends Error {
  constructor() {
    super('pending');
    this.name = 'PendingUserError';
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private api = injectApi();

  private _token = signal<string | null>(localStorage.getItem(STORAGE_KEY));
  private _me = signal<MeResponse | null>(null);

  readonly token: Signal<string | null> = this._token.asReadonly();
  readonly me: Signal<MeResponse | null> = this._me.asReadonly();

  readonly status: Signal<'unauthed' | 'pending' | 'approved'> = computed(() => {
    if (!this._token()) return 'unauthed';
    if (this._me()?.status === 'approved') return 'approved';
    return 'pending';
  });

  private writeToken(t: string | null): void {
    this._token.set(t);
    if (t === null) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, t);
    }
  }

  /** Clear local auth state only — no backend call. Used by the API middleware on 401. */
  clearLocalAuth(): void {
    this.writeToken(null);
    this._me.set(null);
  }

  async refresh(): Promise<void> {
    if (!this._token()) return;
    const { data, error, response } = await this.api.GET('/api/v1/auth/me');
    if (response.status === 401) {
      this.clearLocalAuth();
      return;
    }
    if (error) return;
    this._me.set(data ?? null);
  }

  async register({ email, label, password }: { email: string; label: string; password: string }): Promise<'pending'> {
    const { error } = await this.api.POST('/api/v1/auth/register', {
      body: { email, label, password },
    });
    if (error) throw error;
    return 'pending';
  }

  async login(email: string, password: string): Promise<'approved'> {
    const { data, response } = await this.api.POST('/api/v1/auth/login', {
      body: { email, password },
    });
    if (response.status === 403) throw new PendingUserError();
    if (!data) throw new Error('login failed');
    this.writeToken(data.token);
    await this.refresh();
    return 'approved';
  }

  async logout(): Promise<void> {
    // Clear local state first so the token can't be used by any concurrent
    // requests or be picked up by the onResponse middleware during the
    // backend call below.
    this.clearLocalAuth();
    try {
      await this.api.POST('/api/v1/auth/logout', {});
    } catch {
      // best-effort
    }
  }
}
