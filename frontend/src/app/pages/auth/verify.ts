import { Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService, type VerifyFailureReason } from '../../api/auth.service';

type State = 'verifying' | 'approved' | 'pending' | 'failed';

@Component({
  selector: 'app-verify',
  templateUrl: './verify.html',
  styleUrl: './verify.scss',
})
export class VerifyPage implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);

  state = signal<State>('verifying');
  reason = signal<VerifyFailureReason>('invalid');
  resent = signal(false);
  private token = '';

  async ngOnInit(): Promise<void> {
    const url = new URL(window.location.href);
    this.token = url.searchParams.get('token') ?? '';

    // Strip the token from the address bar before anything else can observe it. The
    // POST below keeps it out of server logs; this keeps it out of the user's own
    // history and out of any Referer we send later.
    url.searchParams.delete('token');
    window.history.replaceState({}, '', url.pathname + url.search);

    if (!this.token) {
      this.state.set('failed');
      return;
    }

    const outcome = await this.auth.verifyEmail(this.token);
    if (!outcome.ok) {
      this.reason.set(outcome.reason);
      this.state.set('failed');
      return;
    }

    this.state.set(outcome.status);
    if (outcome.status === 'approved') {
      await this.router.navigateByUrl('/');
    }
  }

  /**
   * Ask for a fresh link. Requires the address, which we deliberately do not have —
   * the expired token is spent and the page never knew who it belonged to — so this
   * hands the user to the sign-in page, which does.
   */
  async goToSignIn(): Promise<void> {
    await this.router.navigateByUrl('/login');
  }
}
