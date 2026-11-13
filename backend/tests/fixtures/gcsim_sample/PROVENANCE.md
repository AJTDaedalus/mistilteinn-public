# gcsim calibration samples

Each `*_calc.json` holds the **`calc` events** of one `sample(cfg, seed)` run, taken in the
browser build at the pin (`docs/CROSSVAL_gcsim.md` — never restated here). Seed `12345`.

| fixture | config | hits | exercises |
|---|---|---:|---|
| `rotation_gated_calc.json` | `rotation_gated.txt` | 245 | ATK scaling, physical + cryo, a real `while 1` gated rotation |
| `rotation_gated_nostats_calc.json` | `rotation_gated_nostats.txt` | 245 | the **zero-stat calibration** the one above is predicted from |
| `noelle_redhorn_calc.json` | `noelle_redhorn.txt` | 94 | **`flat_dmg` on 83 hits** (Redhorn's DEF conversion), **`flat_atk` on 33** (Noelle's burst), `use_def` on 5 |
| `noelle_redhorn_probe_calc.json` | `noelle_redhorn_probe.txt` | 94 | the same at `def%=0.5` — the **probe** that identifies those conversions |
| `noelle_redhorn_target_calc.json` | `noelle_redhorn_target.txt` | 94 | the same at `def%=0.9 cd=0.4` — a run the recipe must **predict** |
| `skirk_team_calc.json` | `skirk_team.txt` | 215 | **four characters**, three elements, `+params`, a `for` loop, `energy every`, a custom target, and a real conversion on 18 % of the damage |
| `xiangling_vape_calc.json` | `xiangling_vape.txt` | 86 | **vaporize**: 10 of Xiangling's 27 hits at ×1.5, teammates' ×2; `em`, `reaction_type`, `react_mult`, `react_bonus`, `avg_crit_dmg_react` |
| `xiangling_vape_em_calc.json` | `xiangling_vape_em.txt` | 86 | the same at **+250 artifact EM** — the run the EM gate predicts |

## The probe triple

Three calibrations of one rotation: at zero stats, at a probe point, and at a target the
recipe has to predict. That is what turns a frozen conversion into a measured one —
`resolveConversions` compares the first two, and the third is the check.

**`Redhorn Stonethresher`'s DEF-to-damage conversion resolves exactly**: prediction over the
hit-time hits goes from **14.87 % to 2.376e-16**.

**Noelle's burst does not, and that is correct.** It **snapshots** DEF at cast, so its flat-ATK
term moves by a factor no hit-time stat ratio equals — its ratio is constant at 1.26596 while
DEF's varies 1.23585–1.26596 across the rotation. A two-point probe cannot separate that, so
the recipe **refuses to resolve it and keeps reporting it stale**. Guessing would put a
confident wrong number in 33 hits.

## Why two

One is not enough to gate the parser. The Ayaka rotation is **entirely ATK-scaling with no
flat damage and no amplification**, so a mis-transcribed `flat_dmg` survives against it while
every number still matches. Adding Noelle + `Redhorn Stonethresher` moved that mutation from
*caught by the spec only* to *caught by the gate* — and Redhorn is the weapon this whole plan
exists to stop the optimizer getting wrong.

## The multi-character fixture

`skirk_team.txt` is a rotation the owner actually runs — Skirk, Furina, Yelan, Escoffier —
supplied to test this work against something real rather than a fixture built to pass it.

**It closed a gap this file named.** The two solo fixtures could not have caught a character
swap, an off-field hit, or three elements in one rotation. It also exercises DSL this repo had
never emitted: `+params`, a `for` loop, `energy every`, and a target with `radius`, `hp` and
`freeze_resist`.

**Its `for` loop is cut from four iterations to one.** A fixture needs *coverage*, not
*duration*: at one iteration it still carries **all 24 distinct sources** and all three
elements, at **0.64 MB** instead of 1.82 MB.

**Its stats are stripped to ER**, which is what a calibration is. Run as the owner's full build
config it reports `flatAtk`, `flatHp` and `flatDef` stale on **100 %** of hits — not a bug: a
build config carries flat artifact stats (`atk=311`, `hp=4780`), and the detection's premise is
*"at zero artifact stats a non-zero flat term means a conversion"*. Stripped to a calibration,
only the genuine one remains: **`flatDamage` on 91 hits, 18 % of the damage**.

## What none of them covers, stated

- **Crit rate above 100 %.** All sit under the cap, so the clamp in `effectiveCritRate` is
  gated by the spec's stubs alone.
- ~~**Amplifying reactions.**~~ **Closed 2026-11-13** by the `xiangling_vape` pair. Melt is
  still stub-only (`recipe-eval.spec.ts`), though it travels the same code path as vaporize.
- **HP and EM scaling.** `use_def` appears; `use_hp` and `use_em` do not. No released
  character in the owner's roster scales a gcsim hit off EM with `UseEM` — Nahida-style kits
  put EM into `FlatDmg` instead, which the probe does not yet perturb (see below).

These are gaps in the **gate**, not in the tests — `recipe.spec.ts` covers all of them with
stubs. The distinction matters: a stub proves the code does what it was written to do, and a
fixture proves gcsim agrees. Closing them needs a melt team and an HP scaler, which is a
fixture to add, not a bug to fix.

**One thing the gate structurally cannot check:** `RecipeHit.scaling` is not used by
`replayHit`, because replay reuses gcsim's own precomputed `total_scaling`. The label becomes
load-bearing in **G.4**, when a candidate's stats replace that value — so its gate belongs
there, and a surviving mutation on it here is expected rather than a hole.

## Why only the `calc` and `damage` events

A full payload is ~1.3 MB and **most of it is `hitlag`, `icd` and `debug` entries the parser
never reads**.

**Both kept, because neither is sufficient.** `calc` carries the decomposition; `damage`
carries the **element by name** and the attack tag. `calc`'s own `ele` is gcsim's internal enum
(`19`, `14`), which is meaningless outside gcsim — G.4 needs the real name to decide which of a
candidate's element bonuses reach which hit. They are emitted as a strict pair, one per damage
instance, ability matching on all 245 in the larger fixture; the parser **verifies** that
rather than assuming it.

## Regenerated at the 2026-11-13 re-pin to v2.50.0 — and the Noelle triple moved

`caf738dc` → `b107b5dc` (76 Go commits). All six were regenerated, because every one
changed bytes, and **the hit count of every fixture is unchanged**:

| fixture | hits | total damage | why |
|---|---|---|---|
| `noelle_redhorn` | 94 | 159,672.10 → **159,646.23** (−0.016 %) | three `Normal 1` hits each −1.151 % |
| `noelle_redhorn_probe` | 94 | 185,407.61 → **185,381.73** (−0.014 %) | the same three hits |
| `noelle_redhorn_target` | 94 | 209,877.63 → **209,851.76** (−0.012 %) | the same three hits |
| `skirk_team` | 215 | identical | one damage event lands 5 frames earlier (51 → 46) |
| `rotation_gated`, `_nostats` | 245 | identical | none in `calc`/`damage` |

**The three Noelle hits carry one fewer Husk of Opulent Dreams stack**: `def_per` 1.12 → 1.06
(6 % a stack) at frames 2548, 3827 and 5106, and every other term follows from it.
`verify-gcsim-recipe` caught it as a 1.164e-2 drift. **Bisected, not guessed**, with a native
sampler that reproduces the wasm's `sample()` exactly: `3f528e2c7` *"Fix CharTasks duration
when added during hitlag (#3115)"* — overlapping hitlag now takes the **max** instead of the
sum, and character tasks are extended by hitlag the way mods are. The same commit moves the
Skirk frame. It touches every character with hitlag, so it is an engine change, not a kit fix.

**Everything else that changed is formatting.** gcsim `c3152ad1f` prints stat values to six
decimals (`def%: 0.30` → `def%: 0.3`, `atk: 1951.66` → `atk: 1951.65665`), which rewrites the
mod strings inside `damage` events and the `final_stats` of `snapshot` events. Nothing here
parses those strings. `rotation_gated*` are the full sample payload, not `calc`+`damage` only,
so they also pick up v2.47.2's never-captured `particle_element` and the new log fields.

**The regeneration reproduces the committed bytes at the old pin**: driving the v2.47.2 wasm
through the same script rewrites `noelle_redhorn*` and `skirk_team` byte for byte (the
`rotation_gated*` pair were last captured before v2.47.2, and match it in every `calc` and
`damage` event). So the diff here is gcsim's, not the capture's.

## Regenerated at the 2026-09-19 re-pin to v2.47.2 — and one case moved

`a36661d9` → `caf738dc` (49 Go commits). Five of the six came back byte-identical.
`skirk_team_calc.json` did not:

| | |
|---|---|
| hits | 219 → **215** |
| total damage | 1,338,594.8 → **1,296,751.5** (−3.13 %) |

Every missing hit is a **tick of a timed summon** — one Frosty Parfait and three Furina Salon
Members — and no other ability changed. The cause is `60894d7cb` *"Add checking animation
length in tests"*, which corrected the frame tables for about 70 characters: the rotation
takes marginally longer, so each summon expires a tick earlier relative to the actions after
it. The re-pin research bisected this to that commit rather than guessing.

**This is what DECISIONS §26 rests on**, and it is now known to be weaker than when it was
written: an ordinary upstream fix moved a real team's damage by 3 %, and a vendored
Skirk/Furina/Citlali/Escoffier config by 8.2 %. The owner's ruling (2026-09-19) is that the
run corpus still serves rows from older pins; this paragraph is the measurement behind that
being a choice rather than an oversight.

## Regenerated at the 2026-08-31 re-pin — and one case moved

`3647a07a` → `a36661d9` (15 upstream commits). Four of the six recordings came back
**byte-identical**. Two did not:

| fixture | hits | damage |
|---|---|---|
| `rotation_gated_calc.json` | 221 → **245** | +13.43 % |
| `rotation_gated_nostats_calc.json` | 221 → **245** | +13.42 % |

The whole difference is `physical/1`: 172 → 196 normal-attack hits. No other element or
attack tag moved, and `noelle_redhorn*` and `skirk_team` are unchanged in every field.

**What this is not.** It is not drift on our side. The crossval oracle regenerated at the same
pin differs only in `sim_version`, and every replay in `verify-gcsim-recipe` still matches to
~1e-16. The decomposition transcribes gcsim exactly; gcsim's own output for this one rotation
changed.

**What it probably is, and the honest limit of that claim.** Of the fifteen commits, none touch
Ayaka or the frame tables. The plausible candidate is `Make ICD per Char per Tag per Group
(#2727)`, which re-keys internal cooldowns in `pkg/target/icd.go`. **This was not confirmed** —
attributing it would need the old wasm rebuilt and a bisect, which was not done. Recorded as an
open question rather than asserted, because a 13 % move in a golden fixture with a guessed cause
is exactly the thing that later gets cited as settled.

## Why they are committed at all

`RESEARCH_gcsim_calibration.md` proves the decomposition is exact across these hits. That proof
is only worth having if what it was proved against is pinned — otherwise the next run silently
becomes the oracle. **fairy shipped a stale golden fixture that sat green on CI for months**,
and this is the shape of file that happens to.

`npm run gcsim:verify-recipe` replays both and regenerates both. It **exits non-zero when the
wasm is absent** rather than skipping: a skipped check means *could not check*, never *checked
and clean*.

## The vaporize pair, and the EM gate (2026-11-13)

`xiangling_vape.txt` is the National core — Xiangling, Xingqiu, Bennett, Yelan — calibrated as a
calibration is (`er=0.3`, nothing else), and `xiangling_vape_em.txt` is the same at `em=250`.
They exist to gate the fix the owner approved on 2026-11-13: a gcsim recipe used to freeze the
amplifying multiplier at the calibration's EM, so **artifact EM was worth nothing** to a
vaporize or melt build. `verify-gcsim-recipe` predicts the second run from the first:

| | gcsim | recipe |
|---|---:|---:|
| gain from +250 EM | 23,461.20 | 23,461.20 (1.1e-7) |
| before the fix | — | −0.0017 |

The tolerance is **1e-6**, because the multiplier goes through `damage.ts`, which is f32 by
design (`docs/CROSSVAL_gcsim.md`). Planted defects it catches: a parser that stops naming the
reaction fails the price check (predicted gain 0.00, Pyronado 24 % out), and one that reads
`avg_crit_dmg` instead of `avg_crit_dmg_react` fails replay at 1.000e+0.

**Bennett's burst is reported stale in `flatAtk`**, correctly: it is computed from *Bennett's*
base ATK and lands in Xiangling's flat ATK, so no probe of her stats can resolve it.

**Not covered: EM converted into flat damage** (Nahida's Tri-Karma is `ATK × a + EM × b`, the
second part written as `FlatDmg`). The probe moves `atk%`, `hp%` and `def%` only, so such a
term stays frozen and is reported stale. Widening the probe to EM is a backend schema change
(`probe_deltas`), left as a follow-up rather than folded into this fix.
