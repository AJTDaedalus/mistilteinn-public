import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { GcsimJob, GcsimReply } from './gcsim-protocol';
import { deadlineMs, GcsimTimeoutError, SAMPLE_ITERATION_EQUIVALENT } from './gcsim-runner';
import { WorkerGcsimRunner, type WorkerLike } from './gcsim-worker-runner';

/**
 * The deadline and the replacement, against a fake worker.
 *
 * jsdom has no `Worker`, and the real one needs a 41 MB wasm — `scripts/verify-gcsim-runner.mjs`
 * drives that, including a planted hang. What a fake proves is the **bookkeeping**: that the
 * clock starts when the job starts and not while the module downloads, that a job past its
 * deadline kills the worker and says why, and that the next job gets a fresh one.
 */

/** A worker whose replies the test writes. `hang` makes it start a job and never finish. */
class FakeWorker implements WorkerLike {
  onmessage: ((event: MessageEvent<GcsimReply>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  readonly jobs: GcsimJob[] = [];
  terminated = false;

  constructor(private readonly behaviour: (job: GcsimJob, fake: FakeWorker) => void) {}

  postMessage(job: GcsimJob): void {
    this.jobs.push(job);
    queueMicrotask(() => this.behaviour(job, this));
  }

  terminate(): void {
    this.terminated = true;
  }

  send(reply: GcsimReply): void {
    this.onmessage?.({ data: reply } as MessageEvent<GcsimReply>);
  }
}

const RUN = { iterations: 1, totalDamage: 1, dps: { mean: 2, sd: 0 }, raw: {} };

/** Starts and completes every job, reporting progress for a run. */
const healthy = (job: GcsimJob, fake: FakeWorker) => {
  fake.send({ id: job.id, type: 'started' });
  if (job.kind === 'run') {
    for (let i = 1; i <= job.iterations; i++) {
      fake.send({ id: job.id, type: 'progress', done: i, total: job.iterations });
    }
    fake.send({ id: job.id, type: 'ran', run: { ...RUN, iterations: job.iterations } });
  } else if (job.kind === 'sample') {
    fake.send({ id: job.id, type: 'sampled', log: '{"logs":[]}' });
  } else {
    fake.send({ id: job.id, type: 'validated', error: null });
  }
};

/** Starts every job and never finishes it: the ungated burst. */
const hangs = (job: GcsimJob, fake: FakeWorker) => fake.send({ id: job.id, type: 'started' });

function runnerWith(...behaviours: ((job: GcsimJob, fake: FakeWorker) => void)[]) {
  const created: FakeWorker[] = [];
  const runner = new WorkerGcsimRunner({
    base: 'http://test.local/gcsim/',
    createWorker: () => {
      const fake = new FakeWorker(behaviours[Math.min(created.length, behaviours.length - 1)]);
      created.push(fake);
      return fake;
    },
    deadline: (iterations) => 1_000 + 100 * iterations,
  });
  return { runner, created };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('WorkerGcsimRunner', () => {
  it('returns the run and relays progress, as the synchronous runner did', async () => {
    const { runner, created } = runnerWith(healthy);
    const seen: [number, number][] = [];

    const result = await runner.run('cfg', 3, (done, total) => seen.push([done, total]));

    expect(result.iterations).toBe(3);
    expect(result.dps?.mean).toBe(2);
    expect(seen).toEqual([[1, 3], [2, 3], [3, 3]]);
    expect(created[0].jobs[0]).toMatchObject({
      kind: 'run', config: 'cfg', iterations: 3, base: 'http://test.local/gcsim/',
    });
  });

  it('kills a job that runs past its deadline and names the cause', async () => {
    const { runner, created } = runnerWith(hangs);

    const pending = runner.run('cfg', 10);
    const outcome = pending.catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(1_000 + 100 * 10 + 1);

    const error = await outcome;
    expect(error).toBeInstanceOf(GcsimTimeoutError);
    expect((error as Error).message).toContain('did not finish within 2 s');
    // The sentence a user needs, not just a number: what usually causes it.
    expect((error as Error).message).toMatch(/burst/);
    expect(created[0].terminated).toBe(true);
  });

  it('does not fire before the deadline', async () => {
    const { runner, created } = runnerWith(hangs);
    const outcome = runner.run('cfg', 10).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(created[0].terminated).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    expect(await outcome).toBeInstanceOf(GcsimTimeoutError);
  });

  it('starts the clock when the job starts, not while the module loads', async () => {
    // The first job pays a 41 MB download and compile. Counting that against the deadline
    // would time out a healthy first run on a slow connection.
    let start: (() => void) | null = null;
    const { runner } = runnerWith((job, fake) => {
      start = () => {
        fake.send({ id: job.id, type: 'started' });
        fake.send({ id: job.id, type: 'ran', run: RUN });
      };
    });
    const pending = runner.run('cfg', 1);
    await vi.advanceTimersByTimeAsync(60_000); // "loading" for a minute
    start!();
    await expect(pending).resolves.toMatchObject({ iterations: 1 });
  });

  it('runs the next job on a fresh worker after a kill', async () => {
    const { runner, created } = runnerWith(hangs, healthy);

    const first = runner.run('hangs', 1).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(1_101);
    expect(await first).toBeInstanceOf(GcsimTimeoutError);

    const second = await runner.run('fine', 2);
    expect(second.iterations).toBe(2);
    expect(created).toHaveLength(2);
    expect(created[1].terminated).toBe(false);
  });

  it('keeps the worker after gcsim refuses a config', async () => {
    // A refusal is a fact about the config; the worker and its loaded module are fine, and
    // re-downloading 41 MB for the next job would be a cost for nothing.
    const { runner, created } = runnerWith((job, fake) => {
      if (job.config === 'bad') {
        fake.send({ id: job.id, type: 'started' });
        fake.send({ id: job.id, type: 'failed', message: 'gcsim rejected the config: nope' });
      } else {
        healthy(job, fake);
      }
    });

    await expect(runner.run('bad', 1)).rejects.toThrow('gcsim rejected the config: nope');
    await expect(runner.run('good', 1)).resolves.toMatchObject({ iterations: 1 });
    expect(created).toHaveLength(1);
    expect(created[0].terminated).toBe(false);
  });

  it('discards a worker that errors and recovers on the next job', async () => {
    const { runner, created } = runnerWith(
      (_job, fake) => fake.onerror?.({ message: 'boom', preventDefault: vi.fn() } as unknown as ErrorEvent),
      healthy,
    );
    await expect(runner.run('cfg', 1)).rejects.toThrow('the gcsim worker failed: boom');
    await expect(runner.run('cfg', 1)).resolves.toBeTruthy();
    expect(created[0].terminated).toBe(true);
    expect(created).toHaveLength(2);
  });

  it('runs jobs one at a time, because gcsim aggregates into global state', async () => {
    // Two runs interleaved in one Go instance would aggregate into each other. On the main
    // thread that was impossible; once runs are asynchronous it is not.
    const order: string[] = [];
    const { runner, created } = runnerWith((job, fake) => {
      order.push(`start ${job.config}`);
      setTimeout(() => {
        order.push(`end ${job.config}`);
        healthy(job, fake);
      }, 10);
    });

    const a = runner.run('a', 1);
    const b = runner.run('b', 1);
    await vi.advanceTimersByTimeAsync(50);
    await Promise.all([a, b]);

    expect(order).toEqual(['start a', 'end a', 'start b', 'end b']);
    expect(created).toHaveLength(1);
  });

  it('gives validate and sample their own deadlines and payloads', async () => {
    const { runner, created } = runnerWith(healthy);
    await expect(runner.validate('cfg')).resolves.toBeNull();
    await expect(runner.sample('cfg', '7')).resolves.toBe('{"logs":[]}');
    expect(created[0].jobs.map((j) => j.kind)).toEqual(['validate', 'sample']);
    expect(created[0].jobs[1]).toMatchObject({ seed: '7' });
  });

  it('refuses a non-positive iteration count without starting a worker', async () => {
    const { runner, created } = runnerWith(healthy);
    await expect(runner.run('cfg', 0)).rejects.toThrow('positive integer');
    expect(created).toHaveLength(0);
  });
});

describe('deadlineMs', () => {
  it('scales with the iteration count over a floor', () => {
    expect(deadlineMs(100)).toBeGreaterThan(deadlineMs(60));
    expect(deadlineMs(0)).toBeGreaterThan(0);
  });

  it('leaves ample headroom over the slowest real config measured', () => {
    // 125.2 ms/iteration: the worst config in the gcsim database corpus, on a loaded host.
    // The deadline must be several times that, or a slow laptop times out a real search.
    const worst = 125.2;
    for (const n of [1, 20, 60, 100]) expect(deadlineMs(n)).toBeGreaterThan(5 * worst * n);
    // And a sample — logging every frame — measured at 3.78 s worst, quiet.
    expect(deadlineMs(SAMPLE_ITERATION_EQUIVALENT)).toBeGreaterThan(10 * 3_780);
  });
});
