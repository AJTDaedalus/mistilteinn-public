---
name: kit-curation
description: >
  Runbook for adding or re-validating agent kit modifiers (the skill
  description → functionality pipeline). Use whenever a new ZZZ patch ships
  agents/W-Engines, when a kit-math bug is reported, or when re-auditing
  existing kits. Orchestrates kit-curator and kit-auditor subagents and the
  validate_kits harness. Invoke as /kit-curation <agent names | "patch X.Y">.
---

# Kit Curation Workflow

Turns in-game skill descriptions into `backend/app/data/modifiers/` JSONs with
machine-verified values. Trust lives in the harness and the drafter/auditor
split, **not** in any model's self-assessment — so every step here is
executable by Opus (or Sonnet where marked) if Fable is unavailable.

**Scope also covers `backend/app/data/moves/agents/` and
`backend/app/data/skill_overrides/`** for any agent this run touches (docs/
DESIGN_move_key_resolution.md, issue #77). These are separate JSON types
(anomaly buildup/timing and hit-mode annotation, not stat modifiers —
`docs/MODIFIER_AUTHORING.md` §3/§4) but the same curator/auditor discipline
applies, because neither has a validation harness of its own beyond
`validate_kits` L4 — see step 3a below and the per-agent-scoping trap it
exists to catch.

## Model tiers

| Step | Tier | Model | Fallback |
|---|---|---|---|
| Orchestrate this skill | Planner | Opus | Sonnet (procedure is mechanical) |
| Draft kit JSON | Worker | Sonnet (kit-curator agent) | — |
| Independent audit | Planner | Opus (kit-auditor agent) | Fable optional, never required |
| Unrepresentable-mechanic schema decisions | Brain | Fable | **Opus, using the escalation protocol below** |

## Preflight (blockers — stop if any fail)

1. `git branch --show-current` is a `feat/` or `fix/` branch (never dev/main).
2. DB is seeded and contains the new agents' descriptions:
   `docker compose exec -T db psql -U fairy -c "select name from agents"` —
   if a new agent is missing, run the seed importer first; kit curation
   without DB descriptions cannot be L1-validated.
3. ZO reference exists at `/tmp/genshin-optimizer/libs/zzz/` — else:
   `git clone --depth 1 --filter=blob:none --sparse
   https://github.com/frzyc/genshin-optimizer /tmp/genshin-optimizer &&
   git -C /tmp/genshin-optimizer sparse-checkout set libs/zzz`.
   Record the ZO commit hash; it goes in each kit JSON's `notes`.
4. Harness exists: `python -m scripts.validate_kits --help`. As of
   `docs/TASKS_kit_validation.md` Tasks 8–12 (L0–L3 + CI lane), it does. If a
   future `dev` sync ever regresses this, treat it as a hard blocker and fix
   the harness (those tasks) before curating — do not hand-verify instead.

## Procedure

1. **Scope.** For a patch run, do not hand-list targets — enumerate them:
   `python -m scripts.seed_db --skip-icons` (re-seed; the icon traceback is not a
   seed failure, #115), then `python -m scripts.validate_kits --roster`. Its LR
   report lists every DB agent / W-Engine / disc set with no kit JSON, ranked —
   signature engines of already-curated agents first (per
   `app/data/validation/signature_map.json`). Cross-check against nanoka's
   `manifest.json` `new` key (per-version new character/weapon/equipment ids) that
   the reseed picked up everything. For named-kit runs, list them as before. One
   curator subagent per kit, parallel, each writing only its own JSON. A gap that
   is deliberately not being curated needs a `coverage_ledger.json` entry — the
   curator records it (`authorized_by: null`), only the owner authorizes it.
   Then run `python -m scripts.dimbreath.build_unseeded_rows --check` in the same
   DB-backed pass (#180). LU proves the *committed* snapshot against the ledger and
   is offline, so it cannot see a re-seed that added agents — and a new agent's
   unseeded rows are invisible to every other level too, which is the gap #180
   exists to close. Drift means re-sweep (drop `--check`) and triage whatever
   appeared: a new row is an `unseeded_row_ledger.json` entry, recorded by the
   curator with `authorized_by: null`, never authorized by one.
2. **Draft.** Spawn `kit-curator` per kit. Collect reports from
   `docs/LOG_kit_curation.md`.
3. **Gate 1 — harness.** `python -m scripts.validate_kits` (there is no
   per-kit or changed-only filter yet — it runs L0–L2 over every curated
   JSON; grep the output for your kit's `source_name`). L1 (every value
   matches a number in the kit's DB description text), L2 (every ZO
   citation resolves to a real symbol with a matching value), L3 (every stat
   key has a frontend stat-meta entry — separate check, `npm test` in
   `frontend/`). Loop failures back to the owning curator (max 2 rounds,
   then escalate to you/Planner).
4. **Gate 1a — move keys, if this agent has (or needs) a `moves/agents/` or
   `skill_overrides/` file.** `python -m scripts.validate_kits --level l4`
   (needs a seeded DB — skips cleanly without one, so run it against a real
   Postgres, not just the isolated test DB). L4 is **per-agent scoped**: a
   move-name key must resolve to an attack **owned by this agent specifically**,
   not merely to *some* real attack somewhere in the DB. This is the trap
   issue #77 itself fell into while writing its own remediation table — a
   curator (human or model) matching a move name globally instead of
   per-agent will confidently rename a dead key to a real move that belongs
   to a *different* agent, which resolves clean at a glance and is wrong.
   Before writing any `moves/agents/<name>.json` key, confirm the candidate
   `Attack.name` via a query scoped to `agent_id = <this agent's id>`, never
   a bare `WHERE name = '...'` across the whole table. `docs/
   MODIFIER_AUTHORING.md` §3/§4 has the full field reference and failure
   modes for both directories.

   **Gate 1a and 1b are the ONLY place L4/L5 run.** They are not in CI and are
   not coming back: `attacks.param_name` (which L5 reads) is populated by the
   nanoka importer alone, so no offline seed produces it, and putting nanoka.cc
   inside a manually-confirmed merge gate would make the gate flaky — which
   trains reviewers to wave it through. CI proves L0–L2 and LC; you prove L4 and
   L5. See `CLAUDE.md`'s kit gate paragraph and `docs/DECISIONS.md`
   (2026-07-30, issue #114).

   **A skipped level BLOCKS. It is never a pass.** `L4 skipped: DB not
   reachable`, `L4 skipped: DB has no agents`, `L5 skipped: attacks.param_name
   is NULL on every sequential row` all mean *could not check*, which is not
   *checked and clean* — the `ex_energy_cost` lesson, and the exact failure L5
   exists to prevent. The all-NULL case is the normal state of a dev box that
   pulled a migration without re-seeding, so it will happen to you: re-seed
   (`python -m scripts.seed_db --skip-icons`) and re-run, or state plainly in
   your report that L4/L5 were **not proven**. Never fold a skip into a green
   summary.

   **Add `--require-db` so the harness enforces that instead of you noticing
   it.** `python -m scripts.validate_kits --gate --require-db` exits non-zero
   when L4 or L5 could not check, names which, and prints the re-seed command.
   Without the flag an unseeded DB exits 0 and reads exactly like a clean run —
   which is the whole failure mode this rule is guarding against. Never drop
   the flag to make a run pass; the flag failing *is* the finding.

4b. **Gate 1b — sequential plausibility, if this run touched `hit_mode:
   sequential` rows or `skill_overrides/`.** `python -m scripts.validate_kits
   --level l5` (same seeded-DB requirement as Gate 1a). L5 reads each
   sequential row's `param_name` and flags six shapes that do not look like a
   real press chain — rider rows, duplicate param names, variant labels, a
   leading qualifier over a shared label tail, and identical rows.

   **L5 flags; it never classifies, and no finding may be auto-fixed.** That is
   the harness's own contract, and it is why this level belongs to you rather
   than to CI: deciding whether a flagged row is a rider, a context variant or
   a genuine press needs the skill description text and nanoka's input
   notation, which no rule can read. Resolve each flag by reading the source,
   then either re-classify the move (`docs/MODIFIER_AUTHORING.md` §4's decision
   tree for `atomic` / `sequential` / `variant`) or record a waiver with its
   reasoning. A tool that decided this for itself is the generator the
   sequential/variant branch retired — do not rebuild it.

   Because L4/L5 no longer run in CI, the D-KV7 stale-waiver guarantee for
   their codes lives here: report the waiver counts your run produced, not just
   pass/fail, so a waiver that has quietly stopped firing is visible.

5. **Gate 2 — audit.** Spawn `kit-auditor` on every drafted kit. Auditor
   re-derives independently and records its verdict in
   `docs/LOG_kit_curation.md`. **The confidence ladder is not enforced by
   the harness yet** (Task 18, Phase E, unshipped) — there is no
   `--set-audited` or equivalent CLI promotion path. Until Task 18 lands,
   you (the orchestrating session) are the one who bumps
   `"confidence": "audited"` in the JSON, and only after reading a clean
   audit verdict with zero open findings — the auditor itself does not have
   Edit/Write tools and does not touch the JSON.
   `phantom`/`citation_invalid` findings go back to the curator; `missing`
   and `wrong_structure` findings usually mean the curator misread the ZO
   sheet — fix and re-audit. If this run touched `moves/agents/` or
   `skill_overrides/`, the auditor also re-derives every move key
   independently against the DB, per-agent scoped (see kit-auditor.md) —
   same trap as Gate 1a, checked a second time by a different reasoning
   pass.
6. **Escalations.** Collect all `unrepresentable` entries. These are schema
   questions (Brain). If Fable is unavailable, resolve them in an Opus
   session with this discipline: write the mechanic, ≥2 candidate schema
   representations, and the downstream calc/UI implications into
   `docs/DECISIONS.md` **before** choosing; prefer the representation that
   fails loudly (loader error) over one that silently under-buffs.
7. **Verify in-app** (`/verify`): pick one drafted kit, open its build in the
   UI, confirm buff chips show correct labels/values/stacks (issues #62/#63
   were user-visible here).
8. **PR.** Conventional commit per kit (`feat(kits): curate <agent>`), plus
   the LOG update. Cite ZO commit hash in the PR body.

## Standing rules (encode failures we've already had)

- `confidence: draft` is set by the curator. `confidence: audited` should
  only ever follow a clean auditor verdict (zero open findings) — but as of
  today the auditor cannot write it itself (no Edit/Write tools, and no
  harness promotion path — Task 18 is unshipped), so *you*, reading the
  audit verdict, make that edit. `confidence: verified` does not exist yet
  in practice: no harness stamps it, so no kit should carry it — a
  hand-set `verified` is a review-reject regardless of which tier set it.
  Once Task 18 ships the loader-enforced ladder, this rule reverts to the
  original design (`verified` written only by the harness) — check
  `docs/TASKS_kit_validation.md` Task 18 status before relying on this note.
- Flattening an unrepresentable mechanic into the nearest stat is the worst
  outcome — worse than shipping nothing, because it looks done (Astra core,
  Lucy `value: 0`). Ship the escalation instead.
- Newest agents may have no ZO sheet for weeks. `no_reference` ≠ `pass`:
  such kits cap at `confidence: draft` and get re-run when ZO catches up
  (check on next patch's curation run).
- **A kit you leave at `draft` needs a ledger entry, not just a `notes`
  paragraph.** Add it to `draft_blockers` in
  `backend/app/data/validation/known_issues.json`, classed
  `curation_pending` (decided, unauthored — names an `owner_task`),
  `schema_gap`, `approximation_ceiling`, or `upstream_blocked` (the last
  three name a `retire_when`). `validate_kits` fails the run on a draft kit
  with no entry, and on an entry whose kit is no longer draft. Issue #88 is
  what happens without this: four kits sat at `draft` for four unrelated
  reasons, each recorded only inside its own file, and every report said the
  corpus was clean.
- **`audited` means "no known defects", and the harness now enforces it.** A
  kit carrying an open `known_issues.json` waiver may not sit above `draft`
  (D-KV22) — `validate_kits` reports `waived_finding_above_draft`. So a
  clean auditor verdict is necessary but not sufficient: check the kit has
  no open waiver before bumping it.
- Six-week cadence: run this skill once per patch, plus a full
  `python -m scripts.validate_kits` re-run (no flags — that's already every
  kit, every implemented level) to catch drift (balance patches, description
  re-imports).
- Three mechanic shapes are **settled policy, not escalations**
  (D-KV17–D-KV19, `docs/MODIFIER_AUTHORING.md` "Escalation vs approximation")
  — don't route these to step 6: hit-subset-grain gates (≤2% fixture-rotation
  over-credit, `"approximation": "hit-subset"` in `notes`), Ultimate-innate
  team riders (authored directly, gated on `ULTIMATE_USED`/`AFTER_ULTIMATE`),
  and Energy/ER grants (stay omitted with the standard note). Held kits from
  before C5–C9 landed should be re-checked against the *current* schema, not
  auto-promoted — some of their old escalations are now representable
  (Gate-2 amendment, see `kit-auditor.md`).
