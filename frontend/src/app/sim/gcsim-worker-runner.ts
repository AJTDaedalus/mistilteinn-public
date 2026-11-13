/**
 * The app's gcsim runner: a Web Worker, a deadline per job, and a fresh worker after a kill.
 *
 * `gcsim-runner.ts` says why the simulator lives in a worker at all. This file is the part that
 * can stop it: each job gets `deadlineMs(iterations)` from the moment the worker reports it has
 * *started* (so the one-off 41 MB download and compile on the first job is never mistaken for a
 * hang), and a job still running at the deadline gets `terminate()` — the only operation that
 * interrupts a `simulate()` that will never return. The next job builds a new worker.
 *
 * **Jobs run one at a time, in order.** gcsim's aggregator is global state inside the Go
 * program (`initializeAggregator` → `simulate`/`aggregate` → `flush`), so two runs interleaved
 * in one instance would aggregate into each other. On the main thread that could not happen,
 * because each run was synchronous; once runs are asynchronous it can, so this queues them.
 * One worker also means one 41 MB instance — W.4 measured peak RSS near 1 GB per instance.
 */

import type { GcsimRun } from './gcsim';
import type { GcsimJob, GcsimReply } from './gcsim-protocol';
import {
  deadlineMs,
  GcsimTimeoutError,
  SAMPLE_ITERATION_EQUIVALENT,
  type GcsimRunner,
} from './gcsim-runner';

/** The part of `Worker` this uses, so a spec can supply a fake — jsdom has no Worker. */
export interface WorkerLike {
  postMessage(message: GcsimJob): void;
  terminate(): void;
  onmessage: ((event: MessageEvent<GcsimReply>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
}

export interface WorkerRunnerOptions {
  /** Builds a new worker. Called on the first job and after every kill. */
  createWorker: () => WorkerLike;
  /** Absolute URL of the served `gcsim/` directory. */
  base: string;
  /** Overrides `deadlineMs`, for specs and the verify script's planted hang. */
  deadline?: (iterations: number) => number;
}

type Payload =
  | { kind: 'validate'; config: string }
  | { kind: 'sample'; config: string; seed: string }
  | { kind: 'run'; config: string; iterations: number };

export class WorkerGcsimRunner implements GcsimRunner {
  private worker: WorkerLike | null = null;
  private nextId = 1;
  /** The tail of the queue. Each job starts when the one before it has settled. */
  private tail: Promise<unknown> = Promise.resolve();
  private readonly deadline: (iterations: number) => number;
  // Not a parameter property: `verify-gcsim-runner.mjs` imports this with Node's type
  // stripping, which refuses them.
  private readonly options: WorkerRunnerOptions;

  constructor(options: WorkerRunnerOptions) {
    this.options = options;
    this.deadline = options.deadline ?? deadlineMs;
  }

  validate(config: string): Promise<string | null> {
    return this.enqueue({ kind: 'validate', config }, 0, (reply) =>
      reply.type === 'validated' ? { value: reply.error } : undefined,
    );
  }

  sample(config: string, seed: string): Promise<string> {
    return this.enqueue({ kind: 'sample', config, seed }, SAMPLE_ITERATION_EQUIVALENT, (reply) =>
      reply.type === 'sampled' ? { value: reply.log } : undefined,
    );
  }

  run(
    config: string,
    iterations: number,
    onProgress?: (done: number, total: number) => void,
  ): Promise<GcsimRun> {
    // Checked here as well as in the worker, so a bad count is refused without a round trip
    // and with the deadline below never computed from it.
    if (!Number.isInteger(iterations) || iterations < 1) {
      return Promise.reject(new Error(`iterations must be a positive integer, got ${iterations}`));
    }
    return this.enqueue({ kind: 'run', config, iterations }, iterations, (reply) => {
      if (reply.type === 'progress') {
        onProgress?.(reply.done, reply.total);
        return undefined;
      }
      return reply.type === 'ran' ? { value: reply.run } : undefined;
    });
  }

  /** Kill the worker now, if there is one. The next job starts a fresh one. */
  dispose(): void {
    this.worker?.terminate();
    this.worker = null;
  }

  private enqueue<T>(
    payload: Payload,
    iterations: number,
    read: (reply: GcsimReply) => { value: T } | undefined,
  ): Promise<T> {
    const job = this.tail.then(() => this.execute(payload, iterations, read));
    // The queue survives a failed job: the next one waits for this to settle, not to succeed.
    this.tail = job.catch(() => undefined);
    return job;
  }

  private execute<T>(
    payload: Payload,
    iterations: number,
    read: (reply: GcsimReply) => { value: T } | undefined,
  ): Promise<T> {
    const worker = (this.worker ??= this.options.createWorker());
    const id = this.nextId++;
    const ms = this.deadline(iterations);

    return new Promise<T>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const settle = () => {
        if (timer !== null) clearTimeout(timer);
        worker.onmessage = null;
        worker.onerror = null;
      };
      const kill = (error: Error) => {
        settle();
        worker.terminate();
        if (this.worker === worker) this.worker = null;
        reject(error);
      };

      worker.onmessage = (event) => {
        const reply = event.data;
        if (reply.id !== id) return;
        if (reply.type === 'started') {
          timer = setTimeout(() => kill(new GcsimTimeoutError(Math.round(ms / 1000))), ms);
          return;
        }
        if (reply.type === 'failed') {
          // gcsim refused or failed — a fact about the config. The worker is still healthy
          // and keeps its loaded module for the next job.
          settle();
          reject(new Error(reply.message));
          return;
        }
        const done = read(reply);
        if (done !== undefined) {
          settle();
          resolve(done.value);
        }
      };
      // An uncaught error or a failed module load inside the worker. Its state is unknown, so
      // it is discarded rather than reused.
      worker.onerror = (event) => {
        event.preventDefault?.();
        kill(new Error(`the gcsim worker failed: ${event.message || 'unknown error'}`));
      };

      worker.postMessage({ id, base: this.options.base, ...payload } as GcsimJob);
    });
  }
}

let shared: WorkerGcsimRunner | null = null;

/**
 * The page's one runner, created on first use.
 *
 * `new Worker(new URL('./gcsim.worker', import.meta.url), { type: 'module' })` is the exact
 * form Angular's esbuild builder recognises and bundles as a separate chunk; it must stay a
 * literal here for that to work.
 */
export function gcsimRunner(): Promise<GcsimRunner> {
  shared ??= new WorkerGcsimRunner({
    createWorker: () =>
      new Worker(new URL('./gcsim.worker', import.meta.url), {
        type: 'module',
      }) as unknown as WorkerLike,
    base: new URL('gcsim/', document.baseURI).href,
  });
  return Promise.resolve(shared);
}
