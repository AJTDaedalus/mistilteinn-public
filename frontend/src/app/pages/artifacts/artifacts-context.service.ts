import { Injectable, signal } from '@angular/core';

/**
 * The rotation and build the Artifacts tabs are asking about, shared between them.
 *
 * `docs/DESIGN_upgrade_estimator.md` §11. Rank and Upgrade ask different questions of the same
 * build, so choosing it twice — once per tab — was the friction the tabs exist to remove. A
 * root singleton rather than state on the shell: the tabs are sibling routes, each a fresh
 * component instance, and the choice has to survive switching between them.
 *
 * Optimize keeps its own pickers for now (`remembered.ts` persists them across reloads); folding
 * them in is the shared context bar §11 describes, and is recorded there as not yet done.
 */
@Injectable({ providedIn: 'root' })
export class ArtifactsContextService {
  readonly rotationId = signal('');
  readonly buildId = signal('');
}
