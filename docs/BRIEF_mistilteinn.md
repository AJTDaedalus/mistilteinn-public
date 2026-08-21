# BRIEF: mistilteinn — Genshin Impact optimizer (fairy port)

**Date:** 2026-08-19 · **Tier:** Brain (Fable) · **Status:** Direction set — hand to Planner
**Deploy target:** `mistilteinn.aetherus.dev` · **Repo:** new sibling repo `mistilteinn` (fork of fairy)
**Companion:** `docs/RESEARCH_genshin_port.md` (feasibility survey, reuse map, effort phasing — read first)
**Tracking:** both docs are intentionally untracked in fairy (not fairy work); they move to the mistilteinn repo when it exists and become its founding docs.

## Problem statement

Build a Genshin Impact build optimizer + rotation simulator as a web app, reusing the fairy
engine. The combination is the point: Genshin Optimizer optimizes static multiplier sheets but
does not simulate; gcsim simulates but barely optimizes. An optimizer that evaluates artifact
builds *through* a stateful reaction sim — with fairy's DB-backed kit-validation rigor behind
the kit corpus — is the niche neither incumbent occupies.

## Goals

1. **MVP (≈2–3 months):** GO-parity artifact optimizer — GOOD-format import, 5-slot
   combinatorics with top-K/Pareto/budget-K from fairy, damage chain with amplifying reactions,
   curated kits for an initial meta roster, deployed at mistilteinn.aetherus.dev.
2. **Full vision (≈6–9 months):** event-level reaction/gauge simulator (aura units, decay, ICD,
   coexisting auras, particle/ER economy) feeding the optimizer; transformative + additive
   reactions; rolling kit coverage toward the full ~120-character roster.
3. **Process parity:** validation harness (L0–LR equivalents) and the curator/auditor
   `/kit-curation` pipeline ported as the correctness gate from day one.

## Non-goals

- **Frame accuracy.** Event-level fidelity only; frame-accurate simulation is gcsim's territory
  and cloning it is explicitly rejected.
- **Reimplementing gcsim's scripting language.** Rotations are structured data (our combo model),
  not a DSL; gcsim action lists are a *source* we translate from, not a UI we expose.
- **Buildup/decay-style mechanics we don't need:** no stun/daze system exists in Genshin; drop it
  cleanly rather than generalizing it.
- **Multiplayer, abyss clear-time prediction, TCR-style theorycrafting publications.**

## Approach (selected at research stage, confirmed here)

- **Repo strategy A — fork now.** Copy fairy, rewrite the domain layer. Shared-core extraction
  (strategy B) is deferred until shared code proves it wants to converge or a third game appears;
  extracting a core that has served one game yields a ZZZ-shaped abstraction. *Rejected:* B-first
  (front-loads a large fairy refactor before any Genshin work); building on GO's TS libraries
  (abandons our backend, DB-as-truth, and harness).
- **Sim fidelity (b) — event-level gauge sim,** extending the anomaly_simulator architecture:
  event timeline, gauge units with decay, ICD counters, reaction resolution on application.
  Models what decides builds (aura uptime, reaction counts, EM-vs-ATK, ER requirements) without
  frame data. *Rejected:* (a) GO-parity-only (no reason to exist), (c) frame accuracy (see
  non-goals).
- **gcsim in three roles:** crossval oracle (the ZO role, but stronger — Monte Carlo, MIT,
  community-validated); frame-data corpus (per-character hitmarks/durations as Go tables,
  KQM-sourced — harvest with attribution); rotation corpus (community action-list DB → default
  rotations per team archetype).
- **Ship amplifying-only first.** Vape/melt covers a large meta slice with the *simplest*
  reaction math (multiplier on the hit, no aura bookkeeping beyond trigger availability);
  transformative/additive land with the gauge engine.
- **Optional Phase-0 spike (timeboxed):** embed gcsim itself (Go→WASM or sidecar) as the sim
  engine. If integration is clean, it collapses the hardest phase; if not, walk away with better
  crossval tooling. Do the spike before committing to building the gauge engine.

## Tool / stack decisions

| Concern | Decision |
|---|---|
| Stack | Unchanged from fairy: FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Alembic; Angular deferred; Docker Compose; Cloudflare Tunnel deploy |
| Game data (primary) | gi.hakush.in + Project Amber (ambr.top) API via importer adapters; DB is source of truth (fairy rule carries over) |
| Game data (raw) | Dimbreath AnimeGameData as fallback — **committed snapshots only** (L6/LU pattern); never a live-fetch gate. GI has real DMCA history |
| User artifact import | GOOD format (ecosystem standard; Inventory Kamera et al.) |
| Cross-reference | gcsim (primary oracle) + Genshin Optimizer character sheets (secondary) |
| Crossval | gcsim fixtures with **require-DB mode from day one** — fairy's "skipped level looks green" lesson is pre-paid here |

## Downstream robustness

- **Takedown resilience:** every gate reads committed snapshots; importer fetch is a manual
  regeneration step. If AnimeGameData vanishes, hakushin/Amber carry the roster.
- **Correctness under 2× content scale:** the harness + curator/auditor agents are the only way
  one maintainer runs two patch treadmills. Genshin helps: kits are immutable post-release
  (write-once curation) and the rotation grammar kills the Pattern A/B override class (see
  RESEARCH addendum).
- **Clean domain layer:** delete ZZZ concepts (stun area, anomaly enums, specialty semantics)
  rather than aliasing them — leaked ZZZ shapes in the Genshin domain model are the fork
  strategy's main long-term hazard.
- **Infra:** likely co-hosted on the existing Oracle Free ARM VM (24 GB / 4 OCPU) — two compose
  stacks + two Postgres instances should fit, but Planner must confirm before the deploy phase.

## Constraints handed to Planner

1. New repo bootstrap is Task 0 territory: fork, rename, strip ZZZ data corpus (227 MB Dimbreath
   snapshot does not come along), carry over CLAUDE.md conventions (branch policy, commit
   discipline, DESIGN branch-policy section, session cadence).
2. Phase order per RESEARCH: domain models/importers → damage chain + crossval → optimizer/GOOD
   → gauge sim → kit corpus rolling. gcsim-embed spike sits at the front of the gauge-sim phase.
3. Design the gcsim frame-data harvest as a snapshot-generating script (the
   `build_upstream_mv.py` pattern): manual fetch, committed artifact, offline gate.
4. Kit corpus MVP: propose a ~20–30 character cut selected by current Spiral Abyss usage stats,
   for owner approval.

## Open questions (owner, not Planner)

- **OQ-M1:** Public competitiveness vs personal tool? Decides how much the incumbent-strength
  risk matters and whether MVP polish (onboarding, docs, sharing) is in scope.
- **OQ-M2:** Approve the gcsim-embed spike (timebox: ~2–3 sessions) before gauge-engine work, or
  skip straight to building fidelity (b)?
- **OQ-M3:** Same VM or separate hosting for prod?

---
**Resolved at Brain tier. Hand to Planner (Opus): produce `DESIGN_mistilteinn.md` +
`TASKS_mistilteinn.md` in the new repo, starting from Task 0 (repo bootstrap) — after OQ-M1/M2
are answered by the owner.**
