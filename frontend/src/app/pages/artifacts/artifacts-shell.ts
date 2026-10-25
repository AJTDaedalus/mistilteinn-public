import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

/**
 * `/artifacts`: one page, a tab per question. `docs/DESIGN_upgrade_estimator.md` §11.
 *
 * Owner, 2026-10-24: the parent is **Artifacts** — *"make 'Search' 'Optimize'. That's what
 * everyone thinks when they hear optimize"* — with an Inventory tab for the raw pieces. The tabs
 * are **child routes**, not in-page state, so each is linkable and the back button works.
 */
@Component({
  selector: 'app-artifacts-shell',
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './artifacts-shell.html',
  styleUrl: './artifacts-shell.scss',
})
export class ArtifactsShell {
  protected readonly tabs = [
    { path: 'inventory', label: 'Inventory' },
    { path: 'optimize', label: 'Optimize' },
    { path: 'rank', label: 'Rank' },
    { path: 'upgrade', label: 'Upgrade' },
  ] as const;
}
