# gcsim calibration samples

Each `*_calc.json` holds the **`calc` events** of one `sample(cfg, seed)` run, taken in the
browser build at the pin (`docs/CROSSVAL_gcsim.md` — never restated here). Seed `12345`.

| fixture | config | hits | exercises |
|---|---|---:|---|
| `rotation_gated_calc.json` | `rotation_gated.txt` | 221 | ATK scaling, physical + cryo, a real `while 1` gated rotation |
| `noelle_redhorn_calc.json` | `noelle_redhorn.txt` | 94 | **`flat_dmg` on 83 hits** (Redhorn's DEF conversion) and **`use_def` on 5** |

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

## Why only the `calc` events

A full payload is ~1.3 MB and **92 % of it is `hitlag`, `icd` and `debug` entries the parser
never reads**.

## Why they are committed at all

`RESEARCH_gcsim_calibration.md` proves the decomposition is exact across these hits. That proof
is only worth having if what it was proved against is pinned — otherwise the next run silently
becomes the oracle. **fairy shipped a stale golden fixture that sat green on CI for months**,
and this is the shape of file that happens to.

`npm run gcsim:verify-recipe` replays both and regenerates both. It **exits non-zero when the
wasm is absent** rather than skipping: a skipped check means *could not check*, never *checked
and clean*.
