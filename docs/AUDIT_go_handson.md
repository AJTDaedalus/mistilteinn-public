# Hands-on audit: Genshin Optimizer's Artifact Upgrader

**Date:** 2026-09-05
**Site:** https://frzyc.github.io/genshin-optimizer/ — **version 10.38.1**, read off the footer.
**Data:** `references/genshin_export_2026-08-28_11-07.json` — the owner's own GOOD export
(2,370 artifacts, 87 characters, 339 weapons after GO's own merge).
**Screenshots:** `screenshots/go/` — every filename below is in that directory, which is
gitignored, as `screenshots/fribbels/` already is.
**Reproduce:** `cd backend && python -m scripts.audit_genshin_optimizer`. That script is
committed and was run end to end to produce the shots cited here; it is not a description of
what was done by hand.
**Task:** `docs/TASKS_artifact_ranking.md` A.1.

---

## Why this exists

`docs/RESEARCH_genshin_optimizer_scoring.md` documents GO's upgrade-probability model from its
source and is careful to say what it could not do:

> *"I did **not** run GO or view its UI. Statements about what the user sees are read off the JSX
> in `UpgradeOptChartCard.tsx` and the English locale strings, which is strong evidence but is
> not the same as having looked at the page."*

We are copying that display (OQ-A6). This repo's most expensive lesson is that a green suite is
blind to what a page renders — icons that 404'd into an SPA fallback for months, a badge drawn
dark-on-dark by an undefined custom property, a `<select>` that had always shown its first
option. **A chart nobody has looked at is the same bet.** So this looks.

## What actually happened

**The import succeeded.** Upload on the Database 1 card, the export handed to the hidden file
input, `Artifacts: 2370` / `Merged Total: 0 -> 2370` / `Weapons: 320` in the parse summary
(`03_upload_parsed.png`), then **Update Database** → `Characters: 87, Artifacts: 2370,
Weapons: 339` (`04_after_import.png`). Under a minute.

**Pages reached, with data loaded:**

| Page | Reached | Evidence |
|---|---|---|
| Landing | yes | `01_landing.png` |
| Settings / Database | yes | `02_setting.png`, `03_upload_parsed.png`, `04_after_import.png` |
| Artifacts inventory | yes, briefly | `05_artifacts.png` |
| Characters | yes | `06_characters.png` |
| Teams, team creation, character picker | yes | `07`–`11` |
| Character display, all four tabs visible | yes | `12`, `13_furina_tabs.png` |
| **Artifact Upgrader**, before and after a target | **yes, in depth** | `14`, `14b`, `15`, `16`, `16b` |
| Optimize (the five-piece search) | **no — not run** | — |
| Tools, Scanner, Archive, Doc | **no — not opened** | — |

**Things worth stating plainly:**

- **WebGPU was unavailable** in this headless browser — the console logs `No available adapters.`
  repeatedly. Every timing impression below is the CPU path. *(Inference, labelled: a real
  desktop would be faster; I have no measurement of it.)*
- **I did not run GO's main optimizer**, so nothing here compares the Upgrader's numbers against
  a full five-piece search. That comparison is exactly OQ-A5's subject and it is A.10's job, not
  this document's.
- **Two things made the page undrivable until they were handled**, and both are in the script's
  docstring because the next person will hit them: the *Upload* control mounts a hidden
  `input[type=file]` rather than opening a file chooser (`expect_file_chooser` waits forever),
  and an `adsbygoogle` iframe sits on top of *Select an Optimization Target* — Playwright retried
  that click 56 times before timing out.

---

## 1. The finding that matters most, and it is one sentence of GO's own UI

Printed in an info panel at the top of the Artifact Upgrader, above the results
(`14b_upopt_no_target_full.png`, `16b_upopt_computed_full.png`):

> **"The Artifact Upgrader identifies artifacts with high potential to boost the Optimization
> Target's value, guiding you to artifacts worth leveling up. As it only swaps one artifact at a
> time, for the best overall build across all artifacts, use the main artifact optimizer."**

`DESIGN_artifact_ranking.md` §8.2 argued from source-reading that neither Fribbels nor GO offers
the pinned re-search issue #291 asks for. **GO says so itself, on the page, in the product.** It
knows the one-at-a-time swap understates a piece whose value depends on the rest of the build,
and its answer is to send the user to a different tool.

That is the strongest available support for OQ-A5's shape — a fast column that triages and a
deliberate re-search that settles — and it is also a warning about the seam: GO has the same two
tools and no bridge between them, so a user who wants "the best build containing this piece"
must leave the ranker, set up a search, and remember why. **The bridge is the part worth building
that neither reference has.**

## 2. The chart, element by element

`16_upopt_computed.png`. One card per artifact, the chart occupying the right two-thirds:

- **x-axis:** *Relative Increase to Target*, −15% to +5%.
- **y-axis:** *Probability*, 0%–7% (per-card scale; a second card reads 0%–8%, a third 0%–6% —
  the axis is fitted, not shared).
- **Three series, named in a legend above the plot:** *Current Target Value* — a red dashed
  vertical; *Average Increase* — a green dashed vertical; *Exact Distribution* — an orange step
  histogram.
- **The mass to the right of the red line is filled.** That shaded region *is* the probability of
  an upgrade, drawn rather than only stated. It is the single best idea on the page: the number
  and the picture are the same object, so a reader cannot take one and misread the other.
- **Two headline numbers, right-aligned in the card header:** `Prob. upgrade: 31.8%` and
  `Average increase: +1.4%`.

**The distribution is visibly multi-modal** — three or four humps between −10% and 0% — which is
the roll-count structure showing through, and is an argument for drawing it at all. A single
"average +1.4%" hides that the same piece has a fat lobe at −5%.

**`Prob. upgrade` is #291's sentence, almost verbatim** — *"the probability an artifact, at max
level, would be an upgrade"*. GO already computes it. What GO does not do is the second half of
that sentence, per §1.

## 3. The list, and how it is ordered

`Showing 5 out of 130 Artifacts`, paginated `1 2 3 4 5 … 26`. Read down the cards, the
probabilities are **31.8%, 30.4%, 24.7%, 3.2%, 1.9%** — sorted by probability of upgrade,
descending, with no visible sort control. There is no score column and no table: the sort *is*
the ranking, and each row carries its own chart.

Note **130 of 2,370**. The list is the artifacts that survived the filters, not the inventory.

## 4. What has to be configured before a number appears

Before an optimization target is chosen the page reads *"It looks like there aren't any artifacts
available for upgrading that could enhance your setup. Your artifact filters might be too
restrictive."* (`14b_upopt_no_target_full.png`). **That is not an empty inventory and it looks
exactly like one** — a failure mode worth avoiding by name in A.7.

The target is picked from a **Target Selector** modal (`15_target_modal.png`) laid out by source:
*Basic Stats* (HP, ATK, DEF, EM, ER, Crit Rate, Crit DMG, Healing Bonus, Hydro DMG Bonus…),
*Transformative Reactions*, and one panel per talent — `Salon Solitaire · Ele. Skill` listing
*Ousia Bubble DMG*, *Gentilhomme Usher DMG*, *Surintendante Chevalmarin DMG*… This audit used
**Ousia Bubble DMG**.

Above the results: a `Non-CRIT Hit DMG / Avg. DMG / CRIT Hit DMG` toggle and a
`No Reactions / Vaporize` toggle — so the objective is explicitly *which* damage number, not a
vague "damage".

The rest of the configuration surface (`14_upopt_no_target.png`):

| control | what it does |
|---|---|
| **Artifact Upgrader Level Filter** | a two-handle range slider, `0`–`19`, badge `1960` | 
| per-slot counts | `355/430 · 383/462 · 461/547 · 392/472 · 369/459` — eligible/total per slot |
| **Artifact Set Configuration** | 2-Set `59 Allowed`, 4-Set `59 Allowed`, 3-Rainbow, 5-Rainbow |
| **Minimum Build Constraints** | *Select a Build Constraint Target* |
| **Reshape** | badge `410`, "Number of rolls into the guaranteed substats: 2 / 3 / 4 rolls" |
| **Define** | "Substats to consider for defining", pills for all ten substats |

**The level filter defaulting to 0–19 is the whole point of the feature** and worth copying: the
tool is for pieces you have *not* levelled. A +20 piece has no potential left to model.

## 5. The artifact card

Left third of each row (`16b_upopt_computed_full.png`):

```
+0   Troupe's Dawnlight      Flower of Life
     HP  717   ★★★★★
     CRIT DMG +7.8%   ▍100%
     DEF      +19     ▍ 80%
     CRIT Rate+3.9%   ▍100%
     HP       +4.1%   ▍ 70%
     Current Roll Value  350%
     Max. Roll Value     850%
     Wanderer's Troupe        0 Builds
     Inventory
```

Each substat carries a **coloured bar and an explicit percentage — 70 / 80 / 90 / 100** — which
is the roll's tier, matching `getUniformSubstatValues`'s four quality tiers exactly. Where our
inventory card draws roll *bars*, GO prints the tier of the most recent roll as a number.

**`Current Roll Value` against `Max. Roll Value`** (350% vs 850%) is the compact "how much of this
piece is already spent" figure, and it is a *pair*, never a ratio collapsed to one number.

The footer says **who holds it** — `Inventory`, or a portrait and name (`Noelle` on one card).
`AUDIT_fribbels_parity.md` §2 still lists *equipped-by-whom* as missing from our page; here it is,
on the smallest card in the product.

## 6. What to copy, and what not to

**Copy:**

1. **The shaded region.** Probability of upgrade drawn as the area right of the current value,
   with the number beside it. One object, two readings.
2. **Two headline numbers, never one grade.** `Prob. upgrade` and `Average increase` answer
   different questions and neither substitutes.
3. **The level filter defaulting to un-maxed pieces.**
4. **An explicit objective toggle** — Avg / CRIT / Non-CRIT, reactions on or off. Ours is a
   rotation rather than one hit, which is stronger, but the principle is that the user can see
   what is being maximised.
5. **Naming the tool's own limitation in the tool.** §1's banner is the most honest sentence on
   the page and it costs two lines.

**Do not copy:**

1. **A per-card fitted y-axis.** Three cards on one screen with 7%, 8% and 6% axes are not
   visually comparable, and the whole point of a sorted list is comparison.
2. **The empty state that reads as an empty inventory.** *"There aren't any artifacts
   available"* when the real cause is *no target selected yet* is a wrong diagnosis shown to the
   user; A.7 should say which of the two it is.
3. **A ranked list with no visible sort control.** The order is a strong claim and nothing on
   screen says what it is.

## 7. What this changes in the plan

- **§8.2's claim is now evidenced rather than inferred** — GO states the one-at-a-time limit in
  its own UI. `DESIGN_artifact_ranking.md` is updated to cite this document rather than reason
  toward it.
- **A.15 has a specification instead of a guess**: three series, a shaded upgrade region, two
  headline numbers, a *shared* y-axis, and an axis in relative increase rather than absolute
  damage.
- **A.14's verification gains a second check.** GO's `Average increase` is the mean of the same
  distribution it draws, displayed beside it — which is precisely the property A.14 requires of
  our *average* and our distribution's mean. Their display makes a disagreement visible; ours
  should too.
- **Nothing here changes the probability model.** `RESEARCH_genshin_optimizer_scoring.md` §2
  remains the source for that, and this audit did not read code.
