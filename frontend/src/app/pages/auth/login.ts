import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService, PendingUserError } from '../../api/auth.service';

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
      const detail = this._extractDetail(e);
      this.error.set(detail ?? 'Registration failed — this email may already be registered.');
    } finally {
      this.loading.set(false);
    }
  }

  private _extractDetail(e: unknown): string | null {
    if (e && typeof e === 'object' && 'detail' in e) {
      const d = (e as { detail: unknown }).detail;
      if (typeof d === 'string' && d.length <= 200) return d;
    }
    return null;
  }
}
