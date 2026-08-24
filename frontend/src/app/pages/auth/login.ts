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
      await this.auth.register({ email: this.email().trim(), label: this.label(), password: this.password() });
      await this.router.navigateByUrl('/pending');
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
