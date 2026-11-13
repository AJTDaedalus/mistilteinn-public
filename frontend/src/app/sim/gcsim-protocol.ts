/**
 * The messages between the page and `gcsim.worker.ts`. Shared so the two ends cannot disagree
 * about a field name — a typo on one side is a job that never answers, which here would look
 * exactly like the hang the worker exists to catch.
 */

import type { GcsimRun } from './gcsim';

export type GcsimJob =
  | { id: number; kind: 'validate'; base: string; config: string }
  | { id: number; kind: 'sample'; base: string; config: string; seed: string }
  | { id: number; kind: 'run'; base: string; config: string; iterations: number };

export type GcsimReply =
  /** The module is loaded and the job has started — the deadline runs from here. */
  | { id: number; type: 'started' }
  | { id: number; type: 'progress'; done: number; total: number }
  | { id: number; type: 'validated'; error: string | null }
  | { id: number; type: 'sampled'; log: string }
  | { id: number; type: 'ran'; run: GcsimRun }
  | { id: number; type: 'failed'; message: string };
