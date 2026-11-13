/**
 * gcsim, in a thread the page can kill.
 *
 * Every job runs through the **same** `run()` / `configError` the page used to call directly
 * (`gcsim.ts`), so moving off the main thread changed where gcsim runs and nothing about how
 * its answers are read. The deadline is not here — a worker stuck inside `simulate()` cannot
 * check a clock — it is in `gcsim-worker-runner.ts`, which calls `terminate()`.
 */

import { configError, run, type GcsimModule } from './gcsim';
import { instantiateGcsim } from './gcsim-loader';
import type { GcsimJob, GcsimReply } from './gcsim-protocol';

let loading: Promise<GcsimModule> | null = null;

function reply(message: GcsimReply): void {
  postMessage(message);
}

addEventListener('message', (event: MessageEvent<GcsimJob>) => {
  void handle(event.data);
});

async function handle(job: GcsimJob): Promise<void> {
  try {
    // Memoised on the promise and cleared on failure, as the page-side loader was: a 404 during
    // a deploy should fail this job, not every job this worker will ever be sent.
    loading ??= instantiateGcsim(job.base).catch((error: unknown) => {
      loading = null;
      throw error;
    });
    const mod = await loading;
    reply({ id: job.id, type: 'started' });

    switch (job.kind) {
      case 'validate':
        reply({ id: job.id, type: 'validated', error: configError(mod.validateConfig(job.config)) });
        return;
      case 'sample':
        reply({ id: job.id, type: 'sampled', log: mod.sample(job.config, job.seed) });
        return;
      case 'run': {
        const result = run(mod, job.config, job.iterations, (done, total) =>
          reply({ id: job.id, type: 'progress', done, total }),
        );
        reply({ id: job.id, type: 'ran', run: result });
        return;
      }
    }
  } catch (error) {
    reply({
      id: job.id,
      type: 'failed',
      message: error instanceof Error ? error.message : String(error),
    });
  }
}
