import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { CatalogueIcon } from './shared/icon/icon';
import { Emblem } from './shared/emblem/emblem';
import { AuthService } from './api/auth.service';
import { SOURCE_CODE } from './shared/source';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Emblem, CatalogueIcon],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected auth = inject(AuthService);
  private router = inject(Router);

  /** The AGPL §13 source offer the footer carries. */
  protected readonly source = SOURCE_CODE;

  async signOut(): Promise<void> {
    await this.auth.logout();
    await this.router.navigateByUrl('/login');
  }
}
