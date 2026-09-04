import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE_URL } from '../../api/api.client';
import { AuthService } from '../../api/auth.service';
import { VerifyPage } from './verify';

function setup(url = '/verify?token=raw-token-abc') {
  window.history.replaceState({}, '', url);
  TestBed.configureTestingModule({
    imports: [VerifyPage],
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  const fixture = TestBed.createComponent(VerifyPage);
  const comp = fixture.componentInstance;
  const auth = TestBed.inject(AuthService);
  const router = TestBed.inject(Router);
  return { fixture, comp, auth, router };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  TestBed.resetTestingModule();
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

describe('VerifyPage', () => {
  it('POSTs the token from the query string', async () => {
    const { comp, auth, router } = setup();
    const verifySpy = vi.spyOn(auth, 'verifyEmail').mockResolvedValue({
      ok: true,
      status: 'pending',
    });
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(verifySpy).toHaveBeenCalledWith('raw-token-abc');
  });

  it('strips the token from the address bar', async () => {
    // The POST keeps the token out of server logs; this keeps it out of the user's own
    // history and out of any Referer header the page sends afterwards.
    const { comp, auth, router } = setup();
    vi.spyOn(auth, 'verifyEmail').mockResolvedValue({ ok: true, status: 'pending' });
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(window.location.search).not.toContain('token');
  });

  it('strips the token even when verification fails', async () => {
    const { comp, auth, router } = setup();
    vi.spyOn(auth, 'verifyEmail').mockResolvedValue({ ok: false, reason: 'expired' });
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(window.location.search).not.toContain('token');
  });

  it('navigates to / when verification also approved the account', async () => {
    const { comp, auth, router } = setup();
    vi.spyOn(auth, 'verifyEmail').mockResolvedValue({ ok: true, status: 'approved' });
    const navSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(comp.state()).toBe('approved');
    expect(navSpy).toHaveBeenCalledWith('/');
  });

  it('stays put when the address is verified but the account is still pending', async () => {
    // The gate stays shut until Phase 4; verification alone must not imply access.
    const { comp, auth, router } = setup();
    vi.spyOn(auth, 'verifyEmail').mockResolvedValue({ ok: true, status: 'pending' });
    const navSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(comp.state()).toBe('pending');
    expect(navSpy).not.toHaveBeenCalled();
  });

  it('reports an expired link distinctly from an invalid one', async () => {
    // Distinct so the template can offer a way forward rather than a dead end that
    // reads as "the site is broken".
    const { comp, auth, router } = setup();
    vi.spyOn(auth, 'verifyEmail').mockResolvedValue({ ok: false, reason: 'expired' });
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(comp.state()).toBe('failed');
    expect(comp.reason()).toBe('expired');
  });

  it('reports an already-used link', async () => {
    const { comp, auth, router } = setup();
    vi.spyOn(auth, 'verifyEmail').mockResolvedValue({ ok: false, reason: 'already_used' });
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(comp.reason()).toBe('already_used');
  });

  it('fails without calling the API when the URL carries no token', async () => {
    const { comp, auth, router } = setup('/verify');
    const verifySpy = vi.spyOn(auth, 'verifyEmail');
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.ngOnInit();

    expect(verifySpy).not.toHaveBeenCalled();
    expect(comp.state()).toBe('failed');
  });

  it('sends the user to sign in from the failure state', async () => {
    const { comp, router } = setup();
    const navSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await comp.goToSignIn();

    expect(navSpy).toHaveBeenCalledWith('/login');
  });
});
