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