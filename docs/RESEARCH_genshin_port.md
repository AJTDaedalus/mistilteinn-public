# RESEARCH: Porting fairy to Genshin Impact ("mistilteinn.aetherus.dev")

**Date:** 2026-08-19 · **Tier:** Brain (Fable) · **Status:** Feasibility assessment — precedes any BRIEF
**References:** [Genshin Optimizer](https://github.com/frzyc/genshin-optimizer) (frzyc, TypeScript, MIT), [gcsim](https://github.com/genshinsim/gcsim) (Go, MIT, Monte Carlo combat sim)

## Verdict

**Feasible, and the architecture is well-positioned for it — but this is a domain-layer rewrite plus a 2× content effort, not a reskin.** Roughly half the engine transfers with modest rework. The two genuinely hard problems are (1) Genshin's elemental gauge/reaction system, which is strictly deeper than ZZZ anomaly and is the reason gcsim exists, and (2) the kit corpus at ~115–122 characters vs fairy's 58 curated kits. The strategic question is not "can we" but "what sim fidelity do we build vs. borrow."

MVP (Genshin-Optimizer-parity artifact optimizer with curated meta kits): **~2–3 months** at this project's demonstrated cadence. Full vision (stateful reaction sim + optimizer, the GO+gcsim hybrid neither incumbent is): **~6–9 months**, with the reaction engine as the risk center.

## Why fairy is a good starting point

Codebase survey (2026-08-19): ~37.4k lines app code, ~12.5k scripts, ~81k tests, 58 kit JSONs (1.6 MB modifiers + skill_overrides + validation ledgers), 227 MB Dimbreath ZZZ snapshot.

Two structural facts make the port cheaper than it looks:

1. **The formula layer is already game-namespaced.** `app/formula/` (builder, nodes, tags — game-agnostic DSL) has `app/formula/zzz/` as its only domain child. A `formula/genshin/` sibling is the intended extension shape.
2. **The validation harness is game-agnostic in architecture.** L0–L2/L4–L6/LR/LU check *kit JSON ↔ DB ↔ upstream data* consistency; none of the level logic cares that the game is ZZZ. Neither GO nor gcsim has an equivalent — their kit correctness rests on human review alone. This is mistilteinn's structural advantage, and the curator/auditor agent workflow (`/kit-curation`) transfers as a process wholesale.

## Domain mapping

| fairy (ZZZ) | mistilteinn (Genshin) | Port cost |
|---|---|---|
| Discs: 6 slots, main+substats, 2pc/4pc sets | Artifacts: 5 slots (flower/plume fixed mains), same substat-roll structure, 2pc/4pc | **Low** — optimizer combinatorics transfer nearly wholesale; slot constants shrink |
| ZZZ-Scanner import | GOOD format (Inventory Kamera etc.) — an established ecosystem standard | **Low**, and better tooling than ZZZ has |
| W-Engines: specialty-locked, phases | Weapons: type-locked (5 types), refinements | **Low** |
| Mindscapes / core passives / skills | Constellations / ascension passives / talents (level-indexed multiplier tables) | **Low–medium** |
| Standard damage chain (7 multipliers) | Base × (1+DMG%) × Crit × DEF area × RES area × amp multiplier — ZZZ's chain is a descendant of this | **Medium** — restructure, not rewrite; no stun area; DEF uses char/enemy level ratio + shred/ignore |
| Anomaly: per-element buildup → proc → disorder | Gauge theory: aura units (1A/2B/4C), 0.8 application tax, decay rates, coexisting auras (EC, frozen, burning), ICD sequences, reaction priority; amplifying / transformative / additive (aggravate/spread) reactions; EM curves | **High** — strictly deeper state machine than `anomaly_simulator.py` (4.4k lines, largest module); its replacement is *bigger* |
| Stun/daze | No equivalent (drop) | Negative cost |
| Decibels / EX energy (ER unmodeled — known gap) | Burst energy + particle economy (funneling, off-field 0.6×, ER as first-class build stat) | **High** — punting is worse in Genshin; GO sidesteps by making rotations user-declared |
| nanoka.cc + hakushin + Dimbreath ZenlessData | gi.hakush.in, Project Amber (ambr.top) API, Dimbreath AnimeGameData | **Medium** — importer rewrite; see data-source risk |

## Reuse map

**Transfers with light rework (~45–50% of engine):** optimizer_pipeline (1.8k), disc_optimizer (1.5k), rank_pipeline, job_runner + progress/cancel, repositories, API scaffolding, auth/users/teams/builds, buff_resolver + modifiers DSL, formula core, snapshot_builder pattern, attribution, disc_scorer skeleton, validation harness architecture, factory/test infrastructure, Docker/deploy stack, `/kit-curation` process.

**Rewrites:** `formula/zzz/` → `formula/genshin/`; damage_calculator chain; anomaly_simulator → reaction/gauge engine; enums + models domain layer; all importers + seed; all Dimbreath tooling, anchors, and the 227 MB snapshot; combo_step_resolver semantics (swap/rotation model differs — Genshin has hard swap cooldowns and off-field mechanics as the *core* team dynamic).

**Content (the long pole):** 58 kits → ~115–122 ([roster count](https://skycoach.gg/blog/genshin-impact/articles/all-characters-list), 2026), plus weapons (~200) and artifact sets (~60). Mitigations: Genshin reference data is far richer than ZZZ's (GO character sheets, gcsim per-character implementations, KQM Theorycrafting Library frame/ICD data, Amber/hakushin) — so per-kit *verification* is easier even though volume is 2×; and Genshin kits are immutable post-release (no balance patches), so curation is write-once. Ongoing load: ~10–12 new characters/year.

## Owner observation (2026-08-19): rotation definition is *easier* in Genshin

Genshin's gameplay differences cut in mistilteinn's favor on the input side. ZZZ's freeform combo
grammar is what forced fairy's worst curation machinery — sequential/variant hit modes (Pattern A/B
skill overrides), per-press vs whole-cycle buildup ambiguity, channeled-move timings absent from
Dimbreath (the `#channel` Task 12 blocker). Genshin's action grammar is coarse and cooldown-gated
(skill → burst → N normals → swap) with published, stable durations, so:

- The `combo_step_resolver` replacement is **simpler** than the module it replaces, and the
  Pattern A/B override class largely disappears from kit curation.
- **gcsim doubles as a frame-data corpus**, not just a crossval oracle: every implemented character
  carries measured hitmarks, animation lengths, and cancel frames as Go tables (KQM-sourced, MIT —
  harvestable with attribution). The "timing isn't in the datamine" problem is pre-solved for the
  whole roster. Their community action-list DB is likewise a corpus of validated rotations usable
  as per-archetype defaults.
- **The risk center does not move.** Rotation definition was never the hard part of Phase 3 —
  reaction *resolution* is (aura coexistence, ICD, particle economy). Net effect: trim Phase 3
  modestly (cleaner event-layer inputs), trim Phase 4 meaningfully (curation loses its worst
  ambiguity class), keep the gauge engine as the schedule-deciding item.

## The fidelity decision (the real strategic fork)

The reaction engine has three viable fidelity levels:

- **(a) GO-parity:** user declares reaction types/counts per rotation entry; engine applies multipliers statically. Weeks of work. But then mistilteinn is a GO clone with a worse kit corpus — no reason to exist.
- **(b) Event-level gauge sim** — extend the anomaly_simulator design: event timeline, gauge units with decay, ICD counters, reaction resolution on application. Not frame-accurate, but models the things that actually decide builds (aura uptime, reaction counts, EM vs ATK tradeoffs, ER requirements). **Months. This is the differentiator: GO optimizes but doesn't simulate; gcsim simulates but barely optimizes.**
- **(c) Frame accuracy:** that's cloning gcsim, hand-coded per character. Don't.

**Recommendation: (b), with gcsim as the crossval oracle** — filling exactly the role ZO plays for fairy, except gcsim is a much stronger oracle (Monte Carlo, community-validated, MIT). A deeper variant worth one BRIEF-stage spike: embedding gcsim itself (Go → WASM or sidecar service) as the sim engine and building only optimizer/DB/UI around it — cuts the hard problem to integration work at the cost of coupling to their action-list format and per-character impl coverage.

## Repo strategy

- **A. Fork:** mistilteinn as a sibling repo, domain layer rewritten. Simple, immediate, some drift-debt in the shared ~50%.
- **B. Shared core first:** extract formula DSL + optimizer + harness into a library; fairy and mistilteinn become domain packages. Right answer *if* both are maintained for years (and fits the ghost/fairy/youkai coherence concern), but front-loads a large refactor onto fairy before any Genshin work starts.
- **Recommendation: A now, B only when the shared code has proven it wants to converge** (or when a third game appears). Premature extraction of a core that has served exactly one game is how you get an abstraction shaped like ZZZ with Genshin bolted on.

## Rough effort phasing (Brain/Planner/Worker cadence)

| Phase | Scope | Estimate |
|---|---|---|
| 0 | Repo bootstrap, domain models/enums, importers (hakushin-GI/Amber), seed, migrations | 2–4 weeks |
| 1 | Damage chain (amp/transformative/additive, EM curves, DEF/RES areas) + crossval fixtures vs GO/gcsim | 2–3 weeks |
| 2 | Optimizer adaptation (5 slots, GOOD import), builds/teams/scorer | 1–2 weeks |
| 3 | Reaction/gauge sim (fidelity b) + ER/particle model | 2–4 months ← **risk center** |
| 4 | Kit corpus: 20–30 meta characters for MVP, then rolling | 4–6 weeks MVP; full roster over months, ongoing |

## Risks

1. **Reaction-engine underestimation** — gauge coexistence + ICD is where every amateur Genshin calculator dies. Mitigate: crossval against gcsim from day one; ship amplifying-only first (covers vape/melt meta), add transformative/additive incrementally.
2. **Data-source takedowns** — HoYo has historically DMCA'd Genshin data repos (Dimbreath's GenshinData moved hosts repeatedly); enforcement on GI has been harsher than on ZZZ. Amber/hakushin are the resilient layer; keep committed snapshots (the L6/LU pattern) so the gate never depends on a live fetch.
3. **Incumbent strength** — GO and gcsim are mature, free, and community-maintained; ZO's weakness was fairy's opening, and Genshin offers no such gap. The differentiator must be the optimizer-over-simulator combination plus harness-backed kit correctness. If this is primarily a personal tool, this risk is irrelevant; if it's meant to compete publicly, it's the first question.
4. **Two patch treadmills** — fairy + mistilteinn both live means double curation cadence. The agent-driven `/kit-curation` pipeline is what makes this plausible for one maintainer at all.

## Open questions for a future BRIEF

1. Sim fidelity ruling: build (b), or spike gcsim-as-engine first?
2. Fork (A) confirmed over shared-core (B)?
3. MVP roster cut — which 20–30 characters?
4. Is public competitiveness a goal, or is this a personal/portfolio tool? (Changes risk #3 from blocking to irrelevant.)
5. Frontend: still deferred, or does mistilteinn start frontend-first since the backend patterns are proven?

---
*Owner ruling 2026-08-19: graduated to `docs/BRIEF_mistilteinn.md`. Both docs are intentionally
untracked in fairy (not fairy work; excluded via `.git/info/exclude`) and move to the mistilteinn
repo as founding docs when it is created.*
