import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService, PendingUserError } from '../../api/auth.service';
import { apiErrorMessage } from '../../api/api-error';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class LoginPage {
  private auth = inject(AuthService);
  private router = inject(Router);

  mode = signal<'signin' | 'register'>('signin');

  /** Set once registration is accepted, so the form is replaced by "check your email". */
  registered = signal(false);

  /**
   * The honeypot.
   *
   * Hidden from people and from assistive technology; naive form-filling bots populate every
   * input they find. A non-empty value gets the *same* 202 from the backend, which creates
   * nothing and sends nothing — a distinguishable rejection would tell the bot's author which
   * field to skip, and the trap is worth more than the block.
   */
  website = signal('');
  email = signal('');
  label = signal('');
  password = signal('');
  confirmPassword = signal('');
  error = signal('');
  loading = signal(false);

  get password2Mismatch(): boolean {
    return this.confirmPassword() !== '' && this.password() !== this.confirmPassword();
  }

  async signIn(): Promise<void> {
    this.error.set('');
    this.loading.set(true);
    try {
      await this.auth.login(this.email().trim(), this.password());
      await this.router.navigateByUrl('/');
    } catch (e) {
      if (e instanceof PendingUserError) {
        await this.router.navigateByUrl('/pending');
      } else {
        this.error.set('Invalid email or password.');
      }
    } finally {
      this.loading.set(false);
    }
  }

  async requestAccess(): Promise<void> {
    if (this.password2Mismatch) return;
    this.error.set('');
    this.loading.set(true);
    try {
      await this.auth.register({
        email: this.email().trim(),
        label: this.label(),
        password: this.password(),
        website: this.website(),
      });
      // **Always this, whatever the address.** The backend answers 202 identically for a new
      // address and one already registered, so there is nothing here to branch on — and a
      // branch would be the enumeration oracle put back by the client.
      this.registered.set(true);
    } catch (e: unknown) {
      // `apiErrorMessage`, not a local extractor. This page used to carry its own, which
      // handled only the *string* form of `detail` — and FastAPI sends an **array** for
      // request-validation errors. So a 422 saying "String should have at least 12
      // characters" fell through to the fallback below, and a user with a short password
      // was told their email was taken. They would look at the wrong field indefinitely.
      this.error.set(apiErrorMessage(e) || 'Registration failed. Please try again.');
    } finally {
      this.loading.set(false);
    }
  }
}
