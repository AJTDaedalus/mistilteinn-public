import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE_URL } from './api.client';
import { AuthService, PendingUserError } from './auth.service';

const STORAGE_KEY = 'mistilteinn.token';

function setup(): AuthService {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(AuthService);
}

function mockFetch(payload: unknown, status = 200) {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

function mockFetchSequence(responses: { payload: unknown; status?: number }[]) {
  let call = 0;
  globalThis.fetch = vi.fn(async () => {
    const r = responses[Math.min(call++, responses.length - 1)];
    return new Response(JSON.stringify(r.payload), {
      status: r.status ?? 200,
      headers: { 'content-type': 'application/json' },
    });
  });
}

/**
 * The first request the client actually sent.
 *
 * `openapi-fetch` calls `fetch(new Request(...))` — one argument, not the `(url, init)` pair
 * the older style assumes — and reading it wrongly gives an assertion that passes on
 * `'[object Request]'` containing nothing.
 */
function requestSent(call = 0): Request {
  return (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[call][0] as Request;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  TestBed.resetTestingModule();
  vi.restoreAllMocks();
});

describe('AuthService', () => {
  describe('setAvatar', () => {
    const AVATAR = {
      email: 'a@example.com',
      label: 'A',
      status: 'approved',
      avatar: { character_id: 'char-1', name: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka' },
    };

    it('puts the chosen character and adopts the response as the new me', async () => {
      // **The response is adopted rather than a `refresh()` fired.** The header chip reads
      // `me`, so a second round trip is a window in which the page shows the old face after a
      // save that worked.
      mockFetch(AVATAR);
      const svc = setup();

      await svc.setAvatar('char-1');

      const sent = requestSent();
      expect(sent.url).toContain('/api/v1/auth/me/avatar');
      expect(sent.method).toBe('PUT');
      expect(await sent.json()).toEqual({ character_id: 'char-1' });
      expect(svc.me()?.avatar?.name).toBe('Kamisato Ayaka');
    });

    it('sends null to clear it', async () => {
      mockFetch({ ...AVATAR, avatar: null });
      const svc = setup();

      await svc.setAvatar(null);

      expect(await requestSent().json()).toEqual({ character_id: null });
      expect(svc.me()?.avatar).toBeNull();
    });

    it('throws and leaves me alone when the server refuses', async () => {
      // A 404 means the id named nothing. Adopting a failure response — or silently
      // succeeding — would leave the page showing an avatar the account does not have.
      mockFetch({ detail: 'No such character.' }, 404);
      const svc = setup();

      await expect(svc.setAvatar('gone')).rejects.toBeDefined();
      expect(svc.me()).toBeNull();
    });
  });

  describe('initial state', () => {
    it('is unauthed when localStorage has no token', () => {
      const svc = setup();
      expect(svc.token()).toBeNull();
      expect(svc.me()).toBeNull();
      expect(svc.status()).toBe('unauthed');
    });

    it('reads stored token and starts as pending (me not yet fetched)', () => {
      localStorage.setItem(STORAGE_KEY, 'stored-tok');
      const svc = setup();
      expect(svc.token()).toBe('stored-tok');
      expect(svc.status()).toBe('pending');
    });
  });

  describe('refresh()', () => {
    it('skips the API call when no token is set', async () => {
      globalThis.fetch = vi.fn();
      const svc = setup();
      await svc.refresh();
      expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled();
    });

    it('sets me and flips status to approved on a 200 approved response', async () => {
      localStorage.setItem(STORAGE_KEY, 'tok');
      mockFetch({ email: 'a@b.com', label: 'dev', status: 'approved' });
      const svc = setup();

      await svc.refresh();

      expect(svc.me()).toEqual({ email: 'a@b.com', label: 'dev', status: 'approved' });
      expect(svc.status()).toBe('approved');
    });

    it('keeps status pending on a 200 pending response', async () => {
      localStorage.setItem(STORAGE_KEY, 'tok');
      mockFetch({ email: 'a@b.com', label: 'dev', status: 'pending' });
      const svc = setup();

      await svc.refresh();

      expect(svc.me()?.status).toBe('pending');
      expect(svc.status()).toBe('pending');
    });

    it('calls logout on 401 — clears token, me, and localStorage', async () => {
      localStorage.setItem(STORAGE_KEY, 'tok');
      // 401 for /me, then any response for the logout POST
      mockFetchSequence([
        { payload: { detail: 'Unauthorized' }, status: 401 },
        { payload: {}, status: 204 },
      ]);
      const svc = setup();

      await svc.refresh();

      expect(svc.token()).toBeNull();
      expect(svc.me()).toBeNull();
      expect(svc.status()).toBe('unauthed');
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('leaves state unchanged on a non-401 error', async () => {
      localStorage.setItem(STORAGE_KEY, 'tok');
      mockFetch({ detail: 'Server error' }, 500);
      const svc = setup();

      await svc.refresh();

      expect(svc.token()).toBe('tok');
      expect(svc.me()).toBeNull();
      expect(svc.status()).toBe('pending');
    });
  });

  describe('register()', () => {
    it('does not store a token and reports that a verification email was sent', async () => {
      mockFetch({ status: 'pending' }, 201);
      const svc = setup();

      const result = await svc.register({ email: 'x@y.com', label: 'me', password: 'test-password-123' });

      expect(result).toBe('verification_sent');
      expect(svc.token()).toBeNull();
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('throws when the API returns an error', async () => {
      mockFetch({ detail: 'Email already registered' }, 409);
      const svc = setup();

      await expect(
        svc.register({ email: 'x@y.com', label: 'me', password: 'test-password-123' }),
      ).rejects.toBeTruthy();
    });
  });

  describe('login()', () => {
    it('stores the returned token, calls refresh, and returns approved', async () => {
      mockFetchSequence([
        { payload: { token: 'sess-tok', expires_at: '2099-01-01T00:00:00Z' }, status: 200 },
        { payload: { email: 'a@b.com', label: 'dev', status: 'approved' }, status: 200 },
      ]);
      const svc = setup();

      const result = await svc.login('a@b.com', 'good-pass-123');

      expect(result).toBe('approved');
      expect(svc.token()).toBe('sess-tok');
      expect(localStorage.getItem(STORAGE_KEY)).toBe('sess-tok');
    });

    it('throws PendingUserError on 403', async () => {
      mockFetch({ status: 'pending' }, 403);
      const svc = setup();

      await expect(svc.login('a@b.com', 'good-pass-123')).rejects.toBeInstanceOf(PendingUserError);
      expect(svc.token()).toBeNull();
    });

    it('throws on 401 and stores no token', async () => {
      mockFetch({ detail: 'Unauthorized' }, 401);
      const svc = setup();

      await expect(svc.login('a@b.com', 'wrong-pass-123')).rejects.toBeTruthy();
      expect(svc.token()).toBeNull();
    });
  });

  describe('logout()', () => {
    it('calls the backend logout endpoint, clears token, me, and localStorage', async () => {
      localStorage.setItem(STORAGE_KEY, 'tok');
      mockFetchSequence([
        { payload: { email: 'a@b.com', label: 'dev', status: 'approved' }, status: 200 },
        { payload: {}, status: 204 },
      ]);
      const svc = setup();
      await svc.refresh();
      expect(svc.token()).toBe('tok');

      await svc.logout();

      expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(2);
      expect(svc.token()).toBeNull();
      expect(svc.me()).toBeNull();
      expect(svc.status()).toBe('unauthed');
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('still clears local state even if the backend call fails', async () => {
      localStorage.setItem(STORAGE_KEY, 'tok');
      mockFetchSequence([
        { payload: { email: 'a@b.com', label: 'dev', status: 'approved' }, status: 200 },
        { payload: {}, status: 500 },
      ]);
      const svc = setup();
      await svc.refresh();

      await svc.logout();

      expect(svc.token()).toBeNull();
      expect(svc.status()).toBe('unauthed');
    });
  });
});
