import { Component, input } from '@angular/core';

@Component({
  selector: 'optimizer-diagnostics',
  templateUrl: './optimizer-diagnostics.html',
})
export class OptimizerDiagnostics {
  diagnostics = input<{ evaluated: number; pruned_sets: number; pruned_stats: number } | null>(null);
  errorMessage = input<string | null>(null);
  isRunning = input(false);
}
