# RESEARCH — where the artifact substat weights come from, and why not from our own data

**Date:** 2026-09-05. `docs/TASKS_artifact_ranking.md` A.3.
**Reproduce:** `cd backend && python -m scripts.measure_substat_frequencies --max-level 0 --fit`
**Corpus:** `references/genshin_export_2026-08-28_11-07.json` — the owner's own GOOD export,
2,370 artifacts.

---

## The question

`app/data/external/artifact_draw_model.json` carries the substat appearance weights the artifact
ranker's probability model needs, and it carries them as a **citation** — Genshin Optimizer's
`libs/gi/upopt/src/consts.ts` at a pinned commit, which itself cites a community wiki page.

This repo's standing rule is that a number must be able to say where it came from, and its worst
recorded failure is fabricated citations in curated data. A cited-but-unverified table is
uncomfortable. **We have a 2,370-piece export. Why not measure the weights instead?**

This document is the answer, and it is not "we did not get around to it".

## 1. They are not in the game data, and the near-miss is worth naming

Checked against the pinned AnimeGameData capture `5445617e33b2`:

| table | rows | fields | weight? |
|---|---:|---|---|
| `ReliquaryAffixExcelConfigData` | 350 | `id`, `propType`, `group_id`, `propValue`, `depotId` | **no** |
| `ReliquaryMainPropExcelConfigData` | 66 | `id`, `propDepotId`, `propType`, `affixName` | **no** |
| `ReliquaryExcelConfigData` | — | …, **`weight`**, … | **yes — and it is the wrong one** |

The third is the trap. It has exactly the field name you would grep for, and it is an **item-drop
weight on the artifact entry** (`weight: 1` on a necklace), not the probability a substat line is
drawn. A snapshot derivation that matched on the key would have shipped a confident wrong number
with a real citation attached to it, which is worse than no number at all.

## 2. The right test, and the wrong one that came first

The first cut compared each stat's observed share against `weight / Σweight`. **That is not the
model's prediction.** Substats are drawn *without replacement*, so a stat's marginal probability
of appearing is not proportional to its weight, and the naive comparison would flag a disagreement
even on data that fit perfectly.

The correct quantity is `P(s appears) = 1 − P(s missed in all k draws)`, enumerated exactly over
ordered draws with the denominator renormalised after each — `_marginals` in
`scripts/measure_substat_frequencies.py`, which is what GO's `substatProb` computes for the same
problem. Cells are conditioned on `(main stat, line count)`, because the main stat is out of the
pool and the line count is how many draws happened.

**The falsifiable claim is the ordering, not the values.** Inclusion probability under this scheme
is **monotone in weight** whatever the weights are. So sorting stats by observed frequency must
never put a lighter stat above a heavier one. That is testable without assuming the numbers under
test.

## 3. The measurement

5★, all slots, **level ≤ 0** — 1,726 pieces, 5,664 substat lines. This is the least-selected cut
available, and it is most of the export:

| stat | w | observed | expected | obs/exp |
|---|---:|---:|---:|---:|
| `def` | 6 | 12.39% | 14.25% | 0.87 |
| `critDMG_` | 3 | 11.55% | 7.88% | **1.46** |
| `enerRech_` | 4 | 11.48% | 9.95% | 1.15 |
| `critRate_` | 3 | 11.02% | 7.84% | **1.41** |
| `eleMas` | 4 | 10.82% | 9.56% | 1.13 |
| `hp` | 6 | 9.76% | 11.49% | 0.85 |
| `atk` | 6 | 9.22% | 11.36% | 0.81 |
| `atk_` | 4 | 8.99% | 8.89% | 1.01 |
| `hp_` | 4 | 7.45% | 9.36% | 0.80 |
| `def_` | 4 | 7.33% | 9.41% | 0.78 |

**17 weight-order inversions.** Over the whole export at any level it is 21. Per slot the shape
repeats — flower +0 (319 pieces) puts `critDMG_` at 1.46 and `def_` at 0.73; goblet +0 (353
pieces) puts `critDMG_` at **1.70** and `def_` at 0.73.

So the corpus does not agree with the published table, and the residual has an obvious shape: the
stats above expectation are the ones a player keeps a piece *for*.

## 4. The result that settles it — and it is about identifiability

The obvious next move is to fit weights to the export and use those instead. `--fit` does it, and
the result is the reason nobody should.

**It converges in 25 iterations to a maximum marginal error of 9.3e-6.** A weight table that
reproduces this export essentially exactly exists:

| stat | published | fitted |
|---|---:|---:|
| `def` | 6 | 5.02 |
| `hp` | 6 | 4.86 |
| `enerRech_` | 4 | 4.78 |
| `critDMG_` | 3 | **4.72** |
| `eleMas` | 4 | 4.67 |
| `atk` | 6 | 4.58 |
| `critRate_` | 3 | **4.48** |
| `atk_` | 4 | 4.07 |
| `hp_` | 4 | 3.08 |
| `def_` | 4 | 3.00 |

Of course it exists. The model has ten weights, free up to scale — **nine parameters**. The corpus
supplies ten marginals that sum to the line count — **nine independent observations**. A fit is
generic, and it absorbs whatever selection a kept inventory carries directly into the weights,
where it becomes invisible.

**So this corpus cannot distinguish a wrong published table from a selected sample.** That is not
a statement about which explanation is true; it is a statement that no amount of care with *this*
data can decide between them. Both hypotheses predict the same nine numbers, because the fit has
enough freedom to make them.

Fitting anyway would produce a table asserting that CRIT DMG is drawn almost as often as flat DEF.
It would carry no citation, it would be contradicted by every community source, and it would be
**wrong in exactly the direction that flatters our own inventory** — an artifact ranker whose
probability model was trained on the pieces its owner chose to keep.

## 5. What would settle it, and is not available here

- An unselected corpus: every piece a player received, including the ones destroyed. No exporter
  produces this, because the game does not retain them.
- A primary source that publishes the weight. §1 shows the pinned capture does not; a later
  version of AnimeGameData might, and that is worth re-checking on a version bump.
- A large multi-account corpus with the selection modelled explicitly. Out of proportion to what
  it buys, given that the community table is not seriously disputed.

## 6. What was decided

**The weights stay cited, in `app/data/external/`, with the caveat carried in the file itself and
surfaced by `draw_model_provenance()`.** They are a named secondary source, which this repo already
ships openly rather than pretending otherwise — `gcsim_config.ENERGY_DRIP`, five community configs
cited in place.

The consequence for the feature is small and should be stated where a user can see it: the
**distribution's shape** depends on these weights, so it is the one number the ranker reports that
does not trace back to gcsim. Everything else — the damage a projected piece produces — runs
through the recipe evaluator, which is crossvalidated. `DESIGN_artifact_ranking.md` §8.3.
