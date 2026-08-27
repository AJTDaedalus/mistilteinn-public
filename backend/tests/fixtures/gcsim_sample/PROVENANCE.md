# gcsim calibration samples

Each `*_calc.json` holds the **`calc` events** of one `sample(cfg, seed)` run, taken in the
browser build at the pin (`docs/CROSSVAL_gcsim.md` — never restated here). Seed `12345`.

| fixture | config | hits | exercises |
|---|---|---:|---|
| `rotation_gated_calc.json` | `rotation_gated.txt` | 221 | ATK scaling, physical + cryo, a real `while 1` gated rotation |
| `rotation_gated_nostats_calc.json` | `rotation_gated_nostats.txt` | 221 | the **zero-stat calibration** the one above is predicted from |
| `noelle_redhorn_calc.json` | `noelle_redhorn.txt` | 94 | **`flat_dmg` on 83 hits** (Redhorn's DEF conversion), **`flat_atk` on 33** (Noelle's burst), `use_def` on 5 |
| `noelle_redhorn_probe_calc.json` | `noelle_redhorn_probe.txt` | 94 | the same at `def%=0.5` — the **probe** that identifies those conversions |
| `noelle_redhorn_target_calc.json` | `noelle_redhorn_target.txt` | 94 | the same at `def%=0.9 cd=0.4` — a run the recipe must **predict** |

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

## What neither covers, stated

- **Crit rate above 100 %.** Both sit under the cap, so the clamp in `effectiveCritRate` is
  gated by the spec's stubs alone.
- **Amplifying reactions.** No melt or vaporize, so `amp_mult_total` is 0 throughout and only
  the "absent means 1, not 0" case is exercised against real data.
- **HP and EM scaling.** `use_def` appears; `use_hp` and `use_em` do not.

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

## Why they are committed at all

`RESEARCH_gcsim_calibration.md` proves the decomposition is exact across these hits. That proof
is only worth having if what it was proved against is pinned — otherwise the next run silently
becomes the oracle. **fairy shipped a stale golden fixture that sat green on CI for months**,
and this is the shape of file that happens to.

`npm run gcsim:verify-recipe` replays both and regenerates both. It **exits non-zero when the
wasm is absent** rather than skipping: a skipped check means *could not check*, never *checked
and clean*.
