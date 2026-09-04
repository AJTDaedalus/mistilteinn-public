import { Injectable, Signal, computed, signal } from '@angular/core';
import { injectApi } from './api.client';
import type { components } from './api.types';

type MeResponse = components['schemas']['MeResponse'];

const STORAGE_KEY = 'mistilteinn.token';

export class PendingUserError extends Error {
  constructor() {
    super('pending');
    this.name = 'PendingUserError';
  }
}

export type VerifyFailureReason = 'expired' | 'already_used' | 'invalid';

export type VerifyOutcome =
  | { ok: true; status: 'approved' | 'pending' }
  | { ok: false; reason: VerifyFailureReason };

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

  /**
   * Begin registration.
   *
   * **Returns the same thing for every well-formed request**, including an address that is
   * already registered. The backend used to answer 409 for a duplicate, which was a free
   * membership-checking API for anyone who found the URL; there is deliberately no branch
   * here to reintroduce it. What the user is told is "check your email", always.
   *
   * `website` is the honeypot and is sent empty by the real form. `turnstileToken` is empty
   * until Turnstile keys exist, which the backend treats as "skip verification".
   */
  async register({
    email,
    label,
    password,
    turnstileToken = '',
    website = '',
  }: {
    email: string;
    label: string;
    password: string;
    turnstileToken?: string;
    website?: string;
  }): Promise<'verification_sent'> {
    const { error } = await this.api.POST('/api/v1/auth/register', {
      body: { email, label, password, turnstile_token: turnstileToken, website },
    });
    if (error) throw error;
    return 'verification_sent';
  }

  /**
   * Consume an emailed verification link.
   *
   * **Auto-approval hands back a session in the same response**, so one click leaves the user
   * signed in rather than bouncing them to a login form for a password they typed two minutes
   * ago. That is the whole UX win of this feature.
   */
  async verifyEmail(token: string): Promise<VerifyOutcome> {
    const { data, error, response } = await this.api.POST('/api/v1/auth/verify-email', {
      body: { token },
    });
    if (response.status === 400) {
      const reason = (error as { detail?: { reason?: string } })?.detail?.reason;
      return {
        ok: false,
        reason: reason === 'expired' || reason === 'already_used' ? reason : 'invalid',
      };
    }
    if (!data) return { ok: false, reason: 'invalid' };

    if (data.session_token) {
      this.writeToken(data.session_token);
      await this.refresh();
    }
    return { ok: true, status: data.status };
  }

  /**
   * Ask for a fresh confirmation link.
   *
   * Answers `true` for every address — known, unknown, or already verified — because
   * anything else would make this the enumeration oracle `register` was changed to stop
   * being. **It has a caller**: fairy shipped this method with none at all, so a user whose
   * 24-hour link lapsed had no route to a new one and the distinct `expired` outcome existed
   * to offer something nothing consumed.
   */
  async resendVerification(email: string, turnstileToken = ''): Promise<boolean> {
    const { response } = await this.api.POST('/api/v1/auth/resend-verification', {
      body: { email, turnstile_token: turnstileToken },
    });
    return response.status === 202;
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
