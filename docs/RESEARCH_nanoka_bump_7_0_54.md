# RESEARCH — bumping the nanoka pin from 7.0.51 to 7.0.54

Status: research only. No code, fixture, DB or git state was changed. Measured 2026-09-19
against `https://static.nanoka.cc`. Downloads are in the session scratchpad
(`…/scratchpad/nanoka/`): every index at 7.0, 7.0.50–7.0.54 and **every** character, weapon,
artifact and monster detail payload at 7.0.51 and 7.0.54 (2,172 files, 0 failures, 0 404s).

## Summary

- **Upstream moved three beta builds, and none of it is new content.** Index keys are identical
  across 7.0.51 → 7.0.54 for all four entities (150 / 286 / 65 / 585). `gi.new` names exactly
  the same ids at 7.0.54 as the committed 7.0.51 manifest: characters 10000140 **Vodyanitsa**
  and 10000143 **Vesna** were already in the 7.0.51 index, as beta.
- **No schema drift.** A recursive key-level diff over all 1,086 detail pairs found **zero
  added or removed keys**. Every change is a value change. No new element, weapon type,
  rarity, stat prop or material shape; the enums and `nanoka_gi_mappings.py` are unaffected.
- **All nine committed detail fixtures are byte-identical at 7.0.54** (`capture_nanoka_fixtures
  --check --version 7.0.54`: 9 MATCH, 5 DRIFT = manifest + four indexes). Every `verify_seed`
  anchor, the crossval harness, kernel cases and the multiplier crossval read only those nine.
- **What actually changes is beta kit tuning and placeholder names**: Vesna/Vodyanitsa talent,
  passive and constellation numbers; six beta weapons lose their `Weapon: Sword`/`Catalyst`/
  `Bow` placeholder names and get real ones; Beyond the Chrysalis's refinement numbers.
- **One change to a *released* item is a planner regression if taken as-is**: weapon 11521
  **Exaiphanes Blade** (5★, not beta, owned twice in the local DB) has **all six ascension
  phases zeroed** from 7.0.52 on (`cost: 0, mats: []`). `/gi/7.0` (live) still has the real
  bill (10k–65k mora + three materials per phase). A bump would make its ascension read as free.
- **Prune risk is nil**: no id leaves any index between 7.0.51 and 7.0.54, so `_prune` deletes
  nothing and the guard cannot trip.
- **The bigger finding is retention, not drift: nanoka deletes old versions.** `hsr/4.4.x`,
  `hsr/4.4`, `gi/6.7`, `gi/6.7.54` and an old `zzz/3.2.3+…` all answer **404** today. Once GI
  7.1 goes live, 7.0.51 **and** 7.0.54 will very likely 404 too, and then `seed_db --version
  <pin>` (the prod `reseed` job) and `verify_seed --live` stop working at *any* 7.0.5x pin.
- **Recommendation: do not spend a chunk on 7.0.54 alone.** It buys beta tuning that is about
  to be superseded and a pin that is about to disappear. Either bump to the **7.1 live**
  version as soon as nanoka publishes it (Vesna/Vodyanitsa released with final numbers), or —
  if a bump is wanted now — 7.0.54 is mechanically safe *except* for Exaiphanes Blade, and the
  retention problem needs its own decision either way (§Open questions, Q1).
- The YuanShen snapshot is pinned to `OSCBWin7.0.51` for "same patch" reasons; a matching
  `OSCBWin7.0.54` commit exists (`9424e4e556bd`, 2026-09-03). A nanoka bump should move it too.

## Consumer inventory

| Consumer | What it reads | How it is regenerated / verified | Affected by 7.0.54? |
|---|---|---|---|
| `backend/tests/unit/nanoka_transport.py:27` `FIXTURE_VERSION = "7.0.51"` | drives `FixtureTransport` (all offline mapping/integration tests, crossval seed) | hand-edited | yes — edit to new pin |
| `backend/scripts/verify_seed.py:59` `FIXTURE_VERSION` | offline mode refuses a DB whose `seed_runs.version` differs; `deploy-prod.yml` `reseed` job reads it to pass `--version` | hand-edited | yes — edit |
| `backend/tests/fixtures/nanoka_gi/manifest.json` | `capture_nanoka_fixtures.committed_version()` reads `gi.latest` from it | rewritten only by `capture … --version X` | yes — drift (latest, available, other games) |
| `backend/tests/unit/test_capture_pinning.py` | asserts manifest `gi.latest` == both `FIXTURE_VERSION`s | — | passes iff all three are moved together |
| `backend/tests/integration/test_seed_db.py:55` | literal `assert run.version == "7.0.51"` | hand-edited | yes — a fourth copy of the pin |
| `backend/tests/unit/test_nanoka_gi_transport.py` | literal `7.0.51`/`7.0.50` in mocked URLs and manifest | — | no (self-contained mocks); optional tidy |
| Index fixtures `character.json`, `weapon.json`, `artifact.json`, `monster.json` | `test_genshin_enums`, `test_gcsim_character_coverage` (character `en`/`element`), `test_gcsim_keys` (artifact names), `test_kqm_weapons` (weapon/artifact **keys**), `test_traveler`, `test_roster_excludes_only_the_mannequins`, `test_weapon_symbols`, `test_unreleased_content_is_never_seeded`, `verify_seed` counts | `python -m scripts.capture_nanoka_fixtures --version X` | value drift only; keys identical. Character `en`/`element` unchanged → gcsim coverage list unchanged. Weapon names change only for the 8 beta ids |
| 9 detail fixtures under `nanoka_gi/detail/` | enum/mapping unit tests, `verify_seed` anchors (Ayaka, Pyro Traveler, Aquila, Deepwood, Ruin Guard), `tests/crossval/conftest.py` (seeds via the real importer), `scripts/gcsim/crossval_multipliers.py --fixtures`, `scripts/yuanshen/anchors.py` | same capture script | **no — all 9 byte-identical** |
| `nanoka_gi/fight_prop_vocabulary.json` | `test_genshin_enums` `StatType` assertions | `python -m scripts.harvest_nanoka_vocabulary --version X` (network, manual) | expected `_provenance` only: artifact details differ only in 15047's English 4-pc text, which carries no elemental DMG prop (inferred, not run) |
| `verify_seed` anchor "5 one-piece Prayers sets" | `artifact.json` 15009–15013 | — | unchanged |
| `backend/tests/fixtures/gcsim_character_coverage.json` | recomputed from committed `character.json` | edit on re-pin of gcsim or roster | unchanged (no character name/element change) |
| `backend/tests/fixtures/kernel/{cases,search_cases}.json`, `tests/fixtures/crossval/*` | deterministic chain output from committed fixtures | `scripts/kernel/generate_*` | no (inputs unchanged) |
| `backend/app/data/teapot/suite.json` (+ PROVENANCE, `seed_teapot.py`) | 109 suites, "the pin `verify_seed.FIXTURE_VERSION` names" | manual re-capture of `gi/{v}/suite.json` | **identical at 7.0.54**; only the PROVENANCE version line would change |
| `backend/app/data/planner/curated_rates.json`, `app/services/planner/economy.py` | curated owner numbers; material id families (comment already says "measured at 7.0.54") | hand-curated | no |
| `backend/tests/unit/test_planner_crafting.py` | 12 crafting-passive descriptions, "captured at 7.0.54" | query `ascension_passives` | no — passive text changed only for the two beta characters |
| Planner cost tables (`character_ascension_costs`, `character_talent_costs`, `weapon_ascension_costs`, `materials`) | `materials.ascensions`, `materials.talents`, weapon `materials` map, `level_exp`, `xp_requirements` | `seed_db` | shape unchanged; **one value regression: 11521** (below) |
| `backend/app/data/kqm/weapons.json` | KQM guide by nanoka id | `scripts/capture_kqm_weapons.py` (manual) | no — references none of the changed ids |
| `backend/app/data/gcsim/keys.json`, `app/services/gcsim_keys.py` | weapon keys by display name | gcsim re-pin | none of the 7 newly-named weapons is in gcsim's list → still refused, as before |
| `scripts/download_icons.py` + committed `frontend/public/icons/` (2,150 files) | basenames from the seeded DB (characters, weapons, sets, enemies, talents, suites, materials) | `python -m scripts.download_icons [--check]` | no icon basename changed for any seeded entity (only Vesna's two passive icons swapped, and passive icons are not vendored) |
| `backend/app/data/yuanshen/schema/provenance.json` | pinned `OSCBWin7.0.51` (`5445617e`), chosen to match nanoka's pin | `python -m scripts.yuanshen.build_snapshot --sha <sha> [--check]` | pairing rule says move to `OSCBWin7.0.54` `9424e4e556bd…`; snapshot drift **could not check** (not run: large download) |
| `.github/workflows/deploy-prod.yml` `reseed` job | reads `verify_seed.FIXTURE_VERSION`, runs `seed_db --version` | `gh workflow run "Deploy to prod" --ref dev -f reseed=true` | follows the constant; breaks if the pinned version 404s |
| Frontend | `api.types.ts` docstrings mention 7.0.51; `shared/kqm/kqm.ts:116` comment says beta weapons are named "Weapon: Sword"; `weapon-mark.ts` crossbow comment | `npm run codegen` only if backend schema docstrings change | comments go stale; no API change |
| `backend/tests/integration/test_catalogue_endpoints.py:322` | inserts its own `(11522, "Weapon: Sword", beta)` row | — | no (synthetic data) |

## Version diff

### Index files (keys, then per-entry values)

Counts are identical at every version 7.0.50–7.0.54: character 150, weapon 286, artifact 65,
monster 585. **No additions or removals at any step.** The live `7.0` index has 148 / 278 / 65 /
584; the difference is exactly `gi.new` (2 characters, 8 weapons, 1 monster).

| Step | Character | Weapon | Artifact | Monster |
|---|---|---|---|---|
| 7.0.51 → 7.0.52 | — | 8 changed: 11437, 11438, 11522, 14437, 14524, 15437 get real names (were `Weapon: Sword/Catalyst/Bow`); 390002/390003 get `en` "Exaiphanes Blade" (was `""`) | — | 25135202 `ko` name |
| 7.0.52 → 7.0.53 | 10000140, 10000143 `birth` (was `[1,1]`) | 11438, 11522, 14524, 15437 `desc`; 390002/3 `ko` | — | 25135202 `ja`/`ko` |
| 7.0.53 → 7.0.54 | 10000140, 10000143 `desc` | 11438 `ja`; 390002 `desc` | 15047 set text ("reaction dealt" → "reaction DMG dealt") | — |

Names at 7.0.54 for the beta weapons: 11437 New Bough, 11438 Silver Light, 11522 Beyond the
Chrysalis, 14437 Winter's Heavy Heart, 14524 Hymn of the Maelstrom, 15437 Breezeborne Refrain,
390002/390003 Exaiphanes Blade (skins; `is_weapon_skin` skips them). The local DB currently
stores six of these as `Weapon: Sword` / `Weapon: Catalyst` / `Weapon: Bow` with `is_beta = t`.

### Detail payloads, 7.0.51 → 7.0.54 (all 1,086 pairs)

| Entity | Differ | Ids | What changed |
|---|---:|---|---|
| character | 4 | 10000140 Vodyanitsa, 10000143 Vesna (beta) | talent `promote.param` values (Vesna's skill scalings ×1.12; Vodyanitsa's param[7] ~+15%), passive and constellation `param_list`, all descriptive text, `vision`/`native`/`title`, Vesna `vision_special_type_before` `""`→`"Stellar Linchpin"`, Vesna's two passive icons swapped |
| | | 10000148 Alyosha, 10000150 Odette (released 2026-08-11) | `chara_info.stories[].text` only — not imported |
| weapon | 9 | 11437, 11438, 11522, 14437, 14524, 15437 (beta) | `name` (placeholder → real), refinement `name`/`desc`; 11522 refinement `param_list` (e.g. R1 0.48→0.56, 0.28→0.36, 3→5, param[4] 0→4) |
| | | 390002, 390003 (beta skins) | `name`, `desc` |
| | | **11521 Exaiphanes Blade (released)** | `materials."1".."6"`: `cost` 10000/20000/30000/45000/55000/65000 → **0**, `mats` 3 → **0 entries**. Already so at 7.0.52 and 7.0.53; `/gi/7.0` still has the full bill |
| artifact | 1 | 15047 | 4-piece affix English `desc` wording |
| monster | 2 | 25135202 (beta — withheld, not imported) | child 25135204 `base.atk` 81.10→90.12, `base.hp` 109.725365→109.725 |
| | | 25210501 Eremite Sword-Dancer | `special_names` 507 → 508 entries — not imported |

One JSON type change: Vesna's skill `promote` params at levels 1 and 12 went `1`/`2` (int) →
`1.12`/`2.24` (float). The mapping reads these numerically; not a break.

Intermediate details (7.0.52, 7.0.53) were **not** diffed wholesale; only 11521 was checked at
each (zeroed at both).

## Schema drift

**None.** No key added or removed anywhere in the four indexes or the 1,086 detail payloads.
Consequences:

- `app/models/enums.py`: no new `element`, `weapon`/`weapon_type`, `rank`/`rarity`,
  `FIGHT_PROP_*` or talent icon family; `test_genshin_enums` should pass on re-captured indexes
  (the details it reads are byte-identical).
- `nanoka_gi_mappings.py`: every path it reads exists at 7.0.54 with the same type (bar the
  int→float above). `character_ascension_cost_rows`' six-entry assertion and
  `talent_cost_rows`' skills-vs-cost-lists length assertion cannot trip — no `materials`
  path changed on any character.
- Planner inputs (`materials.ascensions`, `materials.talents`, weapon `materials` map,
  `level_exp`, `xp_requirements`): **shape unchanged**. `level_exp` and `xp_requirements` did not
  change on any payload. No new material id appears, so `_write_materials` meets nothing the
  YuanShen snapshot lacks an icon for.
- **The one value hazard** is 11521: `weapon_ascension_cost_rows` would write six rows of
  `mora 0, items []`, and `/planner` would price ascending Exaiphanes Blade at nothing — the
  "wrong answer that looks exactly like a right one" the planner refuses elsewhere. Materials
  114093–114096 stay billed by 13436, 14437 and 15437, so no material becomes orphaned.
  Whether zero is the real 7.1 game rule (a quest weapon that no longer costs anything to
  ascend) or a beta-data artefact: **could not check**.
- No request/response schema changes → no OpenAPI or `npm run codegen` needed for the data
  itself.

## Prune risk

- **No id disappears** from any index between 7.0.51 and 7.0.54 (nor 7.0.50). A seed at 7.0.54
  over a 7.0.51 database prunes **0** rows; `PRUNE_STALE_LIMIT`/`FLOOR` are never consulted.
- The unreleased set comes from the *live* manifest's `gi.new`, not the pinned version's, and it
  is identical (2 / 8 / 0 / 1) — so beta marking (`is_beta`) and the withheld monster are
  unchanged by the bump.
- **The prune risk to watch is at 7.1, not 7.0.54.** When 7.1 goes live, `gi.new` will change;
  a seed that then uses a 7.0.5x index plus a 7.1 manifest mixes two patches. And seeding
  against `/gi/7.0` (live) instead of 7.0.5x would prune the 2 beta characters, 6 beta weapons
  and 1 monster (9 rows, all below the guard) — `builds` referencing a beta character would
  cascade. The local `seed_runs` shows this already happened once: the 2026-08-31 14:33 run is
  recorded as `7.0.51` but its totals (148 / 278 / 584) are the `7.0` index's, and it pruned
  2 characters, 6 weapons and 1 monster. Cause **could not check**.

## Recommendation

**Primary: do not bump to 7.0.54 as a standalone chunk; plan the bump to the 7.1 live build
and decide the retention question first.**

1. **Retention makes any 7.0.5x pin short-lived.** Probed today: `hsr/4.4.55`, `hsr/4.4.51`,
   `hsr/4.4`, `gi/6.7.54`, `gi/6.7` and `zzz/3.2.3+18283617` are all **404**. nanoka keeps the
   current cycle only. The repo commits 9 of ~1,086 detail payloads, so a re-seed at the pin
   needs nanoka. Inference (not checked): 7.0 went live ~2026-08-10 (YuanShen `live` branch
   `OSRELWin7.0.0`), a six-week cycle puts 7.1 around 2026-09-22, and 7.0.51 and 7.0.54 would
   then 404 together. After that the prod `reseed` job and `verify_seed --live` fail at the
   current pin, and they would fail at a 7.0.54 pin too.
2. **7.0.54's content is all beta and still moving.** Everything that differs is Vesna/Vodyanitsa
   tuning, beta weapon names/numbers, and one zeroed bill on a released weapon. The 7.1 live data
   will carry the final numbers.
3. **The beta question.** The importer follows `gi.latest` (beta) by design; the owner's
   2026-09-07 ruling keeps beta characters/weapons in the DB marked `is_beta` for the planner.
   Pinning to a *live* version (`7.1`) instead would drop beta rows (and prune any existing ones)
   unless it is paired with the next beta. That is a strategy question, not a mechanical one
   (Q2).

**If a bump is wanted now anyway, 7.0.54 is mechanically safe** — no schema drift, no prune, all
anchors and detail fixtures unchanged — with two conditions: decide what to do about 11521
(Q3), and move the YuanShen pin to `OSCBWin7.0.54` in the same chunk or record why not. The
visible gain is real weapon names in place of `Weapon: Sword` for six beta weapons.

### Command sequence (as found in the repo; do on a feature branch, never `dev`)

```bash
cd /root/mistilteinn/backend

# 0. See the drift first (writes nothing). Today: 5 DRIFT (manifest + 4 indexes), 9 MATCH.
python -m scripts.capture_nanoka_fixtures --check --version 7.0.54

# 1. Re-capture. --version is mandatory: it is the only thing that rewrites manifest.json
#    and so moves the pin (committed_version() reads it back).
python -m scripts.capture_nanoka_fixtures --version 7.0.54

# 2. Hand edits, same commit:
#    tests/unit/nanoka_transport.py      FIXTURE_VERSION = "7.0.54"
#    scripts/verify_seed.py              FIXTURE_VERSION = "7.0.54"
#    tests/integration/test_seed_db.py   assert run.version == "7.0.54"
#    tests/fixtures/nanoka_gi/PROVENANCE.md  version, date, bytes (copy from step 1's output)
#    app/data/teapot/PROVENANCE.md       version line (suite.json itself is identical at 7.0.54)
python -m pytest -q tests/unit/test_capture_pinning.py tests/unit/test_genshin_enums.py

# 3. Derived vocabulary (network). Expect a _provenance-only diff.
python -m scripts.harvest_nanoka_vocabulary --version 7.0.54

# 4. YuanShen snapshot to the matching beta build (rule in its provenance.json).
python -m scripts.yuanshen.build_snapshot --sha 9424e4e556bd80e5196be7d3c52723d3a35b30e7 --check
python -m scripts.yuanshen.build_snapshot --sha 9424e4e556bd80e5196be7d3c52723d3a35b30e7  # if accepted
#    (provenance.json's pinned_commit_sha/commit_title also need updating; check whether the
#    script writes them — not verified here)

# 5. Seed and verify (local DB lives in fairy-db-1).
python -m scripts.seed_db --dry-run --version 7.0.54
python -m scripts.seed_db --version 7.0.54          # never --force-prune; expect 0 pruned
python -m scripts.verify_seed
python -m scripts.verify_seed --live

# 6. Icons: expect nothing new.
python -m scripts.download_icons --check

# 7. Codegen only if a backend schema/docstring changed.
cd ../frontend && npm run codegen && npm run verify

# 8. The gate, on the final commit.
cd ../backend && python -m scripts.ci_local

# 9. After merge (merge deploys): reseed prod at the pin, then confirm.
gh workflow run "Deploy to prod" --ref dev -f reseed=true
gh run list --branch dev
```

## Open questions

- **Q1 — retention (blocking for any pin).** nanoka 404s superseded cycles. Options: (a) keep
  chasing upstream every cycle (the pin always expires within ~6 weeks); (b) commit or archive a
  full detail mirror at the pinned version (~1,086 files; size not measured) and give
  `seed_db` a local transport; (c) accept that reseeding at an old pin is impossible and record
  it. This is a Brain-tier decision.
- **Q2 — beta vs live.** Pin to 7.1 live (final numbers, no beta rows) or to the next 7.1.5x
  beta (keeps `is_beta` rows for the planner, per the 2026-09-07 ruling)? The manifest's
  `gi.new` is read live regardless of pin, which already couples the two.
- **Q3 — Exaiphanes Blade (11521).** Zero ascension cost from 7.0.52 on. Real 7.1 change or beta
  artefact? Could not check. If taken, the planner shows a free ascension for a weapon the owner
  holds (2 `owned_weapons` rows locally).
- **Q4 — the 2026-08-31 14:33 seed run** recorded `7.0.51` with the `7.0` live index's totals and
  pruned 9 rows. Cause could not check; worth knowing before trusting `seed_runs.version`.
- **Q5 — YuanShen drift** between `OSCBWin7.0.51` and `OSCBWin7.0.54`: not measured.
- **Q6 — 7.1 release date**: inferred, not checked.
