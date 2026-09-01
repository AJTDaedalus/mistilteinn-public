# BACKLOG — the optimize page

> **Code is named, not numbered.** The first draft of this file cited `optimize.ts:547` and
> `optimize.ts:930`, and the very PR that answered §1 pushed both by thirty lines — so an
> argument whose whole basis is "read against the code" pointed at the wrong code within a day.

**Owner feedback, 2026-08-30**, with a screenshot: `references/optimizer_screenshot.png`.
Recorded verbatim before it is interpreted, because the interpretation is the part that goes
wrong. Nothing here is designed yet.

> *"The optimizer seems unusual. What is the button to 'optimize', the 'search' button on the
> team select or 'search rotation' on 'Objective'. I filtered my 4p but still got a message
> `Not exact — your inventory holds 70,429,936,500 combinations, which is hours of arithmetic,
> so this searched the best 17 pieces per slot. Very likely the best five, not proven to be.
> 1,419,857 combinations scored · 794 pieces pruned losslessly, 288 by rank.` The 'Why' seems
> very AI slop, as well as a lot of the text/wording (Objective, 'best across rotation',
> 'Search Rotation', etc. Simpler terms like 'details' for details of the optimizer for that
> set, removing objective entirely, 'Optimize with rotation' vs 'Optimize for single hit', a
> single 'Optimize' button (no search), and 'Required Main Stats' should be 'Main Stats'"*

And, separately: *"Optimize main stats also need an option to select multiple."*

---

## 1. Two buttons, and neither says "optimize"

**SEARCH** sits in the team/build/hit row and **SEARCH ROTATION** in the Objective row. The
page is called Optimize and nothing on it is. The owner's answer is **one Optimize button**,
with the choice between the two modes made as a choice rather than as two buttons.

## 2. The words

| now | owner's word |
|---|---|
| Objective | *(gone)* |
| Best across rotation / Search Rotation | **Optimize with rotation** |
| the single-hit path | **Optimize for single hit** |
| Why? | **Details** |
| Required Main Stats | **Main Stats** |

## 3. Main stats: one per slot, and it should be several

Sands, Goblet and Circlet each take a single choice or "Any". A user who will take ATK% *or*
EM on the sands has to run the search twice.

## 4. The count ignores the set filter — **confirmed, and it is the same bug as §1**

The screenshot has **Finale of the Deep Galleries** selected and still reports
**70,429,936,500 combinations**. Read against the code, the cause is structural rather than
arithmetic:

- `optimize.ts`, `constrained()` — filters candidates by **main stat only**.
- `optimize.ts`, `run()` — the single-hit `search()` is handed `constrained(...)`, so every artifact
  in the inventory is in its space. `search.ts` then multiplies the per-slot buckets, which
  is where 70,429,936,500 comes from. The number is *correct for what that search did*.
- `selectedSets` feeds the **rotation** search and nothing else.

**So the two buttons do not merely differ in cost — they differ in which of the controls on the
page apply to them.**

The set picker is already inside `@if (objective() === 'rotation')`, so it appears only in the
mode that uses it. What it is *not* inside is a guard on the other button: **the top `Search`
is rendered unconditionally**, so with "Best across rotation" chosen and a 4-piece picked,
there are two buttons on screen and the top one runs the single-hit search and ignores the
whole block above it. That is the sequence in the screenshot.

So §1 and §4 are one problem and it is **§1's fix that closes both**: with a single Optimize
button there is no way to press the search that ignores the mode you chose. No kernel change is
needed for this, and the earlier note here saying "the set filter has to apply to both modes"
was wrong — in rotation mode it already applies, and in single-hit mode it is not offered.

**What is still open** is whether single-hit *should* offer it, as a filter — "rank only builds
with a 4-piece Finale". The single-hit walk (`search.ts`, the `walk` inside `search()`) has no set constraint, so that is
a kernel change with its own pruning and its own honest counting, and it is a chunk of its own.
Not needed to answer the owner's question; worth doing on its own merits.

## 5. Every result row reads the same

Ten rows of *"Flower · Plume · Sands · Goblet · Circlet"* and a bare number. The rows differ by
score and say nothing about **which pieces** differ, so the list cannot be read as a comparison
— which is what a ranked list is for. Not raised by the owner in words; visible in their
screenshot, and it may be most of what "seems unusual" is pointing at.

## 6. The score has no units

`733.7` with no label. Damage? Per what? The page should say what it ranked by.

---

## 7. The caller ranks on a recipe the calibrator told it not to — **owner decision needed**

Reported from production, with the full text this time (the `{}` fix made it readable):

> *No recipe describes no 4-piece set — the rotation did not run the same way every iteration…*
> *no 4-piece set: flatDamage carries a conversion no probe could resolve, affecting 90.3% of
> the damage.* … and then **"Exact — the best five over this inventory. 279 combinations
> scored."**

**The chain — and the version below is wrong. Corrected 2026-08-31, kept for the record.**

> ~~An unstable rotation makes the probe run a different number of hits from the baseline, so
> `resolveConversions` cannot identify what the flat terms convert from, so the recipe freezes
> them — over ~90% of the damage.~~

`resolveConversions` **throws** when the two runs differ in length:

    if (baseline.hits.length !== probe.hits.length) throw new Error('probe changed the rotation…')

So a structurally-varying rotation fails loudly rather than producing unresolved terms. The
warnings therefore did **not** come from instability, and the two problems are independent.

**What actually froze them: the probe moved one stat.** It set `def%=0.5` and nothing else, and
the matcher considers only stats the probe moved — *"a stat the probe did not move has ratio 1
and cannot be told from any other unmoved stat."* So a DEF-only probe could resolve only
DEF-derived conversions, and every ATK- or HP-derived one was **structurally unresolvable**,
which on an ATK-scaling character is most of them.

The one-stat design was defended on the grounds that the matcher cannot separate two stats that
move together. That is true of two moving by the **same factor**, and it does not follow that
only one may move. **Fixed:** the probe now moves all three by different amounts
(`atk%=0.5 hp%=0.3 def%=0.7`), at no extra gcsim cost, and a genuine ratio collision still
falls back to "unresolved" rather than to a guess.

Instability remains real and is §8's subject; it is simply not the cause of this.

**What is ours:** `calibrate.ts` says, in its own docstring, *"Stability is reported, not
enforced… **It is the caller's job not to rank on it.**"* The caller
(`recipe-optimize.service.ts`) pushes the caveat and then stores the recipe and ranks on it.
The module stated the contract and its only consumer ignores it.

**Why this is not fixed here.** Refusing to rank would leave a user with nothing where they
currently get something caveated, and which of those is better is a product call, not a defect
report. Two options:

| | |
|---|---|
| **Refuse** | Matches the module's contract and this repo's standing rule that a plausible wrong number is worse than none. Costs the user their only output on a rotation they may not be able to make stable. |
| **Caveat harder** | What is built now: `isExact` no longer claims the *scoring* is sound, and the warnings sit above the table. Keeps the output; relies on the reader. |

Done in the meantime: **"Exact" no longer means two things.** It now says *"every combination
was scored, none were pruned by rank"* and, when the recipes are shaky, *"The scoring is not."*
Exhaustive and trustworthy were one sentence, and only one of them was true.

Also fixed: the baseline calibration was labelled **"no 4-piece set"**, so the progress line
read *"Calibrating no 4-piece set"* beside a picker holding only Finale — a target nobody chose
looking like one they had. It is **"the baseline (no 4-piece bonus)"** now.

## 8. Why that rotation is unstable — **CONFIRMED by experiment**

The mechanism below was written as a hypothesis with the one experiment that would settle it.
That experiment has now been run: `cd frontend && npm run probe:energy`
(`scripts/probe-energy-stability.mjs`), against the committed `rotation_gated.txt` — Ayaka,
90 s, burst gated on `.ready` — at 40 iterations per point.

|   ER | burst mean | burst sd | |
|---:|---:|---:|---|
|   0% | 2.0250 | 0.1581 | **unstable** |
|  10% | 2.2250 | 0.4229 | **unstable** |
|  20% | 2.9000 | 0.3038 | **unstable** |
|  30% | 3.0000 | 0.0000 | stable |
|  45% | 3.0000 | 0.0000 | stable |
|  60% | 3.0000 | 0.0000 | stable |
| 100% | 3.0000 | 0.0000 | stable |

**Confirmed, with a sharp boundary at 30 %.** The hypothesis predicted stable above the
threshold and unstable below it, and that is the shape. The alternative it had to beat —
unstable at every ER, meaning the cause lies elsewhere — is ruled out.

So this is not an edge case: **it will hit any rotation whose burst is energy-marginal**, which
is most real ones. The owner's own rotation reports exactly this, and the page now names the
ability whose count varied instead of only saying that something did.

What follows from it, and what is still open:

- **Done:** the warning names the varying ability and says an ability with a varying count is
  usually short of energy. That is now a measured claim rather than a plausible one.
- ~~**Open:** the *number*.~~ **Done, and this entry was stale.** `energySweep` is passed by
  `recipe-optimize.service.ts`, `calibrate.ts` sets `meta.minimumEnergyRecharge` from it, and
  both `optimize.ts` and the service read it through `energyShortfall`. The note above
  describing both ends as dead survives in `optimize.ts` as a comment about the state it was
  written in.

  Found during the 2026-08-31 frontend audit by walking the backlog against the tree rather
  than trusting it — **an entry that reports finished work as open is the reason a reader stops
  believing the file**, which is the same argument `CLAUDE.md` makes about its own counts.

## 8a. The original hypothesis


**Read from the code, not reproduced against the owner's rotation.** Stated as a hypothesis
with its mechanism, and with the one experiment that would settle it.

`stabilityFrom` (`recipe.ts`) marks a rotation unstable when **any ability's instance count**
varies by more than 2% across iterations. `compile_rotation` gates **every** action on
`.ready` — `DESIGN_rotation.md` §3.4, deliberately: *"A gated rotation skips rather than
stalls… that is what a player does."* gcsim's energy generation carries particle RNG, so a
burst that is marginal fires in some iterations and not others, the count varies, and the
rotation is unstable **by construction**.

So two subsystems, each internally right, with an unstated conflict:

| | |
|---|---|
| the compiler | makes structure **conditional**, on purpose, so a rotation never deadlocks |
| the calibrator | requires structure to be **fixed** — *"same hit count, same abilities in the same order"* |

If this is the mechanism, it is not an edge case: it will hit any rotation whose burst is
energy-marginal, which is most real ones.

**The experiment that settles it:** calibrate the same rotation twice, once on a build with
ample ER and once below what the rotation needs. Stable in the first and unstable in the
second confirms it; unstable in both means the cause is elsewhere.

## 9. The subsystem that would have explained §8 — **WIRED**

Both ends were dead: nothing passed `calibrate` an `energySweep`, so `minimumEnergyRecharge` was
always null, and nothing read the field either.

**Now:** the calibration walks an ER ladder and the page reports the gap —

> This build has 12% Energy Recharge and the rotation needs 30% to run the same way every
> time — 18% more.

**It sweeps only when there is something to diagnose:** the rotation must already be unstable
*and* the ability whose count varied must be a burst. A steady rotation has no threshold worth
finding, and instability somewhere other than a burst is not an energy problem — sweeping either
spends gcsim runs to produce a number about nothing. Six rungs at 20 iterations, against the
100 a calibration already costs.

**A null minimum stays silent.** An unmeasured threshold is not a passed one, but warning on
every search that skipped the measurement is the cry-wolf shape `recipeIsShaky` was thresholded
to avoid. The instability warning already names the ability that moved; this adds the number
when there is one.

## 9a. The original note


`recipe-energy.ts` has **no input and no consumer**: `recipe-optimize.service.ts` never passes
`energySweep` to `calibrate`, so `minimumEnergyRecharge` is always null, and nothing reads the
field either. Both ends are dead, which is why the audit found it "wired to nothing".

§8's experiment now supplies the evidence that it is worth wiring: the threshold is real, sharp,
and the thing a user can act on. The cost is a sweep — one extra gcsim run per ER point per
calibration — against a 7.84 s baseline per run.

## 9a. The original note


`recipe-energy.ts` exists to answer exactly this, and its own docstring says why it matters:
*a build that cannot burst when the rotation says to burst **is not performing that
rotation**.*

It is dormant end to end:

| | |
|---|---|
| `CalibrationRuns.energySweep` | **only ever read** — `calibrate.ts` is the sole mention; nothing supplies one |
| `recipe.meta.minimumEnergyRecharge` | therefore always `null` |
| `energyShortfall(er, null)` | therefore always `null` |
| `RecipeOptimizeService.shortfall()` | **no callers** |

Four layers, built and tested, reachable by nobody. This is the third of these
(`CLAUDE.md` names `createGpuKernel` and `POST /sim-runs`), and like both of those it was found
by chasing something that needed it rather than by reading.

**What it would be worth.** It turns *"the rotation did not run the same way every iteration"* —
a symptom the user cannot act on — into *"this rotation needs 180% ER and this build has
140%"*, which is a thing to go and fix. That is the difference between reporting a failure and
explaining one.

**What it costs.** An ER sweep is more gcsim runs per calibration, on a page that already
spends six seconds a set. Whether that is worth paying on every calibration, only when a
rotation comes back unstable, or only on request, is a decision for the owner rather than an
implementation detail.


---

# Second brief, 2026-08-30 — the whole page

Owner, verbatim, before interpretation:

> *"Ok, the 'no 4p' baseline doesn't make any sense. The baseline should be the current build
> of the character. If they don't have a build yet, we can arbitrarily select the 'best' set and
> show it as +0%, and everything else -x%. Which brings me to another point, alongside the
> damage we need a % indicator, green for positive, red for negative, gray for the comparator
> build (current or best, depending on what you start with). Also, when clicking 'details' the
> detail pane should 'expand' from that row, not show up at the bottom. Also it would be nice
> if the 'details' tab was broken out by groups. For example, the attacks inside that rotation
> likely use attack, so showing [effective attack] = [the variables that went into effective
> attack] would be better than listing all components. Show the components, but show how they
> map up to more meaningful values. Also a lot of AI slop text still in here, the 'Why $1 scores
> what it scores' is cringeworthy. 'Not searched, because no recipe covers them' is clearly AI
> generated, and I still don't know what it means. 'What one more roll is worth' is extremely
> valuable, but again sounds like AI. This needs a lot less explanation and should be a table.
> Also, doesn't it depend on which of the sets tested are picked? Same with 'Pieces that would
> beat the winner' which sounds extremely contradictory. All of the text you've provided on this
> page needs cleaned and less AI slop like, and more thought needs given into how to present
> this data cleanly and meaningfully. Consider plots too, a plot is worth a thousand words."*

## 10. Two of those are questions, and both have a defect behind them

### "Doesn't it depend on which of the sets tested are picked?" — **yes, and the owner's fix removes the question**

> **Resolved by the owner:** *"Let's roll 'what one more roll is worth' under details then, so
> it's relevant to the set the user is looking at."*
>
> Better than labelling the dependency, because it makes the answer **scoped by construction**:
> a marginal-roll table inside one row's details is self-evidently about that row's build and
> that row's set. A caveat explaining that a page-level table silently depends on a choice made
> further up is a worse version of the same information.
>
> It folds into §12 — details expands from its row, and this is one of the things it holds. The
> name goes too: the owner calls the content *"extremely valuable"* and the title AI slop, so
> what it says stays and what it is called does not.

The mechanism, for whoever builds it:

`marginalPerRoll` is computed on `scoredRecipe()` and `winningPools()` — *the winner's* recipe
and *the winner's* five pools. The winner depends on which sets were calibrated, and the recipe
used is the one for the winner's 4-piece. So the table's numbers move when the set selection
moves, and nothing on screen says the answer is conditional on a choice made further up the
page.

Not wrong. Unlabelled.

### "Pieces that would beat the winner… sounds extremely contradictory" — **FIXED**

The scoring defect is closed. `scoreForSlot` takes an optional `recipeAfterSwap`, and
`upgrades()` uses it: a swap that would leave fewer than four of the winner's set is evaluated
on the **no-four-piece recipe** from the same calibration, which the page already held and was
not using. `current` stays on the four-piece recipe, because the build as it stands really does
have the bonus — the comparison is across two recipes because the two builds are genuinely in
two different states.

The effect is the owner's own framing, arithmetically: an off-set piece now has to pay for the
whole set bonus and still win. Most do not, so they drop out of the list by the existing
`delta > 0` filter rather than by being hidden. The ones that survive are real. Rows that spend
the free slot are marked **"costs the set bonus"** so the price is visible rather than implied.

Where no no-four-piece recipe is held, a bonus-breaking swap is **dropped** rather than scored
wrongly — there is nothing honest to score it with.

Still open from this section: the heading's *other* problem — after an **Exact** search nothing
in the searched space can beat the winner, so every row here is something the search did not
consider (an uncalibrated set, or a piece a main-stat filter removed). Worth saying plainly.

<details><summary>The original note, kept for the reasoning</summary>



> **Corrected by the owner, who was right and I was not.** The paragraph below originally said
> every cross-set row was wrongly scored. That is false, and it is false because I did not know
> the domain: **a 4-piece build has one free slot**, so a Viridescent Venerer flower beside four
> Finale pieces is a legal build that keeps the Finale bonus. Scoring it against the Finale
> recipe is then exactly right.
>
> The owner\'s framing is the one that matters: *"Any piece could be off set, but that means
> you\'ve used up your off-piece. So we do need to look at those off-set pieces, but they
> generally need to justify their existence more."* Off-set pieces belong in this list. What
> they need is the **cost of the slot** made visible, not exclusion.

**What is actually wrong is narrower, and nothing checks it.** `scoreForSlot`
(`sim/artifact-score.ts`) swaps one slot\'s stat pool and re-evaluates the recipe. It has no
notion of set membership; the set bonus is a constant baked into the recipe. So:

| the winning build | swapping a Finale slot for an off-set piece | the score |
|---|---|---|
| five Finale | leaves four Finale — bonus holds | **correct** |
| four Finale + one off-set | leaves three Finale — bonus lost | **wrong**, credits a bonus that would go |
| swapping the existing off-piece | Finale stays at four | **correct** |

`artifact-score.ts` says so itself — *"the honest answer for a piece of the same set and an
understatement for one that would complete a different set. **The caller owns that
distinction.**"* — and the caller, `upgrades()`, does not: it filters `delta > 0` and shows the
rest.

So two things were owed, and neither was "hide off-set pieces":

1. **Check the swap keeps four of the set** before claiming a delta. Where it does not, the
   number must either account for losing the bonus or say it cannot.
2. **Show what the slot costs.** An off-set piece spends the one free slot, so it competes
   against every other off-set piece in the build, not just against its own slot.

The heading is still wrong for a different reason: after an **Exact** search, nothing in the
searched space can beat the winner, so a row here is always something the search did not
consider — a piece from an uncalibrated set, or one a main-stat filter removed. That is worth
saying plainly instead of implying the ranking missed something.

</details>



## 11. The baseline should be a build, not "no 4-piece" — **DONE**

The comparator is the character's current build, scored on whichever calibrated recipe matches
the set it actually wears. Every row shows a signed percentage against it: green above, red
below, ordinary ink for level. The referent is stated once above the list, because a column of
signed numbers with no named baseline is a comparison to nothing.

**It refuses rather than guesses.** Three states return no comparator, and each is real:

| state | why not |
|---|---|
| fewer than five pieces on the build | there is no build to score |
| a worn piece was not among the searched candidates | a main-stat filter removed it; its stats are not to hand |
| it wears a 4-piece nobody calibrated | scoring it on another set's recipe credits a bonus it does not have |

The third is §10's mistake in a worse place: every row on the page is a percentage *of* this
number. When there is no comparator the page falls back to **rank 1** — the owner's own
fallback for a character with no build — and says so.

Note the two meanings of "baseline" are now separated in the interface. The calibration's
`noFourPiece` recipe is still mandatory and still used, as a *scoring* artefact; it is no
longer something a reader is shown and asked to interpret.

## 11a. The original note


The owner\'s design, recorded rather than interpreted:

- The comparator is **the character\'s current build**.
- With no build yet, pick the best set arbitrarily and make *that* the comparator.
- Every row shows a **% against the comparator**: green positive, red negative, **grey for the
  comparator itself**.

Note this is a different meaning of "baseline" from the one the code has. The calibration\'s
`no 4-piece` recipe is a *scoring* artefact — the recipe used for combinations that reach no
4-piece bonus — and it is mandatory. The owner is describing a *comparison* baseline, which the
page does not have at all. Both can exist; only one belongs in the interface.

## 12. Details expands from its row, and groups its terms — **DONE**

The pane now renders **inside the `<li>` it belongs to**, below that row. It sat under the whole
list before, so on a ten-row result the explanation for row 2 appeared a screen away from row 2
under a heading naming a rank the reader had to match up by eye.

**The rolled-up terms were already there** and this is worth recording rather than
re-implementing: `/explain` returns each quantity with a `sum_of_parts` and its `sources`, which
is exactly `effective ATK = the parts that made it`. Nothing needed changing.

Two things moved in with it:

- **§16's second half** — the winning five at full size, with the roll-value column the compact
  row cards have no room for.
- **The roll table**, at the owner's direction: *"so it's relevant to the set the user is
  looking at."* It is now computed per row, on **that row's** recipe — row 3 may field a
  different 4-piece from row 1, and answering with the winner's recipe would describe a build
  the reader is not looking at. It is a `<table>` now, as asked.

One layout bug was introduced and fixed inside this section: the `.results li` grid declared
five columns and §11's percentage made six children, which is the wrap-and-overpaint the
comment above it already warned about. The grid moved to `.result__row` (the `li` is a block
now, since it contains the pane) and declares six.

## 12a. The original note


- The pane appears at the **bottom** of the page; it should expand from the row whose Details
  was clicked.
- Its terms should **roll up**: `effective ATK = <the parts that made it>`, rather than a flat
  list of every component. Show the components, and show what they add up to.

## 13. The words — **the named three done, plus two more**

| was | is |
|---|---|
| *Why #1 scores what it scores* | **How #1 adds up** |
| *Not searched, because no recipe covers them* | **You own enough for a 4-piece of these, but they were not scored** |
| *What one more roll is worth* | **Damage per substat roll** |
| *Pieces that would beat the winner* | **Better pieces for each slot** |

The second was not a style problem: the owner said they could not interpret it, and it never
said what it meant. `uncoveredSets` is *sets you hold four slots' worth of that were never
calibrated* — the new line says that, which also makes it actionable.

The marginal-roll prose went from five lines to one, with the exclusions moved to a hover.
**The hover needed a style**: `class="note"` had no rule behind it and rendered as ordinary
text, which is an explanation nobody would know to reach for — the same failure as putting it
somewhere it cannot render at all.

Still open: **§10's scoring defect** behind "Better pieces for each slot" is a correctness bug,
not a wording one, and the rename does not touch it. The marginal table still needs to **move
under details** (owner: *"so it's relevant to the set the user is looking at"*), which waits on
§12.

## 13a. The original note


Named by the owner: *"Why #1 scores what it scores"*, *"Not searched, because no recipe covers
them"* (which they say they still cannot interpret — so it fails at its only job), and *"What
one more roll is worth"* — which they call **extremely valuable** and want as a **table with
much less prose around it**.

The instruction is broader than those three: *"All of the text you\'ve provided on this page
needs cleaned."*

## 14. Plots — **the roll table has one; the ranking does not, deliberately**

*"Consider plots too, a plot is worth a thousand words."*

**Done:** the roll table under details draws a bar per substat, scaled against the best line in
its own table. It is a table cell with a width rather than a chart library — the CSP forbids a
CDN, and a ranked comparison of eight values is exactly what a bar chart is for. The number
stays beside the bar, because the bar answers *which* and only the number answers *how much*.

**Not done, and this is a judgement rather than a backlog item left lying:** the other candidate
was damage against rank, "showing how flat or steep the top is". §11 now puts a signed
percentage against the comparator on every row, which answers that question in the place the
reader is already looking. A second rendering of the same five numbers would be decoration.
Worth revisiting if the result list ever grows past ten rows, where a shape is easier to read
than a column.

## 14a. The original note


*"Consider plots too, a plot is worth a thousand words."* Nothing on this page is a picture
today. The obvious candidates are the marginal-roll table (a bar per substat) and the ranking
itself (damage against rank, showing how flat or steep the top is) — but that is a design pass,
not a list to implement from.


## 15. No defaults for data; rotation mode as the default tool — **DONE**

Shipped on `feat/substat-bars-adopt-go-reading`. `builds[0]` and `rotations.items[0]` are gone;
the last selection is recalled through `pages/optimize/remembered.ts` and validated against the
list actually loaded, so a deleted build falls back to **nothing** rather than to `builds[0]` —
which would have reinstated the invented default one layer further from where anyone looks.
`objective` starts on `rotation`.

`channel`, `scope` and `enemyLevel` were examined and **left**: they are hit-mode configuration
rather than the user's identity, and `enemyLevel = 90` is the standard benchmark, not a guess
about this account. `channel` is already inferred from the chosen talent.


Owner, verbatim:

> *"Also while we\'re at it remove the default values, with Aino and \'melt\' filling in.
> Providing defaults is almost never going to be useful. If anything remember what the user did
> last and keep it there, but filling something ourselves is useless. Also default to the
> rotation mode, it\'s the primary upgrade we provide so keep it at the forefront."*

Two rules that look opposed and are not:

- **Never invent the user\'s data.** The page lands on Aino because she is first alphabetically,
  and on `melt` because it is first in a list — neither is a guess about this user, and a
  populated field reads as a choice somebody made. Remembering the **last** selection is the
  wanted behaviour; inventing a first one is not.
- **Do choose the tool.** `objective` should start on **rotation**, because that is the mode the
  page exists for. Picking which tool is in front is not picking the user\'s data.

Worth checking while implementing: what else fills itself in. `hitIndex`, `channel`, `scope`,
`enemyLevel` and `buildId` all have starting values, and each needs the same question asked —
is this the user\'s data, or is it which tool is in front?


## 16. Artifact cards, on the row and in the details — **rows done, details pending**

The result rows now draw a card per piece. What shipped, and what it needed first:

| built | where |
|---|---|
| `ids` filter on `GET /api/v1/artifacts` | the pieces a row won with, fetched by id |
| `shared/substat-bars` | the bars, the tooltip, and `substatReadings` |
| `shared/stat-label` | `describeStat` / `formatStat`, so a card and an inventory row cannot format the same piece differently |
| `shared/artifact-card` | the card itself, with a `compact` row size |

**The details half waits on §12**, which moves the pane so it expands from its row — putting
the large cards in today's bottom-of-page pane would have to be undone by that change.

Two things worth keeping from the build:

- **`?ids=` with nothing after it is not the same request as omitting `ids`.** The first means
  "none of them", the second means "no filter". `if ids:` in the repository would have answered
  the caller who asked for nothing with the caller's whole inventory, and no test that only ever
  passes a non-empty list can see it. Pinned in
  `tests/unit/test_artifact_id_filter_is_not_truthiness.py`, at the repository layer, because
  over HTTP the empty case is unreachable — httpx drops an empty list from the query string
  entirely, so a test written the obvious way checks the opposite of its name.
- **The cards are an enrichment, never a precondition.** A row is complete without them, so a
  failed fetch leaves them off rather than replacing a sound ranking with an error.

---

## 16a. The original note



Owner, verbatim:

> *"We also need cards for the selected artifacts when you click details, and ideally the 'card'
> of the artifact on the row. It can be a pretty small card, just the icon, level, and the 4
> stats (with substat indicators like we've built already)."*

This is the answer to §5 — *"every result row reads the same"*, ten identical lines of
`Flower · Plume · Sands · Goblet · Circlet` beside a bare number. `describePieces` returns only
the slot name, so a row says nothing about **which** artifacts won. A card per piece says it
without a sentence.

Two sizes of the same thing:

| where | what |
|---|---|
| the result row | five small cards — icon, level, four stats |
| inside details | the same five, with room for the substat indicators |

**The substat indicators already exist** — the owner says so, and the inventory pages use them.
Whatever draws them there is what these cards should reach for, in the same way a new surface
reaches for `shared/{icon,token,element,combobox}` rather than deciding again. Finding that
component and reusing it is the first task, not designing a card.

**Found, and it is not a component.** The bars are inline markup in `artifacts.html` plus
`rollBars` / `barsTitle` on `artifacts.ts` — page-local, so there is nothing to import. They
need extracting to `shared/` first, which is the same shape as `browserStore` in §15: a pattern
with no owner, about to be decided a second time.

**The data is the real blocker, and it is a backend change.** `KernelCandidate` — what
`/artifacts/inventory` publishes and what the search actually ranks — carries `id`, `slot`,
`set_id`, `stats`, `main_stat` and *nothing else*: no level, no icon, no substats, no roll
analysis. A card cannot be drawn from it.

Widening that payload is the wrong fix: it is fetched for the **whole** inventory (2,370 pieces
on the owner's account), it is ETag'd for exactly that reason, and the roll analysis is computed
per piece. The cards need at most ten rows x five pieces.

So: **fetch the winning pieces by id.** `GET /api/v1/artifacts` filters on
`slot`/`set_id`/`equipped`/`build_id`/`offset`/`limit` and has **no `ids` parameter** — adding
one is the first task of §16, ahead of any card markup.

Worth noting what this makes possible beyond legibility: with the pieces named on each row, the
difference between rank 1 and rank 4 becomes visible — which is the thing a ranked list is for,
and which "733.7 / 732.5 / 731.4" against five identical labels cannot show.

## 17. ER was weighted and never chosen — **the prefilter was the bug**

**Owner, 2026-08-31:** *"I just tried an Optimize run on this team with Furina, but no ER sands
were picked in any of the top optimizations... I'm suspecting we're not weighing ER correctly in
the optimizer."* And the target behaviour, stated the same day:

> *"Ideal optimize behavior is that it'd weight ER alongside damage stats. Obviously it doesn't
> do anything above the threshold where the character can burst on time, but if they can't, the
> DPS gain from ER should be evaluated in whether or not the reduced delay is 'worth' the cost
> of dropping dps stats for ER."*

The weighing was right and the search never saw it. `evaluateRecipe` scales by the energy
ladder; the ladder was measured; the warning named the right characters. But
`liveQuantitiesFor` — the objective `paretoFilter` prunes against — did not list
`energy_recharge`, so an ER sands had an **all-zero vector**, was dominated by everything, and
was discarded **before it was ever scored**. Nothing the ladder could have changed survived to
be ranked, and the ranking still looked complete.

That is exactly the failure that function's own docstring warns about — §10's DEF/Redhorn case
— arriving through a stat rather than through a set. **Twice now**, which is the entry worth
keeping: a lossless layer is only lossless with respect to the objective it is told, and it is
told separately from the scorer. Adding a term to `evaluateRecipe` without adding it here is a
silent, complete loss of that term.

### The second half: the ladder never reached the recipe being scored

Fixing the prefilter alone changed **nothing on screen**, which is how the rest was found.

The energy measurement — the aggregate, the free-energy counterfactual, and the ER ladder — is
taken once per search on the **set-free** target, and rightly so: the aggregate is offered to
the run corpus, a `sim_run` row is keyed by context and *not* by artifacts, so one run has to
answer for every set. But it was also *stored* on that target only, and that target is the
baseline — the recipe `unscoredLabels` exists to say nobody ranks on. Every 4-piece recipe came
back with `energySweep` and `calibratedEnergyDps` undefined, so `energyRatio` returned 1 for
every candidate and `liveQuantitiesFor` saw a flat ladder and went on pruning ER.

The measurement was correct, complete, and attached to the one recipe nothing reads.
`shareEnergyMeasurement` now stamps it onto all of them after the loop, which also covers the
cache-hit path. Sharing is sound for the same reason taking one measurement is: the ladder
varies the subject's ER on the calibration's own stats line and reads team DPS — nothing in it
depends on which set the search is walking.

**Verified on the owner's own data**, driving the real page against the recreated Skirk Freeze
team (`scripts/shoot.py`'s account, Playwright, real gcsim in the browser). The ladder that came
back is emphatically not flat:

| artifact ER | 0.20 | 0.30 | 0.45 | 0.60 | 0.80 | 1.00 |
|---|---|---|---|---|---|---|
| team DPS | 142,380 | 152,589 | 157,761 | 154,314 | 158,306 | 156,188 |
| Furina bursts | 2 | 2 | 2.8 | 2.5 | 3 | 3 |

`energyRecharge` now appears in the per-roll table, sourced from that ladder. Its delta on this
build is **0**, and that is the correct answer rather than a missing one: `dpsAt` is a step
function over six rungs, and one 6.48 % roll does not cross the next one. The owner's ruling
covers exactly this — *"obviously it doesn't do anything above the threshold"*.

**Fixed.** ER joins the live set when the ladder is not flat — above the threshold every rung
reports the same DPS, `energyRatio` is 1 for every candidate, and pruning on a quantity that
provably cannot change an order would cost every search for the benefit of none. A rung with no
measured DPS is *unmeasured*, not flat, and is skipped rather than counted as agreement.

The regression test is the readable statement of the owner's ruling: with a ladder, the winner
is **four ER pieces and one ATK** — reaching the threshold and then stopping, because the ladder
pays nothing above it. That build is unreachable for an ER-blind search, being neither the
all-ATK winner nor an all-ER one.

`ONE_ROLL` gained `energy_recharge` alongside (0.0648, depot 501 id `501234` in
`artifact_substat_values.json`): a table answering *"what is one more roll worth"* that omits
the stat the page is warning about is answering a different question. `liveQuantitiesFor` gates
that row too, so on a build already over the threshold it is correctly absent rather than
printed as a zero.

## 18. Three owner rulings on the results list — **DONE**

- **"There's no point calculating 'better pieces' that lose the 4p bonus. That's never a
  thing."** §10 made a set-breaking swap score honestly, on the no-four-piece recipe, so it had
  to pay for the bonus it removed and still win. Right arithmetic, wrong list: a recommendation
  nobody would take is noise whether or not its number is correct, and a row captioned "costs
  the set bonus" asked the reader to re-adjudicate a decision they had already made. Those
  candidates are dropped rather than priced. `noFourPiece` is still calibrated and still
  load-bearing — `recipe-search` walks it for combinations wearing no four-piece at all — it
  simply no longer scores anything on screen.
- **"Clicking 'details' again should compress the row on optimize."** It only ever opened; the
  only way to close the pane was to open a different row. Closing asks the server nothing, and
  the button says which way it goes.
- **"I don't like the color of the background of the details either."** It was
  `rgb(221 174 33 / 8%)`, wrong twice: brass is this palette's *action* accent and an opened
  disclosure is state, and a literal colour is the rule `_tokens.scss` exists to enforce. The
  row lifts to `--surface`, the pane recesses to `--bg-deep` on a `--surface-rule` border.

## 19. The energy warning named a character who cannot be short of energy — **FIXED**

**Owner:** *"Skirk has no burst energy cost, she has a unique burst effect. Something is very
wrong there."*

The warning decides who is starved by comparing burst counts against a free-energy
counterfactual — and that counterfactual moves the **whole team's** timing, so a character whose
burst spends something else still casts a different number of them. Every such difference was
being attributed to her own energy. Skirk spends Serpent's Subtlety; her catalogue row carries
`burst_energy_cost = None`, and nothing was reading it.

Now published on `RosterCharacter` and on `CalibrationConfigs` (positional against
`characters`, paired through `gcsim_keys.character_key` rather than by index), and filtered on.
An **empty** list means "the caller has not said" and filters nothing — guessing "none of them
cost energy" from "I was not told" would silently empty the warning.

**And the toll is gone from Optimize's copy of the sentence.** Its two runs are calibration
probes, where the subject wears an ER value and a set bonus and no substats; a build like that
loses far more to a missed burst than a real one, and the ratio read **47.9%** where Calculate,
same team and rotation with the actual artifacts equipped, measured **6.9%**. Both are true
about their own run; only one is about the player's build.

## 20. "Better pieces for each slot" is deleted — it could only ever be empty

**Owner, 2026-09-01:** *"The optimized sets already have a flex slot (non-set piece) so I'm not
sure what this section is meant to provide?"*

They were right, and the argument is short. The search walks every combination in a 4-piece
state and returns the best. The section then scored **single-slot swaps against that winner**.
A swap that keeps the same 4-piece state produces a combination the walk *already scored*, and
the winner beat it by definition — so its delta is necessarily ≤ 0 and the row cannot appear.

Which means the set-breaking rows §18 removed were the section's **entire content**: a swap that
changes the 4-piece state is the one thing the walk did not try. Removing them left a section
that renders nothing on an exact search. Confirmed by driving the real page against the owner's
Skirk Freeze team twice — `section.upgrades` was absent from the DOM both times, because
`upgrades()` returned an empty array.

The only case it could still speak to is a **truncated** search — the "searched the best 17
pieces per slot" path — where rank pruning discards pieces the walk never tried. That is real
information, and the page already prints it as the "not exact" notice; a second surface for the
same caveat, under a heading that does not mention truncation, is worse than none.

**Nothing failed when it was deleted**, which is its own finding: the section had no test
coverage at all. It was verified by looking at the page, twice, which is the check this repo
keeps saying it does not automate.

### What this leaves behind

- **`sim/artifact-score.ts` now has no caller.** Kept rather than deleted, with a banner saying
  so: its other half is exactly the feature `DESIGN_artifact_ranking.md` and
  `AUDIT_fribbels_parity.md` §5 ask for — *"is this piece any good?"* on the inventory page,
  with the signed delta the audit names as what makes a list decidable. If §5 is still unbuilt
  next time someone reads that banner, delete the module.
- **The baseline's justification changed and the comments now say so.** Four places explained
  that the no-four-piece recipe is calibrated *for the upgrade list*. It is now calibrated
  because it is the run the energy measurement is taken on — the aggregate, the free-energy
  counterfactual and the ER ladder that §17 hands to every other recipe. That is a better
  reason than the one it replaced.

## 21. The ladder was measuring its own noise — **FIXED**, and the shape it hid

**Owner, 2026-09-01:** *"Are we sure the denominator for DPS is really moving with ER? Its DPS
is suspiciously very close, <<1%, to the non-ER ones which tells me not much changed."*

It was moving; it could not resolve the movement. Three defects, all visible in the ladder the
owner's own run produced at `ENERGY_LADDER_RUNS = 20`:

| artifact ER | 0.20 | 0.30 | 0.45 | 0.60 | 0.80 | 1.00 |
|---|---|---|---|---|---|---|
| team DPS | 142,380 | 152,589 | 157,761 | **154,314** | 158,306 | **156,188** |
| Furina bursts | 2 | 2 | 2.8 | **2.5** | 3 | 3 |

**More ER, fewer bursts, twice.** Impossible — every burst is gated on `.ready`, so extra energy
brings a cast forward or changes nothing. The whole signal above 0.30 ER was +3.7 % and the dip
was 2.2 % of it.

1. **`dpsAt` takes a running maximum.** It invents nothing: every value it returns was measured
   at an ER the candidate can pay for. Below the whole ladder it returns the lowest rung rather
   than `null`, which used to disable ER weighting for exactly the builds shortest of it.

   **Its first stated justification was wrong and is corrected below** — see §21a. "More ER
   cannot buy less" is false; the true claim is narrower and depends on where `ENERGY_LADDER`
   stops.
2. **The ratio is taken against the same ladder.** The denominator was `calibratedEnergyDps`, a
   100-iteration aggregate, under a numerator floored onto a 20-iteration rung — so
   `energyRatio` returned **0.928 at the calibration point**, where its own docstring says 1.
   `calibratedEnergyRecharge` is read through `dpsAt` now, and the calibration's ER is itself a
   rung.
3. **`ENERGY_LADDER_RUNS` 20 → 60.** `AGGREGATE_RUNS` is 100 and CLAUDE.md records the mean
   moving 0.3 % between 25 and 100, so the aggregate was never where precision was missing.

### What the clean ladder shows

Re-measured on the same build, 2026-09-01:

| artifact ER | 0.20 | 0.30 | 0.45 | 0.60 | 0.80 | 1.00 |
|---|---|---|---|---|---|---|
| team DPS | 142,912 | 154,013 | 157,976 | 158,005 | 157,816 | 157,591 |
| Furina bursts | 2.00 | 2.00 | 2.88 | 2.83 | 3.00 | 3.00 |

Residual reversals are 0.12 % and 0.14 %. **The curve saturates at 0.45 ER** — flat within
0.3 % from there to 1.00. The calibration ran at ~0.30 (that rung reads 154,013 against the
aggregate's 153,779, the same point measured twice), so the ratio is 1.0 there and an ER sands
is worth **+2.6 %** against the 46.6 % HP% sands it displaces. On an HP scaler that is not
close, and the owner's *"<<1 %"* was the model telling the truth through a noisy instrument.

### Two findings this surfaced, both open

- **"2 of 5 bursts" overstates what ER can fix.** The free-energy counterfactual has Furina
  casting 5; the ladder says **3 is the ceiling at any ER**. The remainder is particle
  generation, not recharge. The warning therefore implies ER could buy three more bursts when
  it can buy one. The honest sentence names the ladder's ceiling, not the counterfactual's.
- **`dpsCost` measured 0.0082** on this run — 0.8 %, consistent with the ladder's 2.6 % of
  headroom. Worth keeping beside §19's note that the 47.9 % figure was a calibration-probe
  artefact.

## 22. Per-set ER failure, and the seconds it costs — **owner request, designed not built**

**Owner, 2026-09-01:** *"When ER requirements aren't met, it'd be nice to show on each set the
**individual** failure of ER, since the global 'Energy insufficient' details are for the
baseline. It'd also be nice to get the seconds delay caused by that, at both the global level
and details level."*

Correct on the diagnosis: `energyCost` is measured once, on the baseline config, where the
subject wears an ER value and a set bonus and no substats. It describes *that* build, and every
result row is a different one.

**Both are computable from runs already made — no extra gcsim work.**

- **Per row.** Each row has its own artifact-borne ER, and `burstsAt(sweep, rowEr)` already
  reads the ladder. So a row can say what the subject casts *at its own ER*, against the
  ladder's ceiling rather than against the counterfactual (see §21). The ladder varies only the
  subject's ER — teammates keep their equipped gear — so a per-row line can honestly speak
  about the optimized character and must not claim anything about the others.
- **Seconds.** `insufficient_energy` is 0 for a gated rotation, which is why the warning counts
  bursts. But gcsim reports `statistics.duration`, `rotation-stats.ts` already parses it, and
  Calculate already displays it. The team-level delay is `duration(real) − duration(free)` from
  the two aggregates the search already runs; the per-row figure needs `duration` added to
  `EnergyObservation` and a `durationAt(sweep, er)` beside `dpsAt`, read off ladder runs that
  are already happening.

The one design question is where the per-row line lives — on the row itself, or inside its
Details pane. Details is the safer default: the row is already dense, and this is a fact about
one build rather than a comparison between them.


## 21a. "More ER cannot buy less" is false — measured, and the correction

Asked by the owner, 2026-09-01: *"There's really no ER that gets to the 5 bursts? That seems
unusual."* A fair challenge, and answering it properly falsified the premise this repo had just
written into `dpsAt`.

Native gcsim, the owner's own team and rotation, 100 iterations, fixed 90-second duration —
pushed past anything the browser ladder sweeps:

| artifact ER | 0.3 | 0.6 | 1.0 | 1.5 | **2.0** | **3.0** | 5.0 | free |
|---|---|---|---|---|---|---|---|---|
| team DPS | 154,106 | 157,499 | 157,359 | 157,471 | **139,387** | 141,487 | 141,812 | 154,241 |
| Furina bursts | 2 | 2.74 | 3 | 3 | 3 | **5** | 5 | 5 |
| Skirk bursts | 3 | 3 | 3 | 3 | 3 | **2** | 2 | 4 |

**Five bursts is reachable — at ~300 % artifact ER**, which no build gets near (an ER sands is
51.8 %, plus an ER weapon and rolls tops out around 130 %). So "3 is the ceiling" is right in
practice and wrong as stated, and the owner was right to find it odd.

**And the route there costs DPS.** An 11.5 % collapse between 1.5 and 2.0 with *identical* burst
counts, and at 3.0 Furina's two extra bursts cost Skirk one of his. A `while 1` rotation runs
for a fixed duration, so a cast that becomes affordable **consumes time another character was
using**. Energy is not a free parameter of a fixed sequence, and it is not monotone in team DPS.

### What this does and does not change

The running maximum **stays**, and its reason is rewritten. It is not "monotonicity is a law";
it is: *`ENERGY_LADDER` stops at 1.0, the curve is monotone below that, and the reversals inside
it measure 0.12 % — the noise of a 60-iteration mean.* Both the docstring and
`recipe-energy.spec.ts` now carry that, including a test that asserts the **limitation** rather
than hiding it: given a ladder with a real decline, `dpsAt` flattens it. That case cannot arise
today because no such rung is swept. **Raise `ENERGY_LADDER` past ~1.5 and the running max
becomes a build scored on a peak it does not have.**

### And a third conflation in the warning

`ignore_burst_energy` frees **the whole team**, not the character being optimized: the
counterfactual gives Skirk 4 bursts and Escoffier 4, more than any ER gives them. So "Furina
casts 2 of 5" is measured against a world where nobody pays for anything, and the rotation's
timing differs for everyone in it. The same shape as §19's Skirk problem, one level up — an
honest per-character number needs a per-character counterfactual, or the ladder's own ceiling.
That is now the specification for §22's per-row line.
