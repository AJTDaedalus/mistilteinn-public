# RESEARCH: re-pinning gcsim, 2026-09

**Status:** research only. Nothing in the repo has been changed apart from this file. Every
number below was **measured** in a scratch worktree unless it says *not checked*.

| | |
|---|---|
| **Current pin** | `a36661d918772851378d48a38c267dd6efe49540` (2026-08-29, `git describe`: `v2.45.0-4`) |
| **Candidate** | `7305f726fa7f88c3435e22720526a9bc4a45230c` (2026-09-19, `v2.47.2-7`), the parent of the relicense commit `05f01a733` |
| **Conservative alternative** | tag `v2.47.2` = `caf738dc807a646e2eee7e7b572f225dd6deb510` (2026-09-18). See §Licence |
| **Distance** | 174 commits pin..candidate, and **49 touch `*.go`**. Everything after the candidate on `origin/main` is UI-only |
| **Go toolchain at candidate** | `go.mod` says `go 1.27.0` with no `toolchain` line, the same as at the pin. `golang:1.27-alpine` in `frontend/Dockerfile.prod` still satisfies it |

## Summary

- **The damage chain has not moved.** Crossval `ayaka_normal_1`/`_nocrit` at the candidate
  gives `108.53039935232651`, the same to the last digit. Native and wasm agree. The committed
  JSON differs only in `sim_version` and a new `target_details[0].particle_element: "none"`.
- **The committed snapshots regenerate cleanly.** Run at the pin, `build_key_snapshot` and
  `build_multiplier_snapshot` reproduce the committed `keys.json` and
  `talent_multipliers.json` **byte-for-byte**. At the candidate the only differences are
  additions: 5 characters, 5 weapons, 2 sets, 4 aliases, one action (`special_skill`), 3 new
  multiplier characters, one new Yumemizuki row, and one new Ifa param. **M.4 multiplier
  crossval against the seeded DB with the candidate snapshot: 110 characters, 19,466 hits,
  0 mismatches.**
- **One real break: `special_skill`.** `1de5a4243` adds `special_skill` to `astr`, and
  `authorable_actions()` derives from `astr`, so after a re-pin the builder would offer it
  on every character. **gcsim's own parser rejects it**: `validateConfig` returns
  `unexpected token after <character>: special_skill` at the candidate, from both native and
  wasm builds. The lexer's `actionKeys` (`pkg/gcs/ast/keys.go:92-104` at the candidate) does
  not include it. It needs adding to `_NOT_AUTHORED`, or better, deriving the vocabulary from
  `actionKeys`. After that, regenerate the OpenAPI contract.
- **Simulation numbers do move for real teams.** Seeded samples (seed 12345) of the six
  committed calibration fixtures: five are identical in every `calc`/`damage` event.
  **`skirk_team` goes from 219 to 215 hits and loses 3.13 % of its damage.** Bisected to
  `60894d7cb` (*Add checking animation length in tests*), which changes frame tables for
  about 70 characters, Escoffier included. On the vendored gcsim-db config
  `skirk-furina-citlali-escoffier` it is **−8.21 % DPS at z = −115** (1,000 iterations), with
  the same bisect result.
- **Traveler DPS rises by about 27 %** (`traveler_pyro` emitted config, z = +7.1). This is
  `473e89986`: a default-on *True Moon* story buff worth CR +10 %, CD +20 %, ATK/HP/DEF%
  +20 %, ER +20 % and EM +60. mistilteinn models neither this buff nor the existing
  `skirk_story_buff`, so gcsim and `/explain` already disagree for Travelers, and the re-pin
  widens that gap.
- **Coverage grows.** Iansan, Prune, Odette and both Cryo Travelers now resolve, so
  `gcsim_character_coverage.json` goes from 31 unimplemented entries to 26. Five catalogue
  weapons and two catalogue sets become simulatable: Blade of Atonement, Covenant of Frost
  and Snow, Echoes of the Heart, Exaiphanes Blade, Jade Vista, Heart of the Furnace and
  Scarlet Proof.
- **Output-format changes we read are benign.** The Element enum was renumbered and
  `NoElement` now prints as `"none"` instead of `""` (`61f578730`). AttackTag values ≥ 7 were
  renumbered (`387bbb936`). `BURST_ATTACK_TAG = 6` is unchanged, and `calc.ele` is a *Stat*
  index that did not move. The parser reads only `damage.ele` by name and `attack-tag == 6`.
- **Citation drift.** Every `pkg/enemy/damage.go` citation shifts by −4 lines. `element.go`
  was rewritten: `ElementString` is gone, the order is new, and `Burning`, `UnknownElement`
  and `EndEleType` were removed. `attack.go` lost its delimiters and gained
  `AttackTagRelicSkill`. Three existing damage.go citations were **already off at the pin**.
- **Fixtures a re-pin must regenerate**, because a test pins `sim_version` or `pinned_commit`:
  `crossval/ayaka_normal_1.json`, `er_sweep/ayaka_er_sweep.json`,
  `gcsim_character_coverage.json`, `keys.json` and `talent_multipliers.json`.
  `gcsim_sample/skirk_team_calc.json` also has to be regenerated, because
  `verify-gcsim-recipe` would fail on the hit count (219 against 215).
- **Licence.** The candidate's tree carries the MIT `LICENSE`. The relicense notice, however,
  only promises MIT for *"released versions up to and including v2.47.2"*, and the candidate
  is 7 commits past that tag. The only Go commit in that gap is `bf3524998` (Add Jade Vista).
  mistilteinn has **no LICENSE file** and ships `gcsim.wasm` without gcsim's MIT notice.

## Licence

Facts, read from `/root/gcsim`:

- `05f01a733` *license: relicense to AGPLv3 effective 2026-09-19 (#3033)*, 2026-09-19
  10:13 −0400. It changes `LICENSE`, adds `LICENSE-MIT` and updates `CONTRIBUTING.md`.
  - `LICENSE` at `05f01a733` opens: *"gcsim / Copyright (c) 2021 The gcsim contributors …
    GNU Affero General Public License … version 3 … gcsim is licensed under the AGPLv3
    effective 2026-09-19. Released versions up to and including v2.47.2 were licensed under
    the MIT License; see LICENSE-MIT. Code originally contributed under the MIT License
    remains available under those terms, and its MIT notice is retained per that license's
    requirements."* The full AGPLv3 text follows.
  - `LICENSE-MIT` at `05f01a733`: *"gcsim was licensed under the MIT License through release
    v2.47.2. Effective 2026-09-19, the project as a whole is licensed under the GNU Affero
    General Public License v3.0 (see LICENSE). Because the MIT License is permissive, portions
    of the code originally contributed under it remain available under the MIT terms below …
    The MIT-licensed releases (<= v2.47.2) remain available under this license via the
    project's git history and release tags."* The original text follows: `MIT License /
    Copyright (c) 2021 genshinsim`.
  - The commit message adds that *"All changes merged from this point are under AGPLv3"*.
- `git show 7305f726f:LICENSE` is the plain **MIT License, Copyright (c) 2021 genshinsim**.
  At the candidate the repository presented itself as MIT.
- `v2.47.2` is `caf738dc8` (2026-09-18). `v2.47.2..7305f726f` holds 7 commits, and only
  **`bf3524998` Add Jade Vista (#2763)** touches Go. The rest are UI and `CONTRIBUTING.md`.
- The current pin `a36661d9` is an ancestor of `v2.47.2` and is MIT without ambiguity.

**Two readings, for the owner.** This is not legal advice.
1. *The tree at `7305f726f` says MIT, so its code was published under MIT.* On that reading
   the candidate is fine.
2. *The project's own notice guarantees MIT only for `<= v2.47.2`.* On that reading, pinning
   the tag `caf738dc8` removes the ambiguity at the cost of Jade Vista (a 4★ bow, stats and
   passive in `internal/weapons/bow/jadevista/`). Everything else in this report holds for
   either commit, because all the other Go changes predate the tag.

**mistilteinn's own side:**
- There is no `LICENSE`, `LICENSE.*` or `COPYING` at the repo root. `README.md` §License
  says only *"Game data © miHoYo / HoYoverse. Fan project, not affiliated with miHoYo."*
- Production builds `gcsim.wasm` from source (`frontend/Dockerfile.prod`) and serves it to
  every browser. That is **distribution of a gcsim binary**. MIT requires the copyright and
  permission notice *"in all copies or substantial portions"*, and nothing in the bundle
  carries it: `angular.json` has `"extractLicenses": false`, and `frontend/gcsim/` holds no
  licence file. The gap exists **at the current pin already**. It is not created by the
  re-pin.
- A future pin **≥ `05f01a733`** would make the served wasm AGPLv3 object code. Conveying it
  requires offering Corresponding Source (§6). §13 is about *modified* versions interacting
  over a network, and we build unmodified upstream. That is still a decision for the owner,
  not an engineering one, and it is why this candidate stops at `05f01a733^`.

## Consumer inventory

Every place mistilteinn reads the pin or depends on gcsim behaviour. Found with `rg`, and
`backend/build/` was excluded.

| Consumer | What it reads from gcsim | Regenerate / verify |
|---|---|---|
| `docs/CROSSVAL_gcsim.md` §The pin | **The single pin** (`**Commit**` row) and the `**Go toolchain**` row | Hand edit. Every row below re-derives from it |
| `frontend/scripts/build-gcsim-wasm.sh` | Reads the pin from the doc and builds `./cmd/wasm` into `frontend/gcsim/`, writing `BUILT_FROM` (currently `a36661d9…`) | `npm run gcsim:build` |
| `frontend/Dockerfile.prod` (`FROM golang:1.27-alpine AS gcsim`) | The same pin grep, then `git clone`, checkout and `GOOS=js GOARCH=wasm go build ./cmd/wasm` | Built on deploy |
| `tests/unit/test_gcsim_pin_is_single.py` | The pin is declared only in the doc. The two builders read it. Crossval JSON `sim_version` equals the pin. CI builds and verifies the wasm | `pytest tests/unit/test_gcsim_pin_is_single.py` |
| `tests/unit/test_prod_go_satisfies_the_gcsim_pin.py` | The doc's Go row is ≤ the Dockerfile's `golang:X.Y` | pytest. **Still 1.27** at the candidate |
| `backend/app/data/gcsim/keys.json` (`scripts/gcsim/build_key_snapshot.py`) | `pkg/core/keys/*.dm.go`, `pkg/shortcut/*.dm.go`, `pkg/core/action/action.go` (`astr` plus the enum), and every `zz_*.dm.go` `paramsFor` block. `pinned_commit_sha` **is the runtime pin**: `gcsim_keys.pinned_commit()` feeds `/sim-runs` (409 on mismatch, `api/v1/sim_runs.py:76`), the recipe-cache epoch and the rotation API | `python -m scripts.gcsim.build_key_snapshot --src <clone at pin>`. It refuses unless the clone HEAD equals the doc pin. Tests: `test_gcsim_keys.py` (`pinned_commit() == doc`), `test_variant_params_are_classified.py` |
| `backend/app/data/gcsim/talent_multipliers.json` (`build_multiplier_snapshot.py`) | Commented `[]float64` tables in `internal/characters/*/zz_*.dm.go`. **Travelers are absent**, because their tables are hand-written `stats.go` | `python -m scripts.gcsim.build_multiplier_snapshot --src …`. Test `tests/crossval/test_talent_multipliers.py:104` checks sha == pin |
| `scripts/gcsim/crossval_multipliers.py` (M.4) | The snapshot above, compared against our nanoka parse | `python -m scripts.gcsim.crossval_multipliers [--fixtures]` |
| `scripts/gcsim/emit_sample_configs.py` → `frontend/gcsim/emitted/` | The emitter's output, fed to gcsim `validateConfig` and the cycle check | `python -m scripts.gcsim.emit_sample_configs`, then `npm run gcsim:verify-config` |
| `tests/fixtures/crossval/{ayaka_normal_1.json,.txt,_nocrit.txt}` + `tests/crossval/test_gcsim_crossval.py` | gcsim's result JSON. Asserts `sim_version == pinned_commit()` and `modified is False` (`:167-168`). `CROSSVAL_REQUIRE_DB=1` | Recipe in `fixtures/crossval/PROVENANCE.md`: native `./gcsim -c … -nb -out …`, then strip the noise fields |
| `frontend/scripts/verify-gcsim-wasm.mjs` | The browser build on `_nocrit`, compared with `21.706…` DPS | `npm run gcsim:verify` |
| `tests/fixtures/gcsim_sample/*_calc.json` + `frontend/scripts/verify-gcsim-recipe.mjs` | `sample(cfg, "12345")` `calc`/`damage` events. The verifier **regenerates at the pin and fails on a hit-count or ability mismatch** | `npm run gcsim:verify-recipe`. Regenerate by hand from the wasm |
| `tests/fixtures/er_sweep/ayaka_er_sweep.json` | 54 gcsim runs. `tests/unit/test_sim_retrieval.py:171` asserts `sim_version == pinned_commit()`. Its `PROVENANCE.md` **still names `3647a07a`** while the JSON says `a36661d9`: pre-existing doc drift | Recipe in its PROVENANCE (not scripted) |
| `tests/fixtures/gcsim_character_coverage.json` + `test_gcsim_character_coverage.py` | Which seeded characters fail `character_key()` against `keys.json`. Fails on drift in **either** direction | Recompute `_unimplemented()` and commit, with `pinned_commit_sha` |
| `app/services/gcsim_keys.py` | `authorable_actions()` = `astr` minus `{swap, wait, delay}`. `VARIANT_PARAMS`/`NOT_OFFERED_PARAMS` must classify every param. `_traveler_key` error text says *"there is no Cryo Traveler"* | Unit tests. **`special_skill` must be excluded** (see §Risks) |
| `app/schemas/rotation.py` (OpenAPI `enum` of actions) → `frontend/openapi.json` → `api.types.ts` | `all_offerable_actions()` / `authorable_actions()` | `test_openapi_contract_is_current.py`, then `npm run codegen` |
| `app/services/gcsim_tokenizer.py`, `gcsim_parser.py`, `rotation_converter.py`, `gcsim_emitter.py`, `rotation_tree_compiler.py`, `rotation_compiler.py` | gcsim's config language: action names, `wait`/`delay`, conditions (readiness, energy, status), `group_repeat` unroll, the `.ready` gate on bursts | `test_gcsim_construct_suite.py`, `test_gcsim_parser.py`, `test_gcsim_emitter.py`. `scripts/sweep_gcsim_db.py` (501 cached corpus configs in `backend/var/gcsim_corpus`, **not run**). `references/gcsim_db/*.txt` (5 vendored) |
| `app/services/gcsim_config.py` | `ENERGY_DRIP` (community configs, not gcsim code), swap_delay omitted (default 1, `pkg/gcs/parser/parser.go:55`), `target_fields` (`lvl`, `resist`, `pos`, `hp`, `freeze_resist`, `radius`) | `test_gcsim_config.py`, `test_swap_delay_is_never_zero.py`. `parseTarget.go` and `parser.go` are **unchanged** pin..candidate |
| `frontend/src/app/sim/recipe.ts` | `calc` fields, `damage.ele` **by name**, `damage['attack-tag']`, `BURST_ATTACK_TAG = 6`, `char_index` | `recipe*.spec.ts`, `verify-gcsim-recipe` |
| `frontend/src/app/sim/{rotation-stats,energy-delay,sample-timeline,gcsim}.ts` | `statistics.{dps,character_dps,failed_actions.insufficient_energy,dps_by_element,source_dps,…}`, `logs[].event=='action'` plus `logs.action` | specs, `verify-gcsim-runner` |
| `frontend/src/app/sim/recipe-cache.ts` (`SCHEMA = 7`) and the `sim_runs` table (`gcsim_pin` column, DECISIONS §26 `any_pin`) | The pin as a key. A re-pin invalidates the recipe cache (the pin sits inside `cacheEpoch`). The run corpus **keeps older-pin rows and serves them with `any_pin=True`** | No regeneration. The §26 premise is revisited in §Risks |
| `formula/genshin/{tags,stats,damage}.py`, `services/stat_calculator.py`, `frontend/src/app/sim/damage.ts` | File:line citations (see §Citation drift) | Hand re-check |
| `weapon_comparison` gcsim tier (`/compare-weapons/gcsim`, `sim/weapon-ranking.ts`) | gcsim weapon keys via `gcsim_keys.weapon_key` | `test_gcsim_weapon_configs_endpoint.py`. There is **no ported-passive JSON**: `app/data/gcsim_passives/` from `DESIGN_passive_port.md` does not exist, so gcsim weapon changes reach us only through simulation |
| Cited text across docs and code (`flins/skill.go:56`, `setup.go:94 @3647a07`, `run.go:154/155/187`, `exec.go:151`, `sysfunc.go:472`, `status.go:56`, `parseTarget.go:63`, `parseOptions.go:104`, `conditional/character.go:134`, `cmd/wasm/main.go:45`, `varesa/burst.go:41`, `player.go:53`) | Prose citations | See §Citation drift |

## Commit triage

Every commit in `a36661d9..7305f726f` that touches `*.go` (49 of them), oldest first.
Classes: **(a)** new content, **(b)** engine or grammar change, **(c)** numeric or behaviour
fix to an existing kit or item, **(d)** irrelevant to us.

| Hash | Title | Class | Affected consumer | Action |
|---|---|---|---|---|
| `541511f38` | Fix noelle/xinyan shield element | c | Noelle fixtures | None measured. The `noelle_redhorn*` samples are byte-identical |
| `b910aa1d4` | Fix mods with mislabeled AffectedStat | c | Alhaitham cons, Faruzan burst, Sucrose cons: sim results for teams with them | Note only |
| `381d0f316` | Add Stellar Swirl | a+b | New reaction (`stellarswirl.go`), new `AttackTag`s, Viridescent change, new Yumemizuki multiplier row | Multiplier snapshot gains 1 row. No reaction work needed (Chunk F models amp only) |
| `ade2effcc` | Fix Jahoda A1 Pyro | c | Jahoda sims | Note |
| `3c81e21b3` | Fix shenhe quills below A4 | c | Shenhe sims | Note |
| `473e89986` | Traveler True Moon quest stat buffs | **c** | **Every Traveler sim, +27 % DPS on `traveler_pyro`** (z = 7.1). Param `true_moon_story_buff` defaults to 1 | **Owner decision:** emit `true_moon_story_buff=0`/`skirk_story_buff=0`, or model them in `stat_calculator` so `/explain` matches |
| `707af6214` | Subscriptions and Attack Tags for SSw | c | Nocturne, Sunny Morning, Varka, `OnLunarReactionAttack`→`OnSpecialReactionAttack` | Note |
| `2cf702243` | Fix PMC's CA scalings | c | Pyro Traveler CA multipliers (`traveler/common/pyro/stats.go`, e.g. lvl-1 0.722→0.6072, lvl 10-14 lowered) | **Invisible to M.4**: Travelers are not in the multiplier snapshot. Compare against our nanoka parse by hand if it matters |
| `513bd930b` | Action log includes params | b | `action` events: message now `executed skill[hold=1]`, **only when `Debug`**. Field `logs.action` unchanged | None. `sample-timeline.ts` reads `logs.action`, and samples are debug runs |
| `1de5a4243` | Special Skill action + DiscardActionCooldown | **b** | **`keys.json` `actions` gains `special_skill`** (`action.go:125,146` at the candidate). `authorable_actions()` would offer it, and gcsim's lexer rejects it | **Must fix**: exclude it, or derive from `pkg/gcs/ast/keys.go:92-104` `actionKeys` |
| `f8772b595` | rSSw base damage; `CalcSpecialReactionDmg` | b/c | Stellar reactions only | None |
| `fd1699c4c` | Expose Ifa/Ororon nightsoul condition | b | New condition fields (outside our condition vocabulary) | None |
| `45f44eaba` | arm64 builds | d | `cmd/wasm/build.sh` gains `-trimpath` (our script does not use `build.sh`) | None |
| `387bbb936` | Remove AttackTag delimiters | **b** | `AttackTag` renumbered from 7 up (`RelicSkill` = 7, `WeaponSkill` 7→8, reactions shifted). `ReactionAttackStartDelim` removed | `BURST_ATTACK_TAG = 6` **still correct** (`attack.go:14` at the candidate). Update the `tags.py` comment and citations |
| `d0a7bb3eb`, `bdd9d861e`, `5a91f9c55`, `6916966cf` | Varka CD / sE CD / bugfixes / E CA | c | Varka sims | Note |
| `4dc3634df` | Segmented field in animation handler | b | `hitlag` log gains `Segmented`. Itto, Mavuika, Noelle CA and Wolf's Gravestone changed | None (hitlag is not parsed) |
| `61f578730` | Fix usage of attributes.Element | **b** | Element enum **renumbered and regenerated** (enumer). `NoElement` stringifies `"none"` (was `""`). `unknown`/`burning`/`burning-fuel` gone. `frozen` removed from `ast.EleKeys`. `.keys.element.*` ints changed. `dps_by_element` keys change accordingly | `recipe.ts` reads `ele` by name: OK. `verify-gcsim-recipe` treats `element === ''` as unlabelled, and `"none"` would now pass it. Display-only in `/calculate` byElement |
| `720f1a1f8`, `550c97d88`, `688764258`, `ece627835` | Add Prune + 3 fixes | a | New key `prune`; multiplier rows | Coverage fixture −1 |
| `b1ac4d662` | Ifa bugfixes | c | Ifa sims. `paramsFor` gains `low_plunge: [collision]` | `collision` already in `NOT_OFFERED_PARAMS` |
| `9420fe3e2` | Fix jahoda frames doc | d | none | none |
| `32bf1b5e5` | Merge AdditionalTag into AttackTag | b | `AttackInfo.AdditionalTags []AttackTag` | None (internal) |
| `4f9d1020a` | Fix shenhe quills regression | c | Shenhe sims | Note |
| `a80e6065a` | Extend TTDS ICD by 1s when on-field | c | Thrilling Tales sims (also now `AffectedStat: ATKP`) | Note |
| `a1d96bdc1` | Blade of Atonement | a | New weapon key | Now resolves |
| `3f9518102` | fix shenhe skill comment | d | none (comment) | none |
| `138b1a994` | Fix OnElementApplied emit | b/c | Event emission in `reactable.go` | Not visible in any of our samples (bisect showed no change) |
| `837e89688` | Update travelergeo.go | c | Geo Traveler | Note |
| `60894d7cb` | Add checking animation length in tests | **c** | **Frame tables for ~70 characters**, including Escoffier N1/N2 cancels 17→22 / 21→30 and removal of the `ActionCharge = 500` placeholders. **Moves `skirk_team` (−3.13 % seeded; 219→215 hits) and gcsim-db `skirk-furina-citlali-escoffier` (−8.2 %)** | Regenerate `skirk_team_calc.json`. Revisit DECISIONS §26 |
| `a27e8e281` | Echoes of the Heart | a | New weapon | Now resolves |
| `d1b130cc9` | Covenant of Frost and Snow | a | New weapon, alias `covenant` | Now resolves |
| `b9df20e5e` | Add Odette | a | New key `odette`, uses `ActionSpecialSkill` | Coverage −1 |
| `2fe552e56` | Yae Revelation | c | Yae kit rewrite (`cons.go` +227, new `stellar.go`) | Yae sims move. **Not measured** |
| `20d0a79e6` | Fix panic in SSW gadget checks | c | Stellar Swirl | None |
| `93775d3dc` | workers R2 | d | none | none |
| `450b73540` | protos protoc→buf | d | `pkg/model/*.pb.go` header lines only | None |
| `6916966cf` | Fix Varka E CA | c | (listed above) | — |
| `5cb4f796e` | Heart of the Furnace | a | New set, alias `furnace` | Now resolves |
| `ced1fa30e` | protos plugin bump | d | none | none |
| `f438abf30` | remove legacy Go preview/embed | d | `backend/cmd/*`, `cmd/services/embedgenerator` | none |
| `94cc01a89` | Fix Mona c2 buff duration | c | Mona sims | Note |
| `43823e2c2` | Exaiphanes Blade | a | New weapon, alias `exaiphanes` | Now resolves |
| `5dd054e33` | Add Iansan | a+b | New key. Generic param `movement` (`info/params.go`) is ignored by validation. New sysfunc `movement(n)` (`sysfunc.go`) | Coverage −1. Our importer will refuse a `movement()` call by name |
| `25e6ef499` | Add Cryo Traveler | a | `aethercryo`/`luminecryo`, alias `travelercryo` | Coverage −2. Fix the `_traveler_key` message |
| `d265e16d5` | Fix pipeline | a | generated data for Cryo Traveler | — |
| `437cd9963` | Scarlet Proof | a | New set | Now resolves |
| `9ee883735` | Mona omen extending on bubble break | c | Mona sims | Note |
| `bf3524998` | Add Jade Vista | a | New weapon. **The only Go commit after tag v2.47.2** | Drop it if pinning `v2.47.2` |

The remaining 125 commits are UI, web, workers, pnpm, CI and docs, all class d. None touch
`cmd/wasm/main.go`: the only `cmd/wasm` change is `build.sh`. `pkg/gcs` changes are limited
to `ast/keys.go` (lost `frozen` in `EleKeys`), `eval/sysfunc.go` (`movement()`, and
`pick_up_crystallize` now reads `EleKeys`), `parser/parseHurt.go` (default
`Element = NoElement`) and `validation/validate.go` (`movement` param ignored).

## Citation drift

Table in `docs/CROSSVAL_gcsim.md` §What has been cited so far, checked line by line at both
commits. *"at pin (actual)"* marks where the citation was already off before the re-pin.

| Citation | At pin | At candidate `7305f726f` |
|---|---|---|
| `pkg/core/attributes/stats.go:12-40`, `:44-46` | ok | **unchanged file** |
| `pkg/core/attributes/element.go:13-27` (element list) | ok | **Rewritten** (`61f578730`): enum now `element.go:7-19`, reordered `NoElement, Pyro, Hydro, Dendro, Electro, Cryo, Anemo, Geo, Physical, Frozen, Quicken`. Strings live in generated `element_enumer.go:11` (`_ElementName`). `ElementString`, which `tags.py:67` names as the source, **no longer exists** |
| `pkg/core/attacks/attack.go:5-20` (scopes) | ok | Scope constants now `attack.go:8-17`, with **new `AttackTagRelicSkill` at :15** between Burst and WeaponSkill. "Additional tags" Nightsoul/KinichCannon/VarkaSpecial at :20-22. `ReactionAttackStartDelim` (named in `tags.py:80`) **removed** |
| `pkg/core/attacks/attack.go:52-59` (strike types) | actual `:54-62` | `attack.go:87-95` |
| `pkg/core/player/character/basestat.go:73-101`, `:82`, `:82-84`, `:102-126` | ok | **unchanged file** |
| `pkg/enemy/damage.go:11-130` (chain) | ok | `:11-126` (−4, from the `IsDirect()` switch collapse, `61f578730`/`387bbb936`) |
| `damage.go:47` (DMG bonus) | **actual `:46`** | `:42` |
| `damage.go:65-66` (base, flat inside) | **actual `:63-64`** | `:59-60` |
| `damage.go:52-62` (ATK/HP/DEF/EM) | switch is `:51-60` | `:47-56` |
| `damage.go:81-84` (DEF term) | ok (`:80-83` + blank line) | `:76-80` |
| `damage.go:76-80` (DEF caps) | ok | `:72-76` |
| `damage.go:89-93` (RES) | ok | `:85-89`. **Semantics unchanged** (`>=` at 0.75 still present) |
| `damage.go:66-71` (crit clamp) | ok | `:62-67` |
| `damage.go:113-116` (EM amp) | ok (`:112-116`) | `:109-112` |
| `damage.go:101` (crit roll, CROSSVAL §3 and PROVENANCE) | roll at `:100` | roll at `:96` |
| `pkg/reactable/melt.go:23,30`, `vaporize.go:26,33` | ok | **unchanged files** |

Other gcsim line citations in code and docs:

| Citation (where) | At candidate |
|---|---|
| `pkg/core/player/exec.go:151` (`gcsim_config.py:244`, `test_swap_delay_is_never_zero.py:4`, `RESEARCH_recipe_cost.md:73`) | **moved to `:156`** (`x.QueueAction(h.swap(k), h.Delays.Swap)`) |
| `pkg/gcs/eval/sysfunc.go:472` (`rotation_compiler.py:240`) | **moved to `:491`** (the implicit-swap comment) |
| `pkg/simulation/setup.go:94` (cited "at pin `3647a07`", in `teams.py`, `build.py`, tests, docs) | same line and content (file changed +2/−2 elsewhere) |
| `internal/characters/varesa/burst.go:41` | same content (`func (c *char) Burst`) |
| `pkg/core/player/player.go:53` (`TASKS_mistilteinn.md`) | same (`SwapCD int`) |
| `flins/skill.go:56`, `run.go:154/155/187`, `parser.go:55`, `parseTarget.go:63`, `parseOptions.go:104`, `status.go:56`, `conditional/character.go:134`, `cmd/wasm/main.go:45` | **files unchanged** |

`frontend/src/app/sim/recipe.ts:40-48` cites `attack.go`'s enum for `BURST_ATTACK_TAG = 6`.
The value still holds (`attack.go:14`), but the comment's enumeration would need re-reading.

## Measurements

Scratch directory: `/tmp/claude-0/-root-mistilteinn/fb1f41ea-2ce7-45d4-b4de-39f3e6cfa126/scratchpad/`.
The host's `go` is 1.23.4. `GOTOOLCHAIN=auto` fetched the cached **go1.27.0** for both
builds.

```bash
cd /root/gcsim
git worktree add --detach $SCR/gcsim-pin  a36661d918772851378d48a38c267dd6efe49540
git worktree add --detach $SCR/gcsim-cand 7305f726f
(cd $SCR/gcsim-$w && go build -o $SCR/gcsim-$w.bin ./cmd/gcsim)        # both OK
(cd $SCR/gcsim-cand && GOOS=js GOARCH=wasm go build -o $SCR/cand.wasm ./cmd/wasm)   # OK, 43 s, 60.8 MB
```

A 15-line helper, `$SCR/zzsampler_main.go`, calls `simulator.GenerateSampleWithSeed(cfg,
seed, Options{})`, which is exactly what the wasm `sample()` calls (`cmd/wasm/main.go:79`).
It was dropped into `cmd/zzsampler` of each scratch worktree.

**1. Crossval oracle** (`$SCR/gcsim-$w.bin -c backend/tests/fixtures/crossval/<case>.txt -nb -out …`):

| case | pin | candidate |
|---|---|---|
| `ayaka_normal_1` total / dps | 108.53039935232651 / 21.706079870465302 | **identical** |
| `ayaka_normal_1_nocrit` | same | **identical** |
| field diff against committed JSON (noise stripped per PROVENANCE) | 0 fields | `sim_version`, `target_details[0].particle_element` (`"none"`, new) |

**2. Calibration samples** (seed 12345, `calc`+`damage` events compared with the committed
`*_calc.json`):

| fixture | pin | candidate |
|---|---|---|
| `rotation_gated`, `rotation_gated_nostats` | byte-identical (all 3,222 events) | calc/damage identical. Other events differ: snapshot `ele` `electro`→`none`, `hitlag` gains `Segmented`/`special_skill`, `charge` frames 500→66 on 24 events |
| `noelle_redhorn`, `_probe`, `_target` | identical | identical |
| `skirk_team` | identical | **219→215 hits, 1,338,594.78→1,296,751.47 (−3.126 %)**. Lost hits: cryo skill-tag 41→40, hydro skill-tag 50→47. First divergence is `source_frame` at event 20 |

The pin reproducing all six fixtures from native Go is itself a finding: **native and wasm
samples agree exactly**, so a native harness is a valid stand-in for the browser here.

Bisect for `skirk_team` (`$SCR/bis_test.sh <commit> skirk_team`, a third worktree):
`138b1a994` same, `837e89688` same, **`60894d7cb` diff**, and every later commit diff.

**3. Snapshot regeneration** (`$SCR/snap/run.py` monkeypatches `declared_pin` and `OUT` so
nothing committed is overwritten):
- Pin clone → `keys.json` and `talent_multipliers.json` **byte-identical** to the committed
  files.
- Candidate clone → additions only: characters `aethercryo, iansan, luminecryo, odette,
  prune`; weapons `bladeofatonement, covenantoffrostandsnow, echoesoftheheart,
  exaiphanesblade, jadevista`; sets `heartofthefurnace, scarletproof`; actions
  `special_skill`; aliases `travelercryo`, `covenant`, `exaiphanes`, `furnace`;
  `character_action_params` gains the 5 new characters and `ifa.low_plunge = [collision]`
  (no new param names, so `test_variant_params_are_classified` holds). Multipliers: `iansan,
  odette, prune` added, and `yumemizukimizuki` gains `skill / Elemental Mastery-Based Stellar
  Swirl DMG Increase / param 5`. **No existing value changed.**

**4. Multiplier crossval (M.4)** with the candidate snapshots swapped in (module globals
patched):

| mode | committed | candidate |
|---|---|---|
| `--fixtures` | 3 chars, 570 matched, 45 no table, 0 mismatched | identical |
| seeded DB | 107 chars, 18,881 matched, 3,004 no table, **0 mismatched** | **110 chars, 19,466 matched, 3,049 no table, 0 mismatched** |

**5. Key resolution against the committed nanoka fixtures** (`gcsim_keys` pointed at the
candidate `keys.json`, `cache_clear()`ed):
- characters newly resolving: `10000005-5`/`10000007-5` Traveler (Cryo), `10000110` Iansan,
  `10000132` Prune, `10000150` Odette. The coverage fixture goes from 31 to **26**
  unimplemented. Still out: Alyosha, Illuga, Kachina, Linnea, Lohen, Nefer, Sandrone, Vesna,
  Vodyanitsa, Zibai, Traveler (element `None`) and the 14 mannequins.
- weapons unresolved 48→43. The five above now resolve.
- sets unresolved 12→10: Heart of the Furnace and Scarlet Proof now resolve. The remaining 10
  are 1-3★ and *Prayers* sets.

**6. `validateConfig` in wasm** (`$SCR/wasm_probe.mjs`): the committed wasm (pin) and the
candidate wasm each accept **18/18** configs (5 `frontend/gcsim/emitted/*.txt` as currently
on disk, 5 `references/gcsim_db`, 6 `gcsim_sample`, 2 `crossval`). The `_nocrit` sample
total is `108.53039935232651` in both. **`ayaka special_skill;` is rejected by both**:
`ln10:7: unexpected token after <character>: special_skill`.

**7. Aggregate DPS, pin against candidate** (native, each config's own iteration count, z
from the two standard errors):

| config | pin | cand | Δ | z |
|---|---|---|---|---|
| emitted `traveler_pyro` | 1,105.7 | 1,403.3 | **+26.9 %** | **+7.1** |
| gcsim_db `skirk-furina-citlali-escoffier` | 141,383.5 | 129,773.7 | **−8.21 %** | **−114.7** |
| sample `skirk_team` | 30,509.5 | 30,275.7 | −0.77 % | −3.0 |
| sample `noelle_redhorn_target` | 2,348.8 | 2,320.8 | −1.19 % | −2.0 |
| everything else (11 configs) | | | within ±4.3 % | abs(z) ≤ 1.7 (noise) |

The Traveler move is `473e89986`: seeded sample 1,524.67 → 1,686.52 across that one commit.
The skirk-db move is `60894d7cb`: seeded sample 17.838 M → 16.153 M across that commit, with
the same hit counts. Per-hit damage fell for Skirk and Escoffier alike, and the run ends 39
frames later. The mechanism is not confirmed. The plausible one is Escoffier's longer
N1/N2 cancel frames shifting buff windows against Skirk's combo.

**Could not check / not run:**
- `scripts.ci_local`, the full backend suite and `npm test` at the candidate. That would
  need the committed files changed, which is out of scope for this research.
- `sweep_gcsim_db.py` over the 501 cached corpus configs. It measures our parser, and the
  only pin-dependent input is `keys.json`. Not run.
- The ER sweep was not regenerated. Its shape assertions at the candidate are unknown.
- Yae (`2fe552e56`), Varka, Mona, Shenhe, Ifa and Jahoda sim deltas were not measured: no
  committed fixture uses them.
- The production image build (`Dockerfile.prod`) was not built. Only the wasm target was.

## Risks and open questions

1. **`special_skill` leaks into the authoring vocabulary.** Mechanically this is the only
   breaking change. The fix fits in the re-pin PR. Options: (a) add it to `_NOT_AUTHORED`,
   a one-line change that does not generalise; (b) have `build_key_snapshot` also parse
   `pkg/gcs/ast/keys.go` `actionKeys` and intersect with it. Option (b) means the next
   CD-only action cannot recur, and it matches the file's own "derive, don't restate" rule.
   Planner's call.
2. **DECISIONS §26's premise** (*"it is rare for existing characters to change behaviour"*)
   **did not hold for this interval.** One commit moved a real four-character
   Skirk/Furina/Citlali/Escoffier team by −8.2 %, and every Traveler by about +27 %.
   With `any_pin=True` the run corpus would serve pin-`a36661d9` rows for those contexts
   after the re-pin. The row does carry its pin, so this is not silent, but the number is
   stale by more than the 60-iteration noise floor. **Owner question:** keep §26 as it is,
   or have a re-pin invalidate contexts whose characters appear in class-(c) commits?
3. **Traveler story buffs.** gcsim now applies +20 % ATK/HP/DEF/ER/CD, +10 % CR and +60 EM
   by default. `stat_calculator` applies neither this nor the older `skirk_story_buff`, so
   `/explain` and `/calculate` already disagree with gcsim for Travelers. **Owner question:**
   emit `true_moon_story_buff=0 skirk_story_buff=0` (the game state of a player without
   them), or model the buffs.
4. **Licence.** Candidate `7305f726f` versus tag `v2.47.2` (`caf738dc8`, which loses only
   Jade Vista). Separately, and **at the current pin already**: the served wasm ships
   without gcsim's MIT notice, and mistilteinn has no LICENSE of its own.
5. **Fixture regeneration is a reviewed diff, not a side effect** (the rule in every
   PROVENANCE). The re-pin PR must regenerate or edit, and explain: `crossval/*.json`,
   `er_sweep/ayaka_er_sweep.json` (fix its stale `3647a07a` PROVENANCE at the same time),
   `gcsim_sample/skirk_team_calc.json` (and check `verify-gcsim-recipe`'s `stale`
   expectations for it), `gcsim_character_coverage.json`, `keys.json`,
   `talent_multipliers.json`, `frontend/openapi.json`, and the citation rows in
   `CROSSVAL_gcsim.md`, `tags.py`, `recipe.ts`, `gcsim_config.py`, `rotation_compiler.py`
   and `test_swap_delay_is_never_zero.py`.
6. **`PROVENANCE.md` of `gcsim_sample`** attributes the 2026-08-31 `rotation_gated` +13 %
   move to `#2727` *"not confirmed"*. The harness above (`bis_test.sh`, a native sampler that
   reproduces the wasm exactly) can now confirm it cheaply. Optional.
7. **The Travelers' multiplier coverage gap.** `2cf702243` changed the PMC CA multipliers,
   and M.4 cannot see it because Traveler tables are hand-written in gcsim. Our nanoka parse
   is independent, so there is no action unless a Traveler CA crossval is wanted.
8. **Element `"none"`.** `verify-gcsim-recipe.mjs:96` flags `element === ''` as unlabelled.
   At the candidate a `NoElement` hit reports `"none"` and would pass that check silently.
   None of the fixtures contains one today. Consider adding `'none'` to the check.

Scratch state left behind: the binaries `gcsim-{pin,cand}.bin`, `sampler-*.bin` and
`cand.wasm`, plus the scripts `cmp_samples.py`, `bis_test.sh`, `tot.sh`, `bychar.sh`,
`snap/run.py`, `wasm_probe.mjs` and `zzsampler_main.go`, all under the scratch directory.
The three scratch worktrees were removed from `/root/gcsim` afterwards.
