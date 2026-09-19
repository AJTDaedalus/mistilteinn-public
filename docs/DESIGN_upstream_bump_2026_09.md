# DESIGN — upstream bump, 2026-09: gcsim re-pin + nanoka catalogue

Status: **planned, not started.** Five owner decisions are open (§5); tasks that depend on one
say so. Evidence: `docs/RESEARCH_gcsim_repin_2026_09.md` (gcsim, 49 Go commits triaged,
measured in scratch worktrees) and `docs/RESEARCH_nanoka_bump_7_0_54.md` (nanoka, 1,086
payload pairs diffed). This doc is the decisions and the order; the research files are the
numbers.

## Branch policy

- Planning lives on `docs/upstream-bump-plan` (this doc, TASKS, both RESEARCH files).
- Implementation is **two independent branches off `dev`**, one PR each (one PR per chunk):
  - `feat/gcsim-repin-v2.47.2` — Chunk U
  - `feat/nanoka-7.1` — Chunk V (blocked until nanoka publishes the 7.1 build; see §3)
- **No direct commits to `dev`.** Merge only after `python -m scripts.ci_local` exits 0 on the
  exact PR head (`--clean` for U, since it changes the wasm build).
- Task 0 of each chunk in `docs/TASKS_upstream_bump_2026_09.md` is the branch-setup gate.

## 1. What changed upstream

**gcsim**: 177 commits since the pin `a36661d9` (2026-08-29). About 130 of them are UI and
worker churn that we never consume. The 49 that touch Go break down like this:

| class | what | effect here |
|---|---|---|
| new kits | Iansan, Prune, Odette, Cryo Traveler (×2 keys); 5 weapons, 2 sets | 31 → 26 uncovered characters; snapshots only **add** entries |
| grammar | `1de5a4243` adds action `special_skill` to the enum **but not to the parser** (`pkg/gcs/ast/keys.go`) | `authorable_actions()` reads the enum, so the builder would offer an action gcsim then rejects. **Must fix first** |
| output | `61f578730` renumbers the element enums; the empty element now reads `"none"`, not `""` | We read by name, so this is harmless, but `verify-gcsim-recipe` treats `''` as unlabelled and would let `"none"` through |
| frames | `60894d7cb` fixes frame tables for about 70 characters | `skirk_team` sample **−3.13 %**; vendored Skirk/Furina/Citlali/Escoffier **−8.2 %** |
| kit buffs | `473e89986` adds a default-on Traveler True Moon story buff | Traveler DPS about **+27 %**. `/explain` models neither this buff nor the older Skirk one |
| kit fixes | Varka, Shenhe, Mona, Ifa, Jahoda, PMC, Noelle/Xinyan shields, mislabeled `AffectedStat`, TTDS ICD | Moves sim results for those kits. Not measured per kit |
| licence | `05f01a733` relicenses to **AGPLv3** as of 2026-09-19. No Go changes come after it | §2 |

**What held**, measured rather than inferred:
- crossval gives `108.53039935232651` at both commits, native and wasm;
- both snapshots reproduce byte-for-byte at the old pin, and every existing multiplier is unchanged at the new one;
- the multiplier crossval is 0 mismatches over 19,466 hits;
- all 18 emitted/vendored configs validate;
- Go is still 1.27.0, so `Dockerfile.prod` needs nothing.

**nanoka**: `latest` is 7.0.54, and 7.0.50–7.0.54 have **identical index keys** (150 / 286 / 65 / 585):
- no schema drift in any of the 1,086 payloads;
- all 9 committed detail fixtures are byte-identical;
- no id disappears, so there is no prune.

The only differences are:
- beta tuning for Vesna and Vodyanitsa;
- six beta weapons getting real names;
- **Exaiphanes Blade (11521) losing its whole ascension bill** from 7.0.52 onward. That weapon is released, and the owner holds two copies.

**What matters more than the bump:** nanoka **deletes old versions**. `gi/6.7` returns 404 (confirmed 2026-09-19). Once 7.1 goes live, 7.0.51 will probably 404 too, and the repo commits only 9 of the ~1,086 payloads a reseed needs.

## 2. Approach — gcsim (Chunk U)

**Recommended pin: tag `v2.47.2` = `caf738dc8` (2026-09-18).** The relicence notice guarantees
MIT only for *"released versions up to and including v2.47.2"*. `7305f726f`, the last commit
before the relicence, is seven commits past that tag. Its tree still says MIT, but no release
covers it. The tag costs one Go change, **Jade Vista**. That is the smallest price that keeps
the licence question closed. (D1)

The order inside U is load-bearing:
1. **Make the action list parser-derived before moving the pin.** Extend `build_key_snapshot` to
   capture `actionKeys` from `pkg/gcs/ast/keys.go`, and make `authorable_actions()` offer
   `enum ∩ parser`. Add a test asserting every offered action is a parser key. At the current
   pin this is a no-op. At the new pin it drops `special_skill`, which proves the test catches
   the case it was written for.
2. **Move the pin and regenerate everything that names it, in one reviewed commit.** That
   covers `CROSSVAL_gcsim.md` (commit, date, title, the Go row), both snapshots, crossval JSON,
   `skirk_team_calc.json`, the ER sweep, the coverage fixture and the OpenAPI contract. Each
   PROVENANCE explains its diff, per the "fixture regeneration is a reviewed diff" rule.
3. **Fix citation drift in the same PR.** Every `damage.go` citation moves −4 lines.
   `element.go` was rewritten (`ElementString` is gone). `attack.go` lost its delimiters and
   gained `RelicSkill`. `exec.go:151→156` and `sysfunc.go:472→491`. Three `damage.go` rows and
   the ER-sweep PROVENANCE are **already wrong at today's pin**; fix those too.
4. **Drive it.** A green suite here is blind to wiring (CLAUDE.md). Build the prod image,
   run a real multi-character rotation search in the browser, and confirm `BUILT_FROM` on the
   deployed site after the merge.

**Licence compliance is overdue whatever the pin.** We serve `gcsim.wasm` without gcsim's MIT
notice (`extractLicenses: false`), and mistilteinn has no LICENSE of its own. U.1 ships the
notice beside the artifact. That is independent of the re-pin and can land first. Whether
mistilteinn itself gets a licence is D5.

## 3. Approach — nanoka (Chunk V)

**Do not bump to 7.0.54 as a chunk.** It adds only beta tuning that 7.1 will supersede, plus
one regression (11521). The bump worth doing is to **7.1**, when nanoka publishes it (inferred
around 2026-09-22 on a six-week cycle; not checked).

**Before that, close the retention gap (D3).** A pin that upstream deletes cannot be reseeded,
so `verify_seed --live` and the prod `reseed` job stop working the day 7.1 goes live. The fix
is to archive the full payload set for the pinned version somewhere we own, and to make the
transport able to read from the archive. It has to happen **before** 7.0.51 disappears if we
want 7.0.51 recoverable, which means now.

The bump itself follows the repo's existing sequence, which is in
`RESEARCH_nanoka_bump_7_0_54.md` §Recommendation:
- `capture_nanoka_fixtures --version 7.1.x`;
- update the four hand-written pin sites (both `FIXTURE_VERSION` constants, the literal in
  `test_seed_db.py`, and `PROVENANCE.md`);
- `seed_db`, then `verify_seed`;
- move the YuanShen snapshot to the matching build;
- run icons and codegen only if something changed;
- then the planner checks, since the materials data comes from here.

Pinning beta versus live is D4. The importer follows `latest` (beta) by design, and the owner's
2026-09-07 ruling keeps `is_beta` rows for the planner.

## 4. Coupling between the chunks

The two are independent except at `test_gcsim_character_coverage`: a character nanoka adds
that gcsim lacks is a reviewed entry, and one gcsim adds that nanoka lacks resolves to nothing.
Whichever chunk lands second re-derives that fixture. Neither blocks the other.

## 5. Owner decisions

| # | question | recommendation | blocks |
|---|---|---|---|
| D1 | Pin `v2.47.2` tag (`caf738dc8`), or `7305f726f` (adds Jade Vista, MIT tree but past the last MIT release) | **tag** | U.2 |
| D2 | DECISIONS §26 serves older-pin runs with `any_pin=True` on the premise that kits rarely change. This re-pin moves one vendored team by **−8.2 %**. Keep §26, or stop serving cross-pin runs (or label them) | **label cross-pin runs as from an older sim, and stop ranking them against fresh ones.** Needs its own small design pass if accepted | U.7 |
| D3 | Archive nanoka payloads for the pinned version: commit them (size not yet measured), or keep them in a prod-side store the transport can read | **measure first**, then decide. Either way, capture 7.0.51 **before 7.1 goes live** | V.1 |
| D4 | Pin nanoka to beta `latest` or to `live` | **keep `latest`** (the current ruling), and re-pin each beta build deliberately | V.2 |
| D5 | Traveler (and Skirk) story buffs: gcsim applies them by default, and `/explain` models neither. Match gcsim, or turn them off in emitted configs, or surface the difference | **surface it now, and model it as a separate plan** | U.8 (docs only) |

Also open, not blocking: the stray `seed_runs` row from 2026-08-31 recorded as 7.0.51 but
carrying live-7.0 totals and 9 pruned rows (nanoka research §Open questions). Nobody has
reproduced it.
