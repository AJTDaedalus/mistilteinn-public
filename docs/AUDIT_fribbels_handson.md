# Hands-on audit: Fribbels Honkai: Star Rail Optimizer

**Date:** 2026-08-29
**Site:** https://fribbels.github.io/hsr-optimizer/
**Data:** `references/hsr_relic_export-2026-03-31T20-03-57.json` — the owner's own export
(`source: reliquary_archiver`, `build 0.14.0`, format `version 4`; 1,712 relics, 66 characters,
328 light cones, UID 615211664).
**Screenshots:** `screenshots/fribbels/` — every filename cited below is in that directory.

---

## What this is, and what actually happened

This is the interaction-and-visual half of the Fribbels audit: what the tool feels like with a
real 1,712-relic inventory loaded, which source reading cannot show. It was driven with
Playwright over headless Chromium at a **1440×1000** viewport, matching our own screenshots.

**The import succeeded.** The file was handed to the page's own hidden `<input type=file>` on
the Import / Save tab; Fribbels parsed it (`File contains 1712 relics and 66 characters.`),
asked for confirmation, and finished with `Done!` in under half a second
(`02_import_page.png`, `03_after_upload_parsed.png`, `04_import_confirm_modal.png`,
`05_after_import.png`). Every populated screenshot below is that data.

**Pages I genuinely reached and screenshotted, with data loaded:**

| Page | Reached | Evidence |
|---|---|---|
| Home / Showcase landing | yes | `01_loaded.png`, `51_showcase.png` |
| Import / Save (Relic scanner importer tab) | yes | `02`–`05` |
| Relics — full inventory, scored, sorted, filtered | yes, in depth | `10`–`25`, `52`–`54` |
| Characters — list and detail | yes | `33`, `33b`, `34`, `34b`, `36_characters_compact.png` |
| Optimizer — form, run, cancelled results, analysis | yes | `35`–`48` |
| Benchmarks | yes, form only (did not generate) | `50_benchmarks.png` |
| Leaderboards, Calculators, Warp Planner, Settings, Get Started | **no — not opened** | — |
| Save optimizer data / Load optimizer data tabs | **no — not exercised** | — |

**Things that did not work, stated plainly:**

- **I never saw a completed optimizer search.** With this inventory and default filters the
  search is **17,693,375,600 permutations**; measured throughput was ~412k–465k/sec, and the
  app's own sidebar quoted **"10:42:43 left"**. I ran it for 137 s (`39_*` progress shots),
  and separately with constraints, and stopped. The results I do show come from pressing
  **Cancel**, which publishes the best-1,024-so-far (`46_optimizer_results_after_cancel.png`).
- **WebGPU was unavailable in this headless browser** — console logged
  `warning: No available adapters.` and the sidebar read `GPU acceleration: Disabled`. So every
  speed number here is Fribbels' **CPU** path. *Inference (labelled as such): on a real desktop
  with the GPU path enabled this would be dramatically faster; I have no measurement of it.*
- **State did not survive a browser restart in my harness.** Relaunching the same persistent
  profile showed `0 to 0 of 0` relics; `localStorage` held only `i18nextLng` and a 1,626-char
  `state` blob. *Inference: the inventory lives in memory (or IndexedDB that my profile did not
  retain) and the "Save optimizer data" tab is the intended persistence route.* I did not test
  Save/Load, so I cannot say whether a normal user loses data on refresh.
- Two interactions defeated my automation rather than the app: the per-slot main-stat
  multi-selects and the character-name search box are Mantine widgets whose visible input has no
  stable handle. I reached both by other routes (`41_mainstat_constraint_dropdown.png`,
  `12_character_selector_open.png`) — nothing is described here that I did not screenshot.

Everything below is read off the listed screenshots. Where I reason past them I write
*(inference)* inline.

---

## 1. Import

`02_import_page.png` — the Import / Save page is four tabs: **Relic scanner importer**, **Load
optimizer data**, **Save optimizer data**, **Clear optimizer data**. The importer tab is a
vertical stepper. Step 1 lists four scanner options, each with its own honesty line —
*"Accurate speed decimals, instant scan"* vs *"Inaccurate speed decimals, 5-10 minutes OCR
scan"*, and *"limited to relics from the 8 characters on the profile showcase"*. The
recommended one carries a live badge: **"Status: Updated for patch 4.5"**. Below that:
`Upload scanner json file` **or** a `Paste json file contents` box, side by side.

`03_after_upload_parsed.png` — on upload, step 2 unfolds with the parse result
(`File contains 1712 relics and 66 characters.`) and **two different imports**, each with its
own sentence of consequence:

- *"Import relics only. Updates the optimizer with the new dataset of relics and doesn't
  overwrite builds."* → **Import relics**
- *"Import relics and characters. Replaces the optimizer builds with ingame builds."* →
  a `Only import existing characters` checkbox → **Import relics & characters**

The destructive one then asks again (`04_import_confirm_modal.png`: *"Are you sure you want to
overwrite your optimizer builds with ingame builds?"*). The modal cleared in **0.4 s** and the
page said `Done!` (`05_after_import.png`).

There is also a **Live Import** block — a websocket mode where the scanner streams new and
enhanced relics in real time, with separate toggles for equipped gear and for warp resources,
and a `Disconnected ●` status dot.

---

## 2. Relics — the part we most want parity with

### Density and speed

`10_relics_tab.png`, `10b_relics_tab_full.png`. The grid renders **all 1,712 relics as one
page** — the footer reads `1 to 1712 of 1712` — on top of an ag-grid that keeps only **32 row
elements in the DOM** at a time. There is no page size, no "load more", and no render cap.

Measured on this inventory:

| Interaction | Wall time |
|---|---|
| Relics tab click → 1,712-row count painted | **0.57 s** |
| Pick a character → all 1,712 relics re-scored | **0.43–0.47 s** |
| Sort by *Selected Char Score* descending | **0.55 s** |
| Filter Part = Head (1,712 → 317 rows) | **0.26 s** |
| 20 programmatic scroll jumps through the grid | 1.86 s total |

Nothing in the relic view felt like it was waiting on anything. *(Inference: the scoring runs
synchronously over the in-memory array; I did not read their source.)*

**27 columns** (`col-id`s read off the grid): Owner · Set · ★ · + · Part · Main Stat · Main
Value · **every substat as its own column** (HP%, ATK%, DEF%, HP, ATK, DEF, SPD, Crit Rate,
Crit DMG, Effect Hit Rate, Effect RES, Break Effect) · Crit Value · **Selected Char Score ·
Selected Char Avg Potential · Selected Char Max Potential · Selected Char Reroll Avg · Selected
Char Δ Reroll Avg** · Custom Chars Avg Potential · Custom Chars Max Potential.

At 1440 px the grid **overflows horizontally** — the rightmost potential columns sit off-screen
and the whole page scrolls sideways (compare `10_relics_tab.png` with the 1640-px-wide
`14b_relics_scored_acheron_full.png`). Collapsing the left nav to icons buys back ~160 px
(`11_relics_sidebar_collapsed.png`).

### Per-relic scores: five numbers, not one

`14b_relics_scored_acheron_full.png` (Acheron selected) and
`15b_relics_sorted_score_desc_full.png` (sorted by score).

Picking a character in the top-left box fills the five *Selected Char* columns. The top relic
for Acheron reads:

```
Score 81%   Avg Potential 81%   Max Potential 81%   Reroll Avg 76%   Δ Reroll Avg −5%
```

and further down the list, rows like `41% max potential, 14% avg, Δ −7%`. The **Δ Reroll Avg**
column is the one that answers a question: it is negative on almost every good relic, i.e.
*a fresh roll of this piece would on average come out worse — keep it.* Rows where it is
positive (`+1%` on one Body piece) are the ones worth rerolling.

Every numeric cell is **heat-shaded** — substat values and potential percentages both — so
the good pieces are visible as a shape before any number is read
(`15b_relics_sorted_score_desc_full.png`).

Off-role relics score a flat `0%` in all five columns (an HP% rope for Acheron). So the score
column cannot rank *within* the junk; it only separates junk from not-junk.

### The selected-relic panel, and three ways to ask "who is this for"

Clicking a row fills a card at bottom-left (`20_top_relic_selected_buckets.png`): relic art,
`+15`, the owner's portrait, main stat, and each substat with **roll chevrons** — `›`, `››`,
`›››` beside SPD / CRIT Rate / CRIT DMG, showing how many of the four upgrades landed there —
and a graded score: **`Score 81.3 (WTF)`**. Grades seen across screenshots: `WTF`, `SS`, `S+`,
`A+`, `A`, `B+`, `B`, `C+` (`34_character_selected.png`, `47_optimizer_result_row_selected.png`).

The right two-thirds of that strip is a switchable analysis panel — **Buckets · Top 10 · EST
TBP**, with a **Maximum / Average** toggle:

- **Buckets** (`20_top_relic_selected_buckets.png`, `23_view_buckets.png`) — rows labelled
  `90%+` down to `0%+`, each row filled with the **portraits of every character in the roster**
  for whom this relic lands in that band. One glance answers "who wants this piece" across 66
  characters without reading a number. On an unscored, low-roll relic
  (`16b_relic_selected_detail_full.png`) the portraits sit in the 50–60% rows; on the best
  Acheron head they crowd 70–80%.
- **Top 10** (`21_view_top10.png`) — a 0–100 dot plot plus a ranked list,
  `1. Anaxa: 81% - 81%`, `2. Acheron: 81% - 81%`, … reading *avg – max* potential per character.
- **EST TBP** (`22_view_est_tbp.png`) — the upgrade/keep affordance:
  `Days 1,342` / `Estimated TBP 322,040` (how much stamina and how long it would take to farm a
  replacement), `Weighted Rolls 7.1`, `Reroll Potential −4.5%`, a per-substat strip of blue
  squares (one per roll) with the character's weight beside it (`× 0.75`, `× 1.00`), and a
  `Perfection 81.3%` progress bar.

### Filters

One row of popover filters above the grid: **Part · Main stats · Substats · Enhance · Grade ·
Initial Rolls · Equipped · Verified**, plus **Relic sets · Ornament sets**, a **Character**
picker, a **Customize characters** field, a `Selected character: Score` chip, and **Clear**
(`10_relics_tab.png`).

Each opens a searchable checkbox list with the stat's own icon
(`17_filter_Substats.png` — `Search…` box over ATK%, ATK, HP%, HP, DEF%, DEF, SPD, CRIT Rate,
CRIT DMG, Effect Hit Rate, Effect RES, Break Effect). Also captured: `17_filter_Part.png`,
`17_filter_Main_stats.png`, `17_filter_Enhance.png`, `17_filter_Grade.png`,
`17_filter_Equipped.png`, `17_filter_Relic_sets.png`.

When a filter is active the button changes to **`✕ Part ①`** — an inline clear plus a count
badge (`53_filter_equipped.png`, `52_relics_filtered_head.png`). `Equipped` is a two-checkbox
popover: `Equipped` / `Unequipped`.

### The scoring model is visible and editable

`25_scoring_algorithm_modal.png`. The **Scoring algorithm** button opens a per-character editor
with the character's splash art beside it:

- **left** — the legal main stats *for each slot*, as removable pills:
  `Body: CRIT Rate, CRIT DMG, ATK%, Effect Hit Rate` · `Feet: ATK%, SPD` ·
  `Planar Sphere: Lightning DMG Boost, ATK%` · `Link Rope: ATK%`
- **right** — numeric substat weights: `ATK 0.75`, `SPD 1`, `CRIT Rate 1`, `CRIT DMG 1`, and
  blank (= 0) for HP, DEF, Effect HIT, Effect RES, Break Effect
- a documentation link, **How are substat weights used?**
- `Cancel` / `Reset to default` / **`Reset all characters`** (in red) / `Save changes`

So the number in the Score column is not a black box: it ships with a per-character default,
says what the default is, and lets you disagree with it and get back.

### Empty state

`30_empty_relics.png` — with no data imported the Relics page is the full filter row and the
full 27-column header over an **empty grid reading `0 to 0 of 0`**. No message, no arrow to
Import / Save, no illustration. `31_empty_characters.png` and `32_empty_optimizer.png` are the
same: chrome with nothing in it.

---

## 3. Characters

`33_characters_tab.png` — a left rail of **banner-art rows**, one per owned character:
priority number, name, `E1 S5`, the equipped light cone as a thumbnail, and a background tinted
by element. The rail is ordered by the user's own priority list (Yao Guang #1 … Acheron #15).
Above it: a `Character menu` dropdown, a search box, and two icon strips — 7 paths and 7
elements. A `Default / Compact` density toggle sits at the bottom
(`36_characters_compact.png`).

`34_character_selected.png` — selecting one fills the right side with full splash art, the
stat block (HP 3286, ATK 4309, SPD 103.6, CRIT Rate 80.2%, CRIT DMG 161.1%, Combo DMG
1916.9K), a headline **`77.7% · B+ DPS Benchmark`**, the three teammates as portraits with
their own E/S levels, a `Default / ⚙ / Custom` team switcher, a Combat Stats block that shows
the buffed values with `↑` arrows next to the ones that changed, and the equipped light cone as
its own art card. To the right, the **six equipped relics as cards** — each with its own main
stat, substats with roll chevrons, and its own graded score
(`64.8 (SS)`, `34.1 (B)`, `30.2 (B)`).

---

## 4. Optimizer

### The form

`35_optimizer_viewport.png` (what fits on 1440×1000) versus `35b_optimizer_full.png` (the whole
page: **1725 × 2706** — about **2.7 screens** of form before any result). Three collapsible
sections: **Character options**, **Relic & stat filters**, **Teammates**, then **Character
custom stats simulation**, then the results grid.

`36b_optimizer_character_loaded_full.png`, `41_mainstat_constraint_dropdown.png` — picking the
character auto-fills, from the imported data and a preset, essentially the whole form: eidolon
`E2`, light cone `Along the Passing Shore` at `S1`, conditional character passives with their
own numeric inputs (`Crimson Knot stacks 9`, `Thunder Core stacks 3`, `Stygian Resurge hits 6`,
toggles for `Nihility teammates buff` and `E1 CR boost`), light-cone passive toggles, the
ability rotation (`1.[Ult] 2.[Ult] 3.[Skill 4.Ult]`), `Priority #15`, `Optimization target: Find
top 1024 results`, `Sorted by Combo DMG`, and the substat weight sliders (ATK / SPD / CR / CD
pushed up, the rest at zero).

The **per-slot main-stat constraint** (`41_mainstat_constraint_dropdown.png`) is a pill
multi-select per slot, pre-populated from `Recommended presets` (`CR ✕  +3` collapsed), whose
dropdown offers **only the main stats that slot can roll** — for Body: HP%, ATK%, DEF%, CR, CD,
EHR, OHB — with checkmarks on the chosen ones.

### The permutation counter and the guard

The right sidebar shows, updating live as filters change:

```
Head    100 / 100 - (100%)      Perms       17,693,375,600
Hands    94 /  94 - (100%)      Searched         7,910,000
Body     83 / 103 -  (81%)      Results              1,024
Feet     58 /  65 -  (90%)      412,022 / sec — 10:42:43 left
Sphere   17 /  67 -  (26%)
Rope     23 /  67 -  (35%)
```

Per slot: *candidates surviving the filters / candidates in inventory*, plus the percentage.
Setting Feet main stat = SPD took the total from 17.69 B to 5.19 B, and the Feet row from
58/65 to 17/65 — the cost of a constraint is visible **before** the search runs.

Pressing Start with a search that large opens a modal
(`37_optimizer_large_search_guard.png`):

> **Very large search requested** — This optimization search will take a substantial amount of
> time to finish. You may want to enable the GPU acceleration setting or limit the search to
> only certain sets and main stats, or use the Substat weight filter to reduce the number of
> permutations. — `Cancel search` / `Proceed with search`

A guard that names the three specific things that would fix it.

### Running it

`39_optimizer_progress_t4s.png` … `39_optimizer_progress_t125s.png`. On the CPU path:

| t | Searched | Results | rate |
|---|---|---|---|
| 4.9 s | 300,000 | 1,024 | 92,222 /sec |
| 13.3 s | 4,460,000 | 1,024 | 386,280 /sec |
| 37.1 s | 14,810,000 | 1,024 | 414,718 /sec |
| 70.4 s | 30,110,000 | 1,024 | 437,092 /sec |
| 125.9 s | 56,210,000 | 1,024 | 451,351 /sec |

The rolling top-1,024 is full within 5 seconds and never empties. **But the results grid stays
blank behind a spinner for the entire run** — `38b_optimizer_search_running_grid_empty_full.png`
and `40b_optimizer_search_running_t137s_full.png` both show `0 to 0 of 0` and `Page 0 of 0`
under a footer, while the sidebar says `Results 1,024`. The only thing moving is the sidebar
counter and a dashed progress bar.

Pressing **Cancel** publishes what it has, in **0.77 s** (`46_optimizer_results_after_cancel.png`):
`412,022 / sec — Finished`, `1 to 500 of 1024`, `Page 1 of 3`.

### Results and the explain panel

`46_optimizer_results_after_cancel.png` — the results grid is a **green-to-red diverging
heatmap** across every column (ΣATK, ΣDEF, ΣHP, ΣSPD, ΣCR, ΣCD, ΣEHR, ΣRES, ΣBE, ΣERR, ΣDMG,
EHP, BASIC/SKILL/ULT/BREAK/COMBO DMG), with the **current build pinned at the top in bright
green** so every candidate is read as a comparison against what you already have. 500 rows per
page.

`47_optimizer_result_row_selected.png` and the readable crop `48_results_analysis_panel.png` —
selecting a candidate opens **Optimization results analysis**:

- **current → candidate, stat by stat, with deltas and percentages**, arrows coloured by
  direction: `Combo DMG 254.4K ➤ 225.8K  11.2% ▼`, `CRIT DMG 161.1% ➤ 197.4%  36.3% ▲`,
  `Break Effect 10.3% ➤ 34.3%  24.0% ▲`
- the **six relics of the candidate build** as cards, each with its own score and grade
  (`26.0 (C+)`, `36.0 (B+)`, `45.7 (A+)`, `57.5 (S+)`, `40.6 (A)`, `56.6 (S+)`)
- **Combo Breakdown** — a horizontal bar per rotation step (`1. Ult 69K`, `2. Ult 69K`,
  `3. Skill 16K`, `4. Ult 69K`) with a `Default / Rotation` toggle
- **Combo Distribution** — a donut, `Ult 209,761 (92.9%)` vs `Skill 16,117 (7.1%)`
- **`+1x Substat → Δ% Combo DMG / Δ Combo DMG`** — a marginal-value table:
  `CR +3.02% / 6843.3`, `CD +2.06% / 4664.6`, `ATK% +1.43% / 3238.9`, `ATK +0.52% / 1190.1`,
  `HP% +2.79% / 169.1`, … i.e. *what one more roll of each stat is worth, in damage*
- a **buff ledger grouped by source** — `BUFF TOTALS` (Σ CRIT Rate 16%, Σ DMG Boost 138%, Σ RES
  PEN 20%), then `ACHERON` (18% Crit Rate boost — E1; 90% DMG Boost — Trace; 20% RES PEN — Talent),
  `SCHOLAR LOST IN ERUDITION` (8% CRIT Rate — Set), `RUTILANT ARENA`,
  `ALONG THE PASSING SHORE` (24% DMG Boost — Light Cone), then the ability scalings
  (`ULT 522% ATK Scaling`), and the enemy config (level 95, 30% Effect RES, 360 toughness,
  1 target, elemental weakness yes, weakness broken no)

That last block is a damage number explaining itself: which multiplier, from which source,
tagged with which ability it applies to.

### The standing epistemic warning

Across the Optimizer and Benchmarks pages sits a red panel that will not be mistaken for
decoration (`32_empty_optimizer.png`, `50_benchmarks.png`):

> **Do NOT use Combo DMG or DPS Score to compare teams, light cones, or eidolons!**

with four bullets explaining precisely which comparisons the number does and does not support
(*"scores across setups cannot be meaningfully compared"*, *"Builds at different speeds are
scored against fundamentally different benchmarks and can't be compared"*), and a single
`Understood, hide warning` button. The tool states the boundary of its own metric, in the place
the metric is used.

`50_benchmarks.png` — the Benchmark Generator: character + eidolon + light cone + superimposition
+ three teammates + benchmark sets + a `Benchmark basic SPD` setting, and a
`⚡ Generate benchmarks` button. I did not run it.

---

## What mistilteinn should copy, and what it should not

Our current state, for reference: a 2,370-artifact inventory with set / main-stat / equipped
filters, sorting, and a **120-row render cap**; portrait character cards; a weapons inventory
with holder portraits; a per-slot main-stat constraint in the optimizer.

### Copy — ordered by how much of a gap it closes

1. **Replace the one score with five numbers, and make one of them a decision.**
   `Score / Avg Potential / Max Potential / Reroll Avg / Δ Reroll Avg`
   (`15b_relics_sorted_score_desc_full.png`). Our inventory can sort artifacts; it cannot tell
   the owner *whether to keep one*. **Δ Reroll Avg** is the whole answer in one signed number:
   negative means a fresh roll would come out worse on average, so keep it. It is cheap to
   compute against a scoring weight vector we would have to define anyway, and it is the single
   highest-value column on the page.

2. **The Buckets view — "who is this piece for", as a picture, across the whole roster.**
   `20_top_relic_selected_buckets.png`. Rows are potential bands; each row is filled with the
   portraits of every character who lands in it. We already have portrait art for every
   character (that is what N.1 vendored), and we already compute per-character damage. This is
   a chart made of the icons we already ship, and it answers a question our artifact page
   currently cannot answer at all. Our closest equivalent is nothing.

3. **A cost-to-replace estimate — their EST TBP panel.** `22_view_est_tbp.png`:
   `Days 1,342`, `Estimated TBP 322,040`, `Perfection 81.3%`, and the per-substat roll squares
   with the weight applied to each. This turns "is this good" into "what would it cost me to do
   better", which is the actual decision. Genshin's equivalent inputs (resin per domain run,
   drop rates, 5-piece odds) are public and derivable; the *shape* — days, a perfection bar,
   and the rolls visualised as squares — is what to lift. **Caveat for our repo's citation
   rule: the farming-rate constants would need a source, exactly like a damage coefficient.**

4. **The `+1x Substat → Δ Combo DMG` marginal table.** `48_results_analysis_panel.png`. Ranking
   substats by *what one more roll is worth in damage for this build* is the most legible thing
   in the entire product, and it is a straight derivative of the damage chain we already have
   (`/api/v1/builds/{id}/explain` already walks that chain). This is a small feature on top of
   machinery that exists.

5. **Make the scoring model visible and editable, with a reset.**
   `25_scoring_algorithm_modal.png`: per-character substat weights *and* per-slot legal main
   stats, shipped with a default, with `Reset to default` and `Reset all characters`, and a link
   explaining how the weights are used. Any score we display will be argued with; this is the
   pattern that lets a user argue with it and get back.

6. **A live permutation counter with per-slot candidate counts, and a too-large guard.**
   `36b_optimizer_character_loaded_full.png`, `37_optimizer_large_search_guard.png`. Showing
   `Sphere 17 / 67 - (26%)` next to a total makes the cost of every filter legible *before* the
   run, and the guard modal names the three specific settings that would shrink it. Our own
   DESIGN records that a 59-candidate weapon comparison is ~7.7 minutes and must be a job with
   progress — this is exactly the sidebar that job wants.

7. **Filter chrome: one row, popovers, count badges, inline clear.** `53_filter_equipped.png`
   (`✕ Part ①`), `17_filter_Substats.png` (searchable checkbox list with per-stat icons). Eleven
   filter dimensions fit in two rows without a drawer or a sidebar. We have three filters and
   they already take a visible chunk of the page.

8. **Cancel publishes the best-so-far.** 0.77 s from Cancel to a full ranked table
   (`46_optimizer_results_after_cancel.png`). A long search that can be stopped early and still
   answer is a different product from one you have to wait out. This is the right default for
   our own long-running jobs.

9. **Drop the 120-row render cap.** They render 1,712 rows in one page with 32 DOM rows and
   sub-second sort and filter (`10_relics_tab.png`, and the 0.26 s Part filter). A cap is a
   workaround for a table that renders every row; the fix is virtualisation, and it removes an
   entire class of "why can't I see my artifact" question. Our inventory is 2,370 — the same
   order of magnitude.

10. **The character picker as a portrait modal.** `12_character_selector_open.png` — a 10-wide
    grid of full portraits, alphabetical, with a name search and two icon strips (element, path).
    Our portrait character cards already have the art; this is the *selection* surface built out
    of them, and it beats a dropdown at every roster size.

11. **Two imports, worded by consequence.** `03_after_upload_parsed.png` — "doesn't overwrite
    builds" vs "Replaces the optimizer builds with ingame builds", plus a re-confirm on the
    destructive one. Our GOOD import should say which one it is in the same words.

12. **The standing metric warning.** The red panel that says *do not compare across teams or
    light cones* is our `unmodelled_passives` caveat, rendered where the number is used rather
    than in an API field. That is where ours should be too.

### Do not copy

1. **The empty states.** `30_empty_relics.png` — a full 27-column header over `0 to 0 of 0`,
   with nothing pointing at Import. A first-run user sees the machinery and no way in. Ours is
   worth doing better; it costs one sentence and a link.

2. **A progress display that shows no progress.** For 137 seconds the results grid read
   `Page 0 of 0` behind a spinner while the sidebar said `Results 1,024`
   (`40b_optimizer_search_running_t137s_full.png`). The rolling top-1,024 existed the whole
   time and was not shown. If we build a long job, **stream the current best into the table**;
   Fribbels proves the data is there and the UI simply does not use it.

3. **Horizontal overflow at 1440.** The relic grid's five most valuable columns — the potential
   columns — are the ones off the right edge at our own reference width
   (`10_relics_tab.png` vs `14b_relics_scored_acheron_full.png`). Twenty-seven columns is the
   right ambition; making the user scroll sideways to reach the point of the page is not.
   *(Inference: a column-visibility control, or promoting the decision columns to the left,
   would fix it — Fribbels has neither.)*

4. **A 2.7-screen form before the button.** `35b_optimizer_full.png` is 2,706 px tall at 1440
   wide. Sections collapse, but they start open.

5. **Brute force as the strategy.** 17.69 billion permutations, ~10.7 hours on CPU, and a GPU
   backend built to make that tolerable. Our repo has already chosen otherwise (the bounded
   2+2 pair picker, #128) — the lesson to take is the *counter and the guard*, not the search.

6. **`WTF` as a grade.** `Score 81.3 (WTF)` (`20_top_relic_selected_buckets.png`) is a community
   in-joke at the top of a grade ladder — untranslatable, unexplained, and the tool ships in
   many languages.

7. **Scores that collapse to `0%` off-role.** Every relic that is not for the selected
   character's kit reads `0%` in all five columns (`14b_relics_scored_acheron_full.png`), so the
   score cannot order the bulk of the inventory. Whatever we do, a score should still
   discriminate below the threshold — or the column should say *not applicable* rather than
   *zero*.

8. **In-memory-only state.** My harness lost 1,712 relics on browser restart and the only
   persistence offered is "Save optimizer data" to a file. We have a backend and a database;
   this is a place we are already ahead and should stay ahead.

### Where we are already ahead

- **A light-cone / weapon inventory.** The Fribbels sidebar has `Showcase, Leaderboards,
  Benchmarks, Calculators, Warp Planner, Optimizer, Characters, Relics, Import / Save, Settings,
  Get Started` (`01_loaded.png`) — **there is no light cone tab**. Light cones appear only as
  a field on a character and as art on the character page (`34_character_selected.png`). Our
  weapons inventory with holder portraits has no counterpart here.
- **Server-side persistence and a real account** — see (8) above.
- **A crossvalidated damage chain with a stated tolerance.** Fribbels states the boundary of its
  metric in prose; we state ours as a number against gcsim (`docs/CROSSVAL_gcsim.md`). Both
  matter; ours is the stronger claim.
