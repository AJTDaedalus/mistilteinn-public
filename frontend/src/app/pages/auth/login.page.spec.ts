import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE_URL } from '../../api/api.client';
import { AuthService, PendingUserError } from '../../api/auth.service';
import { LoginPage } from './login';

function setup() {
  TestBed.configureTestingModule({
    imports: [LoginPage],
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  const fixture = TestBed.createComponent(LoginPage);
  fixture.detectChanges();
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
});

describe('LoginPage', () => {
  describe('signIn()', () => {
    it('calls auth.login with email and password and navigates to / on success', async () => {
      const { comp, auth, router } = setup();
      const loginSpy = vi.spyOn(auth, 'login').mockResolvedValue('approved');
      const navSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

      comp.email.set('user@example.com');
      comp.password.set('test-password-123');
      await comp.signIn();

      expect(loginSpy).toHaveBeenCalledWith('user@example.com', 'test-password-123');
      expect(navSpy).toHaveBeenCalledWith('/');
    });

    it('navigates to /pending when login throws PendingUserError', async () => {
      const { comp, auth, router } = setup();
      vi.spyOn(auth, 'login').mockRejectedValue(new PendingUserError());
      const navSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

      comp.email.set('pending@example.com');
      comp.password.set('test-password-123');
      await comp.signIn();

      expect(navSpy).toHaveBeenCalledWith('/pending');
    });

    it('sets error message on generic login failure', async () => {
      const { comp, auth } = setup();
      vi.spyOn(auth, 'login').mockRejectedValue(new Error('unauthorized'));
      vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);

      comp.email.set('user@example.com');
      comp.password.set('wrong-pass-123');
      await comp.signIn();

      expect(comp.error()).toBe('Invalid email or password.');
    });
  });

  describe('requestAccess()', () => {
    it('registers and shows "check your email" rather than navigating', async () => {
      // **It used to navigate to `/pending`.** Registration no longer creates an approved-or-
      // pending account synchronously — it queues a verification email — so the honest next
      // screen is "check your email", and the user is not signed in to have a pending state.
      const { comp, auth, router } = setup();
      const regSpy = vi.spyOn(auth, 'register').mockResolvedValue('verification_sent');
      const navSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

      comp.email.set('new@example.com');
      comp.label.set('tester');
      comp.password.set('strong-pass-456');
      comp.confirmPassword.set('strong-pass-456');
      await comp.requestAccess();

      expect(regSpy).toHaveBeenCalledWith({
        email: 'new@example.com',
        label: 'tester',
        password: 'strong-pass-456',
        website: '',
      });
      expect(comp.registered()).toBe(true);
      expect(navSpy).not.toHaveBeenCalled();
    });

    it('sends the honeypot value it was given', async () => {
      // The field is invisible, so a filled one means a bot. The client sends it rather than
      // judging it: the *backend* answers 202 and creates nothing, because a rejection the
      // client could show would tell the bot's author which field to skip.
      const { comp, auth } = setup();
      const regSpy = vi.spyOn(auth, 'register').mockResolvedValue('verification_sent');

      comp.email.set('bot@example.com');
      comp.password.set('strong-pass-456');
      comp.confirmPassword.set('strong-pass-456');
      comp.website.set('http://spam.example');
      await comp.requestAccess();

      expect(regSpy).toHaveBeenCalledWith(
        expect.objectContaining({ website: 'http://spam.example' }),
      );
    });

    it('does not submit when passwords do not match', async () => {
      const { comp, auth } = setup();
      const regSpy = vi.spyOn(auth, 'register').mockResolvedValue('verification_sent');

      comp.email.set('new@example.com');
      comp.password.set('strong-pass-456');
      comp.confirmPassword.set('different-pass-789');
      await comp.requestAccess();

      expect(regSpy).not.toHaveBeenCalled();
    });

    it('shows server error message on registration failure', async () => {
      const { comp, auth } = setup();
      vi.spyOn(auth, 'register').mockRejectedValue({ detail: 'Email already registered' });
      vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);

      comp.email.set('taken@example.com');
      comp.password.set('strong-pass-456');
      comp.confirmPassword.set('strong-pass-456');
      await comp.requestAccess();

      expect(comp.error()).toBe('Email already registered');
    });

    it('surfaces a 422 validation message instead of blaming the email', async () => {
      // The bug this exists to prevent, found in production by a real user.
      //
      // FastAPI sends `detail` as a **string** for HTTPException and as an **array** for
      // request-validation errors. This page carried its own extractor that handled only
      // the string form, so a 422 fell through to a fallback reading "this email may
      // already be registered" — and a user whose password was 8 characters was told to
      // change their email. They would look at the wrong field indefinitely.
      //
      // The test above passed throughout, because it only ever exercised the shape that
      // worked.
      const { comp, auth } = setup();
      vi.spyOn(auth, 'register').mockRejectedValue({
        detail: [
          {
            type: 'string_too_short',
            loc: ['body', 'password'],
            msg: 'String should have at least 12 characters',
          },
        ],
      });
      vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);

      comp.email.set('new@example.com');
      comp.password.set('short123');
      comp.confirmPassword.set('short123');
      await comp.requestAccess();

      expect(comp.error()).toBe('String should have at least 12 characters');
      expect(comp.error()).not.toContain('already');
    });
  });

  describe('password2Mismatch', () => {
    it('is false when confirmPassword is empty', () => {
      const { comp } = setup();
      comp.password.set('somepass');
      comp.confirmPassword.set('');
      expect(comp.password2Mismatch).toBe(false);
    });

    it('is true when confirmPassword is non-empty and does not match', () => {
      const { comp } = setup();
      comp.password.set('somepass');
      comp.confirmPassword.set('other');
      expect(comp.password2Mismatch).toBe(true);
    });

    it('is false when passwords match', () => {
      const { comp } = setup();
      comp.password.set('match-me-now');
      comp.confirmPassword.set('match-me-now');
      expect(comp.password2Mismatch).toBe(false);
    });
  });
});
