import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../../api/auth.service';

@Component({
  selector: 'app-pending',
  templateUrl: './pending.html',
  styleUrl: './pending.scss',
})
export class PendingPage {
  auth = inject(AuthService);
  private router = inject(Router);

  async logout(): Promise<void> {
    await this.auth.logout();
    await this.router.navigateByUrl('/login');
  }
}
