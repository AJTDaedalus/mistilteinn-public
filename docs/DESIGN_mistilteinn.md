# DESIGN: mistilteinn — ZZZ strip-out and Genshin domain rebuild

**Date:** 2026-08-21 · **Tier:** Planner (Opus) · **Status:** Design set — hand to Worker at Task 0
**Upstream:** `docs/BRIEF_mistilteinn.md` (Brain), `docs/RESEARCH_genshin_port.md` (Brain)
**Scope of this document:** Phases 0–2 of the BRIEF's phase order (domain models/importers →
damage chain + crossval → optimizer/GOOD), plus the repo-identity work the BRIEF called
"Task 0 territory". Phases 3–4 (gauge sim, kit corpus) are sketched at chunk granularity only —
they get their own DESIGN docs when they come up.

---

## Branch policy

- **Feature branch:** `feat/genshin-domain` off `dev`. `dev` does not yet exist in this repo —
  creating it from `main` is **Task 0.1** and is the gate for everything else.
- **No direct commits to `dev` or `main`.** All work lands on `feat/genshin-domain` (or a
  sub-branch of it) and reaches `dev` only by PR. Verify `git branch --show-current` before
  every commit.
- **Sub-branches.** Chunks C and later are large enough to warrant their own branches off
  `feat/genshin-domain`, merged back into it rather than into `dev` directly:
  - `feat/genshin-models` (Chunk C)
  - `feat/nanoka-gi-importer` (Chunk D)
  - `feat/yuanshen-snapshots` (Chunk E)
  - `feat/genshin-damage` (Chunk F)
  - `feat/artifact-optimizer` (Chunk G)
- Chunks A and B (identity + demolition) land directly on `feat/genshin-domain`; they are
  mostly deletions and are not worth a sub-branch.
- **Task 0 of `docs/TASKS_mistilteinn.md` is the branch-setup gate.** No Worker task starts
  before it is done.

---

## 1. Amendments to the BRIEF

Four owner rulings and one measurement land after the BRIEF was written. They amend it; the
BRIEF is otherwise unchanged and still governs.

### A1 — nanoka.cc is the primary importer source, not hakushin/Amber

The BRIEF's tool table names `gi.hakush.in + Project Amber` as the primary game-data source,
because at Brain time nanoka's Genshin coverage was unverified. **It is verified now**
(probed 2026-08-21):

| Endpoint | Result |
|---|---|
| `https://static.nanoka.cc/manifest.json` | carries a `gi` key: `latest 7.0.51`, `live 7.0`, plus a `new` block per entity type |
| `https://static.nanoka.cc/gi/{ver}/character.json` | index, **150 entries** |
| `https://static.nanoka.cc/gi/{ver}/weapon.json` | index, **286 entries** |
| `https://static.nanoka.cc/gi/{ver}/artifact.json` | index, **65 sets** |
| `https://static.nanoka.cc/gi/{ver}/monster.json` | index, **585 entries** |
| `https://static.nanoka.cc/gi/{ver}/en/character/10000002.json` | full detail, 116 KB (Ayaka) |
| `https://static.nanoka.cc/gi/{ver}/en/weapon/11501.json` | full detail, 12 KB |
| `https://static.nanoka.cc/gi/{ver}/en/artifact/15025.json` | full detail, 4 KB |

This is the **same URL grammar** fairy's `nanoka_importer.py` already speaks — index at
`{base}/{game}/{ver}/{entity}.json`, detail at `{base}/{game}/{ver}/en/{entity}/{id}.json`.
The importer's *transport* layer (manifest pin, index fetch, detail fetch, stale-ID prune,
upsert) therefore transfers; only the *mapping* layer is rewritten. That is a materially
cheaper Chunk D than the BRIEF assumed.

**Ruling:** nanoka is primary. hakushin/Amber demote to fallback adapters, written only if a
field turns out to be missing from nanoka. Do not build them speculatively.

### A2 — GuraFoundation/YuanShenResources replaces Dimbreath AnimeGameData

Raw-datamine source is `https://gitlab.com/GuraFoundation/YuanShenResources`. Verified
2026-08-21: repo is reachable and its root tree is `ExcelBinOutput/`, `TextMap/`,
`BinOutput/`, `Readables/`, `DialogsText/`, `Subtitle/` — **structurally identical to the
AnimeGameData/ZenlessData layout** fairy's `scripts/dimbreath/` toolkit was built against
(pinned-SHA fetch, cached raw bytes, `base ⊕ overwrite` TextMap merge, column dictionaries,
anchor assertions).

**Ruling:** port the toolkit rather than rewrite it. Two real differences: the host is GitLab
(different raw-file URL and tree API), and the table names are Genshin's
(`AvatarExcelConfigData`, `WeaponExcelConfigData`, `ReliquaryExcelConfigData`,
`AvatarSkillExcelConfigData`, … — 100+ tables in the first page of `ExcelBinOutput/` alone).
The BRIEF's rule stands unchanged and is load-bearing given GI's DMCA history: **committed
snapshots only, never a live-fetch gate.**

### A3 — One Postgres server, two databases

Owner ruling 2026-08-21. mistilteinn does **not** run its own Postgres container. It connects
to the existing fairy Postgres instance on `:5432` and owns a separate **database**
(`mistilteinn`, `mistilteinn_test`) alongside `fairy` / `fairy_test`.

```
postgres:16 container (host port 5432, owned by the fairy compose stack)
├── fairy             ← ZZZ, its own alembic_version
├── fairy_test
├── mistilteinn       ← Genshin, its own alembic_version
└── mistilteinn_test
```

Consequences, all handled in Chunk A:
- mistilteinn's `docker-compose.yml` **drops the `db` service** and its bind mount; `backend`
  and `frontend` join the fairy stack's network (external network reference) or reach the host
  DB directly.
- `depends_on: db` disappears; startup ordering is no longer ours to enforce, so the backend
  needs a connect-retry on boot.
- Host port collisions with fairy remain on **8000** (backend) and **4200** (frontend). Remap
  to **8001 / 4201**. `CORS_ORIGINS` and the frontend's API base follow.
- Separate `alembic_version` tables mean the two migration histories never interact. This is
  the reason to prefer separate databases over a shared-database `genshin` schema.
- One shared backup/restore unit and one connection-limit pool is the accepted cost.

### A4 — Rebrand: Fairy → Mitya

fairy's visual identity is derived from the ZZZ NPC "Fairy" (`--cobalt`/`--cyan` halo palette
in `frontend/src/styles/_tokens.scss`, sampled from `references/NPC_Fairy.webp`;
`public/fairy-emblem.webp`; wordmark "Fairy"; sub-wordmark "ZZZ Optimizer"). mistilteinn's
identity is themed on the Genshin character **Mitya**.

Owner ruling 2026-08-21: **identifiers now, visuals later.** Chunk A renames every package and
project identifier and swaps the wordmark/title/favicon to a neutral mistilteinn placeholder.
The Mitya palette, emblem, and typography are a dedicated task in the deferred frontend phase
(Chunk J), and require the owner to supply reference art the way `references/NPC_Fairy.webp`
served fairy — **do not invent a palette from a description of the character.**

### A5 — Demolition strategy: scorched earth

Owner ruling 2026-08-21. Chunk B deletes every ZZZ-bound module in one pass rather than
strangling them behind adapters. The repo is deliberately non-bootable-as-a-game-app for the
span of Chunks B→C, and the test suite shrinks to the infrastructure core before it grows back.

Rationale: the BRIEF names leaked ZZZ shapes in the Genshin domain model as the fork
strategy's main long-term hazard, and a coexistence layer is precisely that leak with a
deadline attached. The safety net is that every deleted file still exists in `/root/fairy` and
in the fairy repo at `76909c4` — deletion here is not destruction.

**Non-negotiable counterweight:** the *infrastructure* core (auth, users, sessions, teams,
optimization jobs, repository base, middleware, formula core, pando) stays alive and its tests
stay green through the whole demolition. "Scorched earth" applies to the game layer only.
Chunk B ends with a green (if small) suite, not a red one.

---

## 2. Inventory — what is actually here

Measured 2026-08-21 at `6e691e7`. `backend/build/` excluded (stale shadow copy; see CLAUDE.md).

### 2.1 Backend by subsystem

| Subsystem | Files | Lines | Disposition |
|---|---:|---:|---|
| `app/services/` | 38 | 21,328 | mostly **DELETE**, ~4k rewritten |
| `app/api/v1/` | 17 | 3,749 | ~40% keep (auth/health/jobs), rest **DELETE** |
| `app/data/` | 13 | 4,112 | **DELETE** mapping layers, keep importer base + transport |
| `app/schemas/` | 14 | 2,890 | ~15% keep |
| `app/formula/` | 11 | 2,161 | core (498) **KEEP**, `zzz/` (1,455) **DELETE** |
| `app/repositories/` | 12 | 1,183 | ~40% keep |
| `app/models/` | 12 | 1,194 | ~25% keep |
| `app/pando/` | 3 | 403 | **KEEP — see 2.4** |
| `app/middleware/` | 4 | 139 | **KEEP** |
| top-level (`main`, `config`, `database`, `dependencies`) | 5 | 359 | **KEEP**, edited |
| `alembic/versions/` | 39 | — | **DELETE**, replaced by one new initial migration |
| `scripts/` | 30 | ~12k | ~5 keep, ~13 port, rest **DELETE** |
| `tests/unit` | 234 | 58,370 | ~90% **DELETE** |
| `tests/integration` | 65 | 23,503 | ~70% **DELETE** |
| `tests/perf` | 2 | 587 | port |
| `frontend/src` | — | 36,694 | frozen until Chunk J; identifiers only in Chunk A |

Rough shape of the job: **~55k lines of backend app+script code and ~82k lines of tests to
triage**, of which roughly 45–50% of the engine survives per the RESEARCH reuse map.

### 2.2 The ten largest services, classified

| Module | Lines | Disposition |
|---|---:|---|
| `anomaly_simulator.py` | 4,471 | **DELETE.** Its replacement (gauge/reaction engine) is a bigger module written from scratch in Phase 3. Do not port line-by-line — the state machine is different in kind. |
| `optimizer_pipeline.py` | 1,826 | **PORT.** Slot count and stat vocabulary change; the top-K / Pareto / budget-K machinery does not. |
| `snapshot_builder.py` | 1,627 | **REWRITE against a ported skeleton.** 425 ZZZ-term hits — the densest per-line coupling in the codebase. |
| `disc_optimizer.py` | 1,525 | **PORT → `artifact_optimizer.py`.** 6 slots → 5; two of the five have fixed main stats, which *shrinks* the search space. |
| `damage_calculator.py` | 1,202 | **REWRITE.** The chain restructures (no stun area; DEF area becomes a char/enemy level ratio; amp multiplier is new). |
| `damage_dag_service.py` | 984 | **PORT.** DAG assembly is game-agnostic; the sheets it assembles are not. |
| `rank_pipeline.py` | 743 | **PORT.** |
| `combo_step_resolver.py` | 720 | **REWRITE, smaller.** Per the RESEARCH addendum, Genshin's cooldown-gated grammar is simpler than ZZZ's freeform combo model. |
| `build_damage_service.py` | 707 | **PORT.** |
| `modifiers.py` + `buff_resolver.py` | 1,168 | **PORT.** The modifier DSL is the reusable heart of the kit corpus; its scope vocabulary (`attack_scope`) is retargeted, not replaced. |

### 2.3 Confirmed game-agnostic (zero ZZZ-term hits, keep untouched)

`app/services/password.py`, `app/pando/calculator.py`, `app/pando/translator.py`,
`app/formula/{__init__,builder,tags}.py`, `app/repositories/{base,optimization_job,session,user}.py`.

### 2.4 The `app/pando/` finding — free ground

`app/pando/` is a Python port of **frzyc/genshin-optimizer's `libs/pando/engine`** — the
symbolic-DAG calculator from *the Genshin optimizer we are being compared to*. It carries no
ZZZ vocabulary at all. It arrived in fairy as a generic engine and is, in mistilteinn, a
component returning to its native game.

Practical consequence: the `formula/` + `pando/` pair (901 lines, all keepers) is the least
risky part of the whole port, and Chunk F should build `formula/genshin/` to feed it rather
than inventing a parallel evaluation path.

### 2.5 Domain-model deltas (ZZZ table → Genshin table)

| fairy table | mistilteinn table | Notes |
|---|---|---|
| `agents` | `characters` | drop `specialty`, `faction`, `base_impact`, `base_anomaly_mastery`, `base_anomaly_proficiency`, `ex_energy_cost`; add `weapon_type`, `ascension_stat_type`, `burst_energy_cost`, `region` |
| `agent_skills` | `talents` | ZZZ's 5 skill keys → Genshin's normal/charged/plunge + skill + burst, level-indexed 1–15 |
| `attacks` | `talent_scalings` | drop `stun_base`/`stun_growth`/`anomaly_buildup`; add per-level multiplier tables rather than base+growth (Genshin publishes explicit tables, not linear growth) |
| `core_skills` | `ascension_passives` | 1st/4th ascension + utility passive |
| `mindscapes` | `constellations` | C1–C6, same 1:N shape |
| `agent_resource_costs` | — | drop (ZZZ EX-energy ledger) |
| `w_engines` | `weapons` | `specialty`-locked → `weapon_type`-locked; phases → refinements R1–R5 |
| `disc_sets` | `artifact_sets` | nanoka `artifact.json` gives `need: [2,4]` and per-rank affix rows directly |
| `discs` | `artifacts` | 6 slots → 5; flower/plume have fixed main stats; substat roll structure is the same shape |
| `enemy_profiles` | `enemy_profiles` | keep the table, replace the columns: drop daze/anomaly fields, add per-element RES and level |
| `builds`, `teams`, `users`, `sessions`, `buff_presets`, `optimization_jobs` | unchanged names | column edits only (slot counts, FK retargets) |

### 2.6 Enum vocabulary, grounded in the live nanoka index

Read off the actual `character.json` / `weapon.json` payloads, **not** from memory:

- **Element** (from `character.json`): `Anemo, Cryo, Dendro, Electro, Geo, Hydro, Pyro` — plus a
  literal `"None"` that must be handled, not mapped (unaligned characters). Physical is *not* a
  vision and must be modelled as a damage type, not an element — a real trap for a ZZZ-shaped
  `Element` enum where Physical was a peer of the rest.
- **WeaponType** (from `character.json` / `weapon.json`): `WEAPON_SWORD_ONE_HAND`,
  `WEAPON_CLAYMORE`, `WEAPON_POLE`, `WEAPON_BOW`, `WEAPON_CATALYST`, **`WEAPON_CROSSBOW`**.
  The BRIEF says "5 types"; the live index says **six**. Crossbow is real in 7.x and the enum
  must carry it.
- **Rarity** (from `character.json`): `QUALITY_ORANGE` (5★), `QUALITY_PURPLE` (4★),
  `QUALITY_ORANGE_SP` (Aloy-class special). Weapons instead expose an integer `rank` 1–5.
  Two different rarity encodings in one source — normalize at the importer boundary.
- **Stat keys**: `FIGHT_PROP_*` strings (`FIGHT_PROP_GRASS_ADD_HURT`, `FIGHT_PROP_NONE`, …).
  These are the artifact/weapon substat vocabulary and become the `StatType` mapping table.
  Note `GRASS` = Dendro internally; the internal element names are *not* the display names.

---

## 3. Chunk plan

Dependencies are strict unless marked parallel-safe.

```
A. Identity & topology ─┬─> B. Demolition ─> C. Domain models ─┬─> D. nanoka GI importer ─┐
                        │                                      └─> E. YuanShen snapshots ─┤
                        └──────────────────────────────────────────────────────────────────┤
                                                          F. Stats + damage chain <────────┘
                                                                     │
                                            ┌────────────────────────┴────────┐
                                            G. Artifact optimizer + GOOD      H. Kit corpus + harness
                                                                              │
                                                                     I. Rotation model
                                                                              │
                                                                     (Phase 3: gauge sim)
                                                                     J. Frontend + Mitya visuals
                                                                     K. Deploy
```

### Chunk A — Identity, topology, and CI (≈1 session)

Make the repo *be* mistilteinn before changing what it does. Everything here is mechanical and
reviewable; none of it touches game logic.

- Create `dev`; branch `feat/genshin-domain`.
- Rename `fairy` → `mistilteinn` in `backend/pyproject.toml`, `frontend/package.json`,
  `frontend/angular.json`, `frontend/eslint.config.js`, `backend/alembic.ini`, and the
  docstrings/comments that name the project. **Not a blind `sed`** — `frontend/openapi.json` is
  generated (regenerate it), and `security/zap/zap-baseline-prod.html` (105 hits) is a stale
  scan artifact to delete rather than edit.
- Repoint at the shared Postgres per A3: drop the `db` service, remap host ports 8001/4201, add
  boot-time connect retry, update `.env.example`, `docker-compose.prod.yml`, `CORS_ORIGINS`.
- Wordmark/title/favicon → mistilteinn placeholder (`frontend/src/index.html`,
  `frontend/src/app/app.html`); sub-wordmark "ZZZ Optimizer" → "Genshin Optimizer".
  Delete `public/fairy-emblem.webp`. Leave `_tokens.scss` alone — the Fairy palette stays until
  Chunk J supplies a Mitya-derived one, and a half-rebrand is worse than an honest old one.
- CI: `.github/workflows/test.yml` still dispatches `validate_kits.py` at levels that reference
  deleted data. Reduce it to lint + the surviving suite, with a `TODO(chunk-H)` naming the
  levels to restore. **Do not delete the job** — a disabled gate that is invisible becomes a
  permanent gap (fairy's own green-by-absence lesson).
- `security/zap/` targets `mistilteinn.aetherus.dev`, which does not exist; gate the scan
  behind an explicit opt-in so it cannot report a false pass.

**Exit:** `docker compose up -d backend` boots against the shared Postgres on port 8001;
`ruff check app/` clean; no file outside `docs/` says "fairy" except deliberate provenance notes.

### Chunk B — Demolition (≈1–2 sessions)

One commit per deletion group, each with a message naming what replaces it and where the
original lives (`fairy@76909c4:<path>`).

Delete, in order:
1. **Services** — all 38 except `password.py`, `job_runner.py`, and the six PORT-marked modules
   which move to `app/services/_ported/` as read-only reference material, ignored by `ruff` and
   excluded from imports. They are *deleted from the runtime* and kept only as porting source.
2. **Formula** — `app/formula/zzz/` (1,455 lines). `formula/{builder,nodes,tags}.py` stay.
3. **Models** — `agent.py`, `disc.py`, `w_engine.py`, and the ZZZ half of `enums.py` and
   `build.py`. `user`, `session`, `team`, `optimization_job`, `buff_preset`, `base` stay.
4. **Schemas / API / repositories** — the matching ZZZ-domain files. Keep `auth`, `health`,
   `common`, `optimization_job`, and the repository base.
5. **Data layer** — every importer except `base_importer.py`; both loaders; `scripts/dimbreath/`
   (superseded by Chunk E, ported from the copy in `/root/fairy`).
6. **Scripts** — the ~22 ZZZ audit/backfill/icon scripts. Note `download_*_icons.py` write into
   `/root/fairy/frontend/public/icons` — a hardcoded path into the *other repo*; these must be
   deleted, never run.
7. **Migrations** — all 39 `alembic/versions/*`. mistilteinn's history starts at one new initial
   migration in Chunk C. There is no production database to preserve.
8. **Tests** — delete every test whose subject was deleted. Preserve and keep green:
   auth/session/user/team/job/repository/middleware/rate-limit/body-size tests, plus
   `tests/unit/test_pando_*` and the formula-core tests. Expect the suite to fall from ~300
   files to roughly 30–40.

**Exit gate (this is the important one):** `pytest` **passes**, `ruff check app/` clean, the app
imports and `/api/v1/health` + auth endpoints answer. A red suite here is not "expected fork
breakage" — Chunk B is where the fork stops having an excuse.

### Chunk C — Genshin domain models, enums, initial migration (≈2 sessions)

Write the tables from §2.5 and the enums from §2.6 fresh. Rules:

- **Nothing is renamed from a ZZZ model.** New files, new classes. If a column looks like it
  wants to be `anomaly_buildup` under a new name, that is the leak the BRIEF warns about.
- Enums are derived from the live nanoka payloads and each carries a source comment naming the
  endpoint and version it was read from, in the style of fairy's `ELEMENT_ID_MAP` provenance
  comments.
- `Element` excludes Physical; a separate `DamageType` carries `physical | elemental`.
- `ArtifactSlot` is a 5-member `StrEnum` (not `IntEnum` — Genshin's slots are named, and the
  fixed-main-stat property of flower/plume belongs in a slot→allowed-mains table).
- `StatType` is generated from the observed `FIGHT_PROP_*` vocabulary with an explicit
  unmapped-key warning path, so a new patch's new prop shows up as a log line, not a silent drop.
- One new initial Alembic migration; `alembic upgrade head` on an empty `mistilteinn` database
  must succeed and `alembic downgrade base` must reverse cleanly.

**Exit:** model round-trip tests pass against the real `mistilteinn_test` database; migration
up/down clean; no import of any deleted ZZZ symbol anywhere in `app/`.

### Chunk D — nanoka GI importer + seed (≈2–3 sessions)

Port the transport layer of `nanoka_importer.py` verbatim (manifest pin → index → detail →
upsert → stale prune), rewrite the mapping layer against the GI payloads.

- `manifest.json` → `["gi"]["latest"]` pins the version; record it in a seed-provenance row so
  "which patch is this DB" is a query, not a guess.
- Four entity passes: `character`, `weapon`, `artifact`, `monster`.
- Character detail carries `chara_info` (vision, birth, release), ascension/promotion stats,
  talent tables, constellations. The exact key layout must be read from a saved sample, **not
  assumed from the ZZZ shape** — Task D.2 exists to write that sample down first.
- Reseed idempotency: running the seed twice must produce an identical DB (fairy's stale-prune
  pattern already does this; keep it).
- `verify_seed.py` port: row counts per table, plus a small set of hand-checked anchor values
  (a known character's base ATK, a known artifact set's 2pc text) that fail loudly on drift.

**Exit:** `python -m scripts.seed_db` fills `mistilteinn` from a cold start; `verify_seed`
passes; 150 characters / 286 weapons / 65 artifact sets present (counts as of 7.0.51 — the
assertion is "matches the index length", not the literal number).

> **Delivered 2026-08-21 (PR #3).** Exit met, with four corrections this sketch could not
> have made — all of them found by sweeping every payload of an entity rather than reading
> one, and all recorded in `docs/LOG_mistilteinn.md` (D.1-D.9):
>
> 1. **Index keys are strings.** 28 of the 150 character keys are `"{body}-{element}"`
>    (Traveler variants); `characters.nanoka_id` had to widen from `Integer`.
> 2. **"Matches the index length" is not the right assertion for two of the four passes.**
>    26 weapon entries are cosmetic skins and 225 monster entries are stat-less codex
>    wildlife; both are *skipped*, so the exit condition is `imported + skipped + failed ==
>    index length`, which is what `verify_seed` checks.
> 3. **A monster payload is a family**, not a row — the stats are on 1-17 children and they
>    differ. The canonical child is chosen by a stated rule and recorded per row.
> 4. **`passives[].unlock` has two shapes** (int gate, or a condition id list), so
>    `unlock_ascension` is nullable with `unlock_condition_ids` beside it.
>
> Also delivered beyond the sketch: `scripts/capture_nanoka_fixtures.py`, so the committed
> ground truth has a reproducible derivation and a `--check` drift mode.

### Chunk E — YuanShenResources snapshot toolkit (≈2 sessions, parallel-safe with D)

Port `scripts/dimbreath/` → `scripts/yuanshen/` from the `/root/fairy` copy.

- Swap the GitHub raw/tree calls for GitLab's (`/api/v4/projects/GuraFoundation%2FYuanShenResources/…`).
- Keep the three properties that made the fairy toolkit trustworthy: **pinned commit SHA** in a
  committed `provenance.json`, **local byte cache** (TextMap is large), and **`base ⊕ overwrite`
  TextMap merge** with an anchor assertion that fails if the merge silently loses the newest
  content.
- Genshin table names replace ZZZ's: `AvatarExcelConfigData`, `WeaponExcelConfigData`,
  `ReliquaryExcelConfigData`, `AvatarSkillExcelConfigData`, `AvatarTalentExcelConfigData`, etc.
  Build the table catalog first (`build_table_catalog.py` equivalent) rather than guessing names.
- **Committed snapshots only.** No gate, test, or importer may fetch from GitLab at run time.
  The output is a checked-in artifact; regeneration is a manual, reviewed step.

**Exit:** `python -m scripts.yuanshen.fetch --lang en --merge` produces a merged TextMap and
asserts its anchor; a committed snapshot of at least the avatar/weapon/reliquary tables exists;
no test touches the network.

> **Delivered 2026-08-21 (PR #4).** Exit met, with three corrections — full detail in
> `docs/LOG_mistilteinn.md` (E.1-E.6):
>
> 1. **There is no `base ⊕ overwrite` TextMap merge to port** — Genshin publishes no
>    Overwrite layer. It publishes two near-disjoint files per language (589,892 and
>    231,397 keys, 363 shared), so the rule is a **union**, and it is just as mandatory:
>    every character, weapon and set name resolves through `_Medium` alone.
> 2. **The pin is `main` (OSCBWin7.0.51), not `live` (OSRELWin7.0.0)** — matching the
>    nanoka version Chunk D seeded from. Two sources on different patches would be worse
>    than either alone.
> 3. **`MAIN_STAT_POOL` is not a depot join.** This dump has no `weight` column, so the
>    depot lists are supersets; the allowed lists come from
>    `ReliquarySetSchemeMainPropExcelConfigData` and are cross-checked against a second
>    table and against their own cardinalities.
>
> `build_column_dicts.py` / `build_upstream_mv.py` were **not** ported as such: their ZZZ
> job was to make an unfamiliar 1,900-table corpus navigable, and `build_table_catalog.py`
> plus a snapshot builder that names its sources covers what Chunks F-H actually need. Port
> the column-dictionary tooling when a task wants it, not before.

### Chunk F — Stats and the damage chain (≈2–3 sessions)

The first chunk where correctness, not mechanics, is the risk.

- `formula/genshin/` sibling to the deleted `formula/zzz/`: `tags.py`, `stats.py`, `sheets.py`,
  `damage.py`, feeding the existing `pando` calculator.
- `stat_calculator.py` rewrite: base stat curves, ascension bonuses, weapon main+sub, artifact
  main+substats, EM as a first-class stat.
- `damage_calculator.py` rewrite around the Genshin chain: base × (1 + DMG bonus) × crit ×
  DEF term × RES term × amplifying term. No stun area.
- **CLAUDE.md's hard rule applies with full force here: do not write a multiplier, reaction
  coefficient, or level curve from memory.** Every constant is sourced from gcsim, KQM, or the
  Amber/nanoka payload and cited *at the line that introduces it*. A task that cannot produce a
  citation is blocked, not guessed — this is the failure mode the BRIEF names as fairy's
  hardest-won lesson.
- **Amplifying reactions only** in this chunk, per the BRIEF's ship-order ruling. Transformative
  and additive wait for the gauge engine.
- **Crossval with require-DB mode from day one.** `CROSSVAL_REQUIRE_DB=1` makes a skipped level
  a hard failure. Fairy shipped a stale golden fixture because a skipped check read as a pass;
  that bug is pre-paid here and must not be re-earned.

**Exit:** a damage figure for one fully specified character/weapon/artifact/enemy configuration
matches a gcsim fixture within an agreed tolerance, with the tolerance and its justification
written into the crossval doc.

### Chunk G — Artifact optimizer + GOOD import (≈1–2 sessions)

- `disc_optimizer.py` → `artifact_optimizer.py`: 5 slots, fixed flower/plume mains, per-slot
  main-stat pools. Keep top-K / Pareto / budget-K and the checkpoint/cancel machinery intact.
- `scanner_importer.py` → `good_importer.py`: GOOD is a documented, stable, widely-produced
  format (Inventory Kamera and others). Validate against the published schema; reject rather
  than coerce on unknown keys.
- `optimizer_pipeline.py` / `rank_pipeline.py` / `job_runner.py` port: mostly slot-count and
  stat-vocabulary edits.

**Exit:** a GOOD export imports to `artifacts` rows; the optimizer returns a ranked build set
for a seeded character; `tests/perf` re-baselined for the 5-slot search space.

### Chunk H — Kit corpus, modifier DSL, validation harness (Phase 4 — own DESIGN doc)

Sketch only: retarget `modifiers.py` scope vocabulary; define the Genshin kit-JSON schema;
port `validate_kits.py` levels L0–L2/L4–L6/LR/LU; rewrite `.claude/agents/kit-{curator,auditor}.md`
and `.claude/skills/kit-curation/` from ZZZ kits to Genshin talents/constellations; propose the
MVP roster cut (BRIEF constraint 4: ~20–30 characters by Spiral Abyss usage, owner approves).
Genshin makes this cheaper than fairy: kits are immutable post-release, so curation is
write-once, and the Pattern A/B override class largely disappears.

### Chunk I — Rotation / combo model (Phase 3 prerequisite — own DESIGN doc)

`combo_step_resolver.py` replacement, expected *smaller* than what it replaces. Adds on-field /
off-field distinction, swap cooldowns, burst energy. Depends on the gcsim frame-data harvest,
designed as a snapshot-generating script on the Chunk E pattern.

### Chunk J — Frontend rewrite + Mitya visual identity (deferred)

Angular pages are ZZZ-shaped (`discs`, `disc-slot-picker`, disc filters) and wait for the
backend. The Mitya design-token pass lands here and **needs owner-supplied reference art**.

### Chunk K — Deploy (deferred)

Re-author the deleted `deploy-prod.yml` against a mistilteinn target, DNS for
`mistilteinn.aetherus.dev`, tunnel config, and the co-hosting confirmation the BRIEF asked
Planner to make (now simplified by A3: one Postgres, two databases, so the marginal cost on the
Oracle VM is one backend container).

---

## 4. Test strategy

- **Chunk B is a floor, not a ceiling.** The surviving infra suite must be green at the end of
  demolition and stay green through every later chunk. Any commit that reds it is reverted, not
  followed up.
- **TDD per CLAUDE.md**: each new domain model, importer mapping, and formula gets its test
  first. The one exception the codebase's own history argues for: importer mapping tests are
  written against a *saved payload sample*, so write the sample down (Task D.2) before the test.
- **Two gate rules carry over verbatim from fairy and are pre-paid, not retrofitted:**
  1. *A skipped check blocks.* Require-DB modes exist from the first crossval fixture.
  2. *The agent runs the harness; it never reasons in its place.* Ground-truth questions are
     answered by querying the DB, never by reading the JSON the answer might be wrong in.
- Coverage targets from CLAUDE.md hold: >90% on services, **100% on damage calculation**.

## 5. Risks specific to this port

| Risk | Mitigation |
|---|---|
| **Scorched earth strands the repo.** Demolition is easy; the rebuild is where sessions run out. | Chunk B's exit gate is a *green* suite on a booting app. The repo is always in a defensible state, just a small one. |
| **ZZZ shapes leak into the Genshin models** — the BRIEF's named top hazard. | Chunk C writes new files rather than editing old ones; ported reference code sits in `_ported/`, excluded from imports, and is deleted when its port lands. |
| **Fabricated constants** — fairy's worst historical failure. | Citation-at-the-line rule in Chunk F; a missing citation blocks the task. |
| **nanoka GI schema drift** between the probed 7.0.51 and whatever ships next. | Version pinned in seed provenance; unmapped-key warnings rather than silent drops; the index-length assertion catches roster changes. |
| **GitLab source takedown** (GI's DMCA history is worse than ZZZ's). | Committed snapshots only; nanoka alone can carry the roster if YuanShenResources vanishes. |
| **`WEAPON_CROSSBOW` class of surprise** — the BRIEF's domain knowledge is one patch stale in places. | Every enum in Chunk C is read off a live payload, with the endpoint and version cited in a comment. |
| **Two ports of Postgres, one box.** | A3 removes the collision at the DB layer; 8001/4201 removes it at the app layer. Confirm before the Chunk K deploy. |

## 6. Open questions

Carried forward from the BRIEF, still owner-level, **not blocking Chunks A–G**:

- **OQ-M1** — public tool or personal tool? Decides whether incumbent strength matters and
  whether MVP polish is in scope. Needed before Chunk J.
- **OQ-M2** — approve the timeboxed gcsim-embed spike before building the gauge engine?
  Needed before Phase 3 / Chunk I.
- **OQ-M3** — hosting. Partially resolved by A3 (shared Postgres); the remaining question is
  whether both stacks live on the same Oracle VM. Needed before Chunk K.
- **OQ-P1 (new, Planner)** — Mitya reference art for the Chunk J palette. fairy's tokens were
  sampled from a specific image; mistilteinn needs the equivalent. Owner supplies.

---
**Planner output complete. Hand to Worker at `docs/TASKS_mistilteinn.md` Task 0.1.**
