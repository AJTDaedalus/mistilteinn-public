# DESIGN — upstream bump, 2026-09: gcsim re-pin + nanoka catalogue

Status: **planned, not started. All five owner decisions are answered** (§5, 2026-09-19).
Evidence: `docs/RESEARCH_gcsim_repin_2026_09.md` (gcsim, 49 Go commits triaged,
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
| grammar | `1de5a4243` adds `special_skill` to the action enum. It is a **cooldown bucket, not a keyword** — `pkg/gcs/ast/keys.go` has no such token | `authorable_actions()` reads the enum, so the builder would offer an action gcsim's own parser rejects. §2 step 1, **before the pin moves** |
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

**What matters more than the bump:** nanoka **deletes old versions**. `gi/6.7` returns 404
(confirmed 2026-09-19). Once 7.1 goes live, 7.0.51 will probably 404 too, and the repo commits
only 9 of the ~1,086 payloads a reseed needs. D3 rules on this — §3.

## 2. Approach — gcsim (Chunk U)

**Recommended pin: tag `v2.47.2` = `caf738dc8` (2026-09-18).** The relicence notice guarantees
MIT only for *"released versions up to and including v2.47.2"*. `7305f726f`, the last commit
before the relicence, is seven commits past that tag. Its tree still says MIT, but no release
covers it. The tag costs one Go change, **Jade Vista**. That is the smallest price that keeps
the licence question closed. (D1)

The order inside U is load-bearing:
1. **Make every gcsim move authorable, and make a new one fail loudly.** Owner ruling,
   2026-09-19: *we cannot just ignore a move gcsim implements.*

   `special_skill` turns out not to be a move at all. It is a **cooldown bucket**:
   `pkg/gcs/ast/keys.go` has no such token, so no gcsim config can spell it, and the
   player-visible moves it tracks are authored as ordinary actions that dispatch internally —
   Varka's Four Winds through `charge` (`internal/characters/varka/charge.go:96`) and
   Odette's recast through `skill` (`internal/characters/odette/skill.go:113`). Offering it
   would have produced configs gcsim rejects; **not** offering it loses nothing.

   So the rule is not "offer gcsim's enum" and not "offer the parser's keys" either. It is:
   every entry in gcsim's action enum is either **authorable** (a parser key, or a variant a
   character exposes through params) or on a **reviewed non-authorable list** with a reason.
   `build_key_snapshot` captures the parser keys beside the enum; a test fails on any enum
   entry that is neither. That is the same shape as the reviewed unimplemented-character
   list, and it means the next `special_skill` is a red test rather than a silent gap.

   Separately, U.3 checks the new kits by driving them: each of Iansan, Prune, Odette and
   Cryo Traveler gets a config authored in our builder and run through gcsim.

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
notice beside the artifact. That is independent of the re-pin and can land first.

Whether **mistilteinn itself** gets a LICENSE is a separate question nobody has asked yet. It
is not blocking, and it is not in scope here.

## 3. Approach — nanoka (Chunk V)

**Reseeding always takes the version nanoka publishes today** (D3). That is the owner's
ruling, and it settles the retention problem by not fighting it: upstream keeps only the
current cycle, so a pin we cannot recapture is not a pin we can reseed. Nothing is archived,
and the catalogue moves forward when it is reseeded.

Two consequences the chunk has to make true, because today's tree assumes otherwise:
- **`verify_seed --live` and the prod `reseed` job must target the current version**, not the
  committed `FIXTURE_VERSION`. Left as they are, both start failing the day 7.1 lands.
- **The committed fixtures stay a snapshot of record**, not a reseed source. They pin what the
  enums and mappings were derived from (9 payloads), and `test_capture_pinning` keeps them
  honest. Say so where the pin is declared, so nobody reads them as a backup.

**The bump itself goes to 7.1, not 7.0.54.** 7.0.54 differs from our pin only in beta tuning
that 7.1 supersedes, plus one regression (below). 7.1 is inferred to land around 2026-09-22 on
a six-week cycle; that is a guess, and V.2 waits on the manifest rather than on the date.

**The catalogue keeps following `latest`, beta content included** (D4) — the 2026-09-07 ruling
stands. Beta rows stay importable and marked, and each re-pin moves their numbers by design.

The sequence is the repo's existing one (`RESEARCH_nanoka_bump_7_0_54.md` §Recommendation):
`capture_nanoka_fixtures --version <v>` (always pass it), update the four hand-written pin
sites, `seed_db`, `verify_seed`, move the YuanShen snapshot to the matching build, re-run
icons and codegen if anything changed, then drive `/planner`, whose inputs come from here.

**One released weapon regressed upstream.** Exaiphanes Blade (11521) has had zero ascension
cost and no materials since 7.0.52, while `gi/7.0` still carries the full bill. If that
survives into 7.1 the planner will price it at nothing, so V.3 rules on it with a citation
rather than letting the zero through unexamined.

## 4. Coupling between the chunks

The two are independent except at `test_gcsim_character_coverage`: a character nanoka adds
that gcsim lacks is a reviewed entry, and one gcsim adds that nanoka lacks resolves to nothing.
Whichever chunk lands second re-derives that fixture. Neither blocks the other.

## 5. Owner decisions — all answered 2026-09-19

| # | question | ruling |
|---|---|---|
| D1 | which commit to pin | **tag `v2.47.2` (`caf738dc8`)**. *"2.47.2 is fine if we have a good reason not to take the latest"* — the reason is the licence: gcsim's own notice guarantees MIT only for releases up to that tag. Cost: Jade Vista |
| D2 | cross-pin runs in the corpus, given the −8.2 % shift | **keep DECISIONS §26 as it is.** Saved runs from an older pin are still served |
| D3 | nanoka retention | **no archive; always reseed at the version nanoka publishes today.** See §3 |
| D4 | beta (`latest`) or `live` | **keep `latest`**, beta rows included |
| D5 | Traveler and Skirk story buffs | **match gcsim** — model them here, default-on, as Chunk W |

**Chunk W follows from D5 and is new work, not a re-pin task.** gcsim applies the True Moon
archon quest buffs (`473e89986`) and the older Skirk story buff by default; we model neither,
so `/explain` disagrees with the simulator by about 27 % on Travelers today — before any
re-pin. W sources the values from gcsim at the pin, applies them in the stat chain with the
citation rule, and proves the agreement against a gcsim run. It is sized on its own and is
not a blocker for U or V.

One open item, not blocking and owned by nobody yet: the stray `seed_runs` row from
2026-08-31 recorded as 7.0.51 but carrying live-7.0 totals and 9 pruned rows
(`RESEARCH_nanoka_bump_7_0_54.md` §Open questions). Not reproduced.
