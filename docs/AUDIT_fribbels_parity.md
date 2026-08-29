# AUDIT: mistilteinn against Fribbels HSR

**Status: in progress.** Owner request (2026-08-29): *"an audit of fribbels for HSR to ensure
we have feature and navigation/visual quality parity. It is the highest reviewed HSR tool like
ours, and something Genshin doesn't have. Use a screenshot tool and my GOOD to play with pages,
especially how you view characters and optimize/rank relics."*

This file is the **mistilteinn side** of the diff — what our pages actually do, observed by
walking them with `python -m scripts.shoot` against the owner's real 2,370-artifact export on
the service account. `docs/RESEARCH_fribbels_hsr.md` is the Fribbels side. Keeping them apart
matters: one is measured here and one is researched elsewhere, and a single document would let
an inference about Fribbels sit beside a measurement of ours in the same voice.

**Every finding below was seen in a screenshot.** None of them failed a test, and the suites
were green — 1,419 backend and 432 frontend — through all of it.

**§3 has been corrected since this was first merged**, and the correction is left visible rather
than edited away: seeing a page in one state and describing it as the page is the exact error
this document exists to catch, and it is worth one worked example of getting it wrong.

---

## 1. The finding that dominates the others: nothing is virtualised

`/artifacts` renders **all 2,370 pieces at once**. There is no pagination, no windowing, and
no lazy list. The full-page screenshot is **313 megapixels** — Pillow refuses to open it
without raising its decompression-bomb limit, which is a fair summary of the problem.

It is not merely slow to shoot. Every card carries five substat rows, a roll-value bar per
substat and an icon, so this is on the order of **30,000 DOM nodes** built on one paint. The
page does render, and on a fast desktop it is survivable, which is exactly why it has
survived.

**Everything else in this audit is smaller than this.** A tool whose whole subject is a large
inventory has to be able to hold a large inventory.

## 2. `/artifacts` — what a user cannot do

Present: a slot filter (All / Flower / Plume / Sands / Goblet / Circlet), a piece count, and
the GO-style card with per-substat roll bars and a roll-value ratio.

Absent, and each is ordinary in this class of tool:

| missing | why it matters at 2,370 pieces |
|---|---|
| **sorting** — by roll value, level, set, rarity | the only order is whatever the API returns |
| **set filter** | finding your Emblem pieces means scrolling |
| **main-stat filter** | the single most common way to narrow a slot |
| **substat filter** ("has CRIT DMG") | the second most common |
| **level / rarity filter** | no way to hide the +0 4-stars |
| **equipped-by** | cards say *"Equipped"* but not by whom — the one fact that makes it actionable |
| **multi-select / bulk delete** | a scanner import brings in junk that stays forever |
| **a per-piece score** | see §5; this is the owner's task #3 |

**Closed since this was written** (#144): sorting by roll value / level / rarity / set / slot,
and set, main-stat and equipped filters. The render cap is the same change — the page held all
2,370 in the DOM, and now holds 120 with an explicit "show more". Still open from that table:
multi-select and bulk delete, equipped-*by-whom*, and the per-piece score.

## 3. `/optimize` — the controls exist and are invisible

**Corrected 2026-08-29, after this section was first written and merged.** The first version
said `/optimize` had no set filter, no 2-piece/4-piece constraint and no cost estimate. **All
three exist.** That was a screenshot of the default objective read as a screenshot of the page,
and it is the same mistake this audit warns about everywhere else — an absence taken for a
fact without checking.

Switch the objective to *"Best over a rotation"* and the page grows: a **set filter over 35
sets**, each annotated with how many pieces the user owns of it; All / None; a **live
calibration count**; a cost hint (*"Roughly six seconds each"*); a rotation picker; and a
collapsible **2+2 pair** picker. That is more search shaping than the first draft credited, and
the cost estimate the draft asked for is already there.

**The real finding is better than the wrong one.** A user landing on `/optimize` sees Build,
Hit, Element, Scope, Enemy level, Objective and a button — and concludes the tool cannot
constrain a search. I concluded exactly that, with the source open. Everything that makes this
page powerful is behind a dropdown whose default hides it.

What was genuinely missing, and what is left:

- ~~**no main-stat constraint per slot**~~ — **built** (#146). One select per slot, offering
  only the stats the user owns, applied where `pieces` is defined so the set list and the
  calibrations see the same inventory, and reporting an impossible constraint *before* the
  search rather than returning nothing.
- **no minimum-stat constraint** — an ER floor is how every real Genshin build is chosen.
- **no way to pin a piece** the user wants kept.

**Both remaining ones exist in `artifact_optimizer.OptimizerConstraints` already** —
`min_stats` and `locked_slots`, with tests. That module is deliberately *not* the app's search
path: `app/services/__init__.py` records it as the oracle the browser kernel is verified
against. So these are not new algorithms; they are the same rules restated in
`sim/recipe-search.ts` and wired to a control. Worth knowing before either is estimated.

The controls are bare `<select>` elements; `shared/combobox` exists and is used on `/compare`.
And below the form is roughly **500 px of empty page** before the footer — a results region
absent rather than empty-stated reads as a page that has not finished loading.

## 4. `/builds` — a list that stops being a list at seventy-five

The saved column is alphabetical, one row per build, with no search, no filter and no grouping.
The owner's export produced **75 builds**; the column shows about nine at a time.

A row carries name, constellation, vision and weapon. It does not carry the thing a build page
exists to show: **the resulting stats**. There is no ATK, no CRIT, no ER on the card and no
expanded view reachable from it — `/explain` exists but is a separate destination reached from
the nav rather than from the build.

## 5. Ranking a single artifact — the gap the owner named

mistilteinn can answer *"what are the best five pieces I own for this build"* (`/optimize`) and
*"why did this number come out"* (`/explain`). It cannot answer either of the two questions a
player actually asks while holding a new drop:

1. **"Is this piece any good?"** — a score for one artifact, independent of a five-piece search.
2. **"Is this +0 worth levelling?"** — the *potential* of a piece, given the rolls it has not
   had yet. This is a distribution, not a number, and it is the harder and more valuable half.

`substat_rolls` already decomposes a piece into its rolls — 85.0% exact, 11.5% estimated, 3.5%
unknown on the owner's real export — so the input to a scoring model exists. What does not
exist is the weighting: a roll's worth depends on the character, and nothing in the repo yet
says how much CRIT DMG is worth to Ayaka relative to ATK%.

**This is task #3 and gets its own plan**, not a paragraph here.

## 6. Design — the Mitya palette is thinner than the logo

Observed across all eight pages: the brass/mint two-accent structure from `_tokens.scss` shows
up in the brand bar, the active nav underline, the eyebrow labels and the filter chips. Past
that, the pages are dark navy panels with hairline rules.

The rarity gradients on the new portrait cards are the only place colour does real work below
the header. The ornament that gives the app its emblem appears exactly once.

The owner's note is the right one: *"more of the gold fillory design could be nice (but not
overdone or AI slop)"*. **Task #5**, and deliberately last — it is the one where doing too much
is worse than doing nothing.

## 7. `/teams` and `/rotations` — the components exist and are not used

`/teams` is four bare `<select>` elements labelled 1–4. `shared/combobox` takes an optional
icon per option and is used on `/compare`, so the pieces for a team builder that shows you
*faces* are already in the repo and were not reached for here. The four-slot cap is correct —
a Genshin party is four — and the earlier note wondering why is answered.

Both pages, like `/optimize`, end in several hundred pixels of nothing. That is a layout
default rather than a decision: a page whose content is one panel should not reserve a
viewport's worth of space beneath it.

---

## What is genuinely good, and should not be traded away

Worth recording so a parity sweep does not flatten it:

- **`/explain` has no equivalent in Fribbels or GO.** Every multiplier in a hit, in order, with
  its source, and an explicit statement of what is *not* modelled.
- **The artifact card is already GO-quality** — per-substat roll bars, a roll-value ratio, and
  an honest `isExact` flag when the decomposition is estimated rather than known.
- **Refusals are specific.** The rotation importer names every line it cannot express;
  `weapon_comparison` reports `unmodelled_passives` rather than publishing a ranking it cannot
  make. Fribbels is a more finished tool; it is not obviously a more honest one.

## Method

`cd backend && python -m scripts.shoot --seed` against `references/genshin_export_2026-08-28_11-07.json`
(2,370 artifacts, 75 builds), then `--viewport` walks of `/inventory`, `/artifacts`, `/builds`,
`/teams`, `/optimize`, `/rotations`, `/compare`, `/explain`. No console errors on any of the
eight after the mannequin 404s were fixed.

---

## 8. Owned weapons are not stored at all

**Found 2026-08-29**, chasing an owner report that *"weapons aren't attributed to my builds
despite the Irminsul import."*

**The import was correct.** The export named a holder for exactly 68 of its 320 weapons, and
exactly 68 of the 75 builds got one. The seven weaponless builds — Beidou, Jahoda, Keqing,
Kujou Sara, Lynette, Sayu, Xinyan — are characters the file gave artifacts and no weapon.

**The cause is now known and measured.** The export contains **no 1★ or 2★ weapons at all** —
24 three-star, 67 four-star, 18 five-star, against ten one- and two-star rows in the catalogue —
and the owner confirms those seven are on default grey weapons. Irminsul omits them. So this is
a scanner omission on characters nobody has built, not a lost weapon, and the import reports it
as information rather than as a warning.

The import now says so, and says it separately from *"weapon not recognised"* — those two have
opposite remedies, and one message for both would send half of readers the wrong way.

**But the larger finding is that the other 252 weapons are discarded.** `ParsedWeapon` is read
only to attach a catalogue row to a build; nothing persists an owned weapon. There is a
260-row weapon *catalogue* and no weapon *inventory*, so:

- there is no page that shows the weapons you own;
- "who has this equipped" cannot be answered for a weapon, only for a build;
- a weapon's level and refinement exist only where a build happens to reference it.

The owner has asked for the inventory, with the holder's portrait on each row and equipped
pieces sorted to the top. **That is a chunk, not a tweak**: a table, a migration, an import
path, an API and a page — the shape `TASKS_artifacts.md` had. Worth knowing before it is
estimated.

---

## 9. Running the optimizer end to end — two defects and a separator

**Found 2026-08-29**, closing the last gap in the owner's task #4. `/optimize` had never been
run to completion in this session; the earlier pass only confirmed its controls existed. Running
it is what found these, and nothing in either suite says a word about them.

### 9a. A rotation search returns ten results, all scoring zero — **fixed**

Build: Nahida C2, Mappa Mare R5 Lv90. Team: Hyperbloom. Rotation: the authored eight-step
cycle. One 4-piece set selected, two calibrations completed, and the search finished:

> **Exact** — the best five over this inventory.  `10 combinations scored · 2,061 pieces pruned first`
>
> 1  **0**  Flower · Plume · Sands · Goblet · Circlet
> 2  **0**  …

Every rank scores **0**.

**Reproduced twice**, and the obvious explanation is ruled out: the first run used the
alphabetically first set, which gcsim does not implement; the second used **Deepwood Memories**,
which it certainly does — the caveat list confirms it was covered — and the result was
identical.

**Not a formatting artifact.** The template is `{{ row.damage | number: '1.0-1' }}`, so a real
figure would render as `12,345.6`. The damage genuinely is zero.

**This is the worst shape a result can have here**, and by this repo's own standard: a confident
`isExact` — *"the best five over this inventory"* — attached to ten identical non-answers. The
page reports its own precision correctly and its number not at all.

**It blocks `DESIGN_artifact_ranking.md` entirely.** That plan's engine, by owner ruling
(`DECISIONS.md` §22), is this evaluator. Scoring an artifact through something that returns zero
would produce a ranking of zeros. **Fix this first.**

#### Where the next session should start

Two facts narrow it a long way, both established rather than guessed:

- **`sim_runs` holds zero rows** — across the whole database, for every user. No calibration
  has ever been persisted. And the *"2 calibration(s)"* the page shows is a **planned** count
  rendered beside All/None *before* the search, not a completed one, so it is not evidence that
  any calibration ran.
- **`calibrateAll` drives `mod.sample(config, SEED)` twice per target** — a baseline and a
  probe — and hands both to `calibrate()`.

That points squarely at a trap this repo has already documented once. `sample()` **returns a
string on failure**, and `CLAUDE.md` records the symptom as misleading: *"flush() reports `index
out of range [0] with length 0` while the real message is on simulate()'s return value, which is
a string on failure."* A failed sample that is parsed rather than checked would yield a recipe
of zeros, and a search over zero-valued recipes returns exactly what was seen — ten
combinations, all scoring 0, reported as `isExact`.

#### Confirmed, and fixed

The instrumented run settled it, and the cause was not the documented trap. `sample()` returned
**valid JSON** — it did not fail. It reported `character_details: []`, a **two-byte log**, and
zero damage: a successful simulation of *nobody*.

The config explains why. `/builds/{id}/calibrate` validated that the build's character was on
the rotation's team, compiled the **team's** rotation, and then emitted **one character's
stanza**:

    nahida char lvl=90/90 cons=2 talent=10,10,10;
    ...
    active kaedeharakazuha;          <- never declared
    while 1 {
        if .kaedeharakazuha.skill.ready { ... }   <- nor these two
        if .furina.skill.ready { ... }
        if .kukishinobu.skill.ready { ... }
    }

gcsim does not reject that. It runs, simulates nobody, and returns a clean result — so the
recipe calibrated to zeros and the search ranked ten builds at 0 while reporting `isExact`.

**This is a worse variant of the trap `CLAUDE.md` records.** That one is a failure *string*
where JSON was expected, which a caller can catch. This is well-formed JSON describing an empty
run, which only a caller checking *what was simulated* can catch — and nothing did.

**Two fixes.** `build_config` now takes the whole team and emits a stanza each, carrying their
**own gear** rather than the calibration, because a teammate's buffs are what the subject's
damage is measured inside — the point of calibrating "in this team" at all. And it **refuses**
any config whose action block names a character it never declared, so the class of bug cannot
recur; that guard is checkable from the text, without a simulator or a browser.

The same single-character emission was live on `/builds/{id}/compare-weapons/gcsim`, which is
fixed in the same change.

Measured before and after, on the page's own config:

| | before | after |
|---|---|---|
| characters simulated | `[]` | all four |
| log | 2 bytes | 3,069,118 bytes |
| combinations scored | 10 | **7,293** |
| rank 1 damage | **0** | **11,237,434.9** |

And the calibration now reports real diagnostics — *"flatDamage carries a conversion no probe
could resolve, affecting 96.3% of the damage"* — where it previously had nothing to say.

### 9b. The single-hit search blocks the page for minutes

The other objective, on the same 2,370-piece inventory, left the main thread unresponsive
past a 120-second wait *and* a 300-second read timeout — the harness could not so much as read
`document.body`. **Indicated rather than fully characterised**: it is possible something else
hung, and this deserves its own measurement before it is described as a hang. But an
in-browser search with no worker and no yielding is exactly the shape that produces it, and
`AUDIT_fribbels_parity.md` §1 already found this page's sibling putting 30,000 nodes on one
paint.

### 9c. Thirty set names with no separator

`uncoveredSets` rendered each name in its own `<span>`, and Angular collapses the whitespace
between adjacent elements — so the caveat read *"Brave HeartInstructorThe ExileBlizzard
Strayer…"*. **Fixed** in the same commit: the separator goes inside the element rather than
relying on inter-element whitespace.

### One thing that looked like a bug and is not

Result rows name pieces as `Flower · Plume · Sands · Goblet · Circlet` rather than by artifact.
That is `describePieces` behaving **as designed** — it maps a slot key to its display name, and
`WHY?` opens the full account. Checked before reporting.
