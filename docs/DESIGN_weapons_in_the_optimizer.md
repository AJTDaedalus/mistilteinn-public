# DESIGN — weapons in the optimizer

**Status:** design, 2026-09-02. Nothing built yet.

## Branch policy

`feat/weapons-in-the-optimizer`, off `dev`. **No direct commits to `dev` or `main`** — this
feature is merged by PR after review, like every other. Sub-branches per task are fine and
should merge into this one. Task 0 of `TASKS_weapons_in_the_optimizer.md` is the branch-setup
gate.

## The ask

Owner, 2026-09-02, after looking for the feature and not finding it:

> *"I don't see weapons in the optimizer."*
> *"#2, in the existing optimizer as an option. Locking the set doesn't make a lot of sense
> because weapons can significantly affect which artifacts win."*
> *"Weapon should definitely be opt-in, off by default, and like set allow you to select some.
> We should have both sets and weapons 'tiered' with recommended sets/weapons first and
> highlighted somehow."*
> *"Are we sure the weapon search is exhaustive, that the best builds for favonius sword are
> being compared against the best weapons for fleuve cendre?"*

That last question is the design. The answer has to be **yes**, and two things in the current
search would quietly make it no.

## What already exists, and is reachable from nothing

`grep` for a caller of any of these, outside the generated `api.types.ts`, returns nothing:

| piece | state |
|---|---|
| `POST /builds/{id}/compare-weapons` | built, tested, **no caller** |
| `POST /builds/{id}/compare-weapons/gcsim` (knows passives) | built, tested, **no caller** |
| `frontend/src/app/sim/weapon-ranking.ts` | built, own spec, **no caller** |

**This is the third instance of the pattern `CLAUDE.md` names** — `createGpuKernel` and
`POST /sim-runs` were the first two, and both were found by building something that needed
them rather than by reading. This one was found by the owner going to use a feature that was
never wired up. The entry is worth keeping for the same reason the others are.

It also corrects an estimate given in the same conversation: *"surface the existing gcsim
weapon tier — cheap, uses code that already exists"* was wrong about the cheap part. The
endpoints exist; the UI does not exist at all.

## The two hazards, which are the same hazard

Both are a **measurement shared across a dimension that has just gained a member** — the shape
this repo produced three times in one day (#222, #227, #228).

### H1 — the Pareto prefilter, and the shape that avoids it

**Corrected 2026-09-02, after reading the call rather than reasoning about it.** The first
draft of this section said the live set must be a union across every weapon, or a piece that
loses under Favonius and wins under Fleuve Cendre is discarded before Fleuve Cendre is scored.
That is true of *one* implementation and not of the obvious one.

`searchRecipe` computes the live set from **its own `context.recipes`** and filters inside its
own call:

```ts
const live = liveQuantitiesFor(
  context.recipes.noFourPiece, ...context.recipes.byFourPieceSet.values(), ...
);
const { kept, removed } = paretoFilter(bucketBySlot(candidates), live);
```

So **one `searchRecipe` call per weapon is correct by construction**: each weapon filters the
inventory against its own objective, and a piece pruned in Favonius's search is untouched in
Fleuve Cendre's. The hazard is real only if someone hoists the filter out of the loop to save
the repeated work — which looks like an optimisation and is a silent loss of candidates.

**Requirement, restated:** the filter stays inside the per-weapon call, and a test pins that a
piece optimal under one weapon and dominated under another survives into the right search.
The cost of re-filtering per weapon is small against the ~2.5 minutes of gcsim each one
already needs.

**This is still #222's shape** — a lossless layer made lossy by an objective that does not
cover everything being scored. What changed is where the mistake would have to be made.

### H2 — the energy ladder is measured once and stamped onto every recipe

```ts
export function shareEnergyMeasurement(recipes: readonly Recipe[]): void {
  const donor = recipes.find((r) => r.meta.energySweep?.length);
  ...
}
```

Correct **across sets** — the ladder is a property of the team and the rotation. **Wrong across
weapons**, and Favonius is the sharpest counterexample available: it generates particles on
crit, so its energy curve is genuinely different from a stat-stick's. Reusing another weapon's
ladder would misprice the exact weapon the owner asked about.

**Requirement:** one ladder per weapon, shared only across that weapon's set states.
`shareEnergyMeasurement` becomes per-weapon rather than per-run.

**Cost consequence:** the ladder is ~30 s, so a weapon is **~2.5 min** rather than ~2.

## Cost, measured

`prod.txt` — the owner's 87-step rotation, 243 emitted actions, 100 iterations:

| | |
|---|---|
| native, all cores | 0.74 s |
| native, one core | 3.65 s |
| browser (WASM, single-threaded), from `CLAUDE.md`'s own measurement | ~7.8 s |

Per weapon, per search:

| | |
|---|---|
| calibration per 4-piece state (baseline + probe) | ~15 s |
| six states | ~90 s |
| energy ladder, 7 rungs × 60 iterations, **per weapon** (H2) | ~30 s |
| **per weapon** | **~2.5 min** |

### What that costs at the sizes anyone actually picks

Owner, 2026-09-02, and this is the number that matters rather than the pool size:

> *"most will select 1-2 weapons to compare … It's very rare to have more than 4 options you'd
> even want to compare, and I can't think of a scenario with that many outside of TC to provide
> the community, which likely wouldn't wait for gcsim in the first place."*

| weapons compared | wall clock |
|---|---|
| 1 (today's search, one weapon) | ~2.5 min |
| **2 — the common case: what I have against one alternative** | **~5 min** |
| 4 — the top of the realistic range | ~10 min |
| 29 — the owner's whole sword pool | ~70 min |

**The honest framing is marginal, not total:** each additional weapon costs **~2.5 minutes on
top of the search the user was already going to run.** The last row exists to show the design
does not break down, not because anyone is asking for it.

**So there is no prefilter.** An earlier draft proposed ranking with `compare-weapons/gcsim`
and calibrating only the top few, to keep a 29-weapon search tractable. At two to four
weapons that machinery costs more than it saves and adds a tier whose ordering can be wrong —
`compare-weapons` reports `unmodelled_passives` for a reason. The full search runs on every
selected weapon.

**And the compute is the user's.** gcsim runs in their browser, so a longer run spends their
time and their CPU, not this server's. That is what makes "let it run" a real option rather
than a promise this project cannot keep.

## Decisions

1. **Opt-in, off by default** (owner). A search that silently became seventy minutes long
   because a checkbox defaulted on is the interaction this repo already refuses elsewhere.
2. **Multi-select, like sets** (owner). The user picks *some* weapons; "all of them" is a
   deliberate act with a stated cost, not the default.
3. **A full artifact search per weapon** (owner, rejecting the fixed-artifact option). Anything
   less answers a different question, and the existing `compare-weapons` docstring already says
   so: *a weapon wanting a different artifact set loses a comparison it would win with its own
   pieces.* **No prefilter** — see the cost section; at the sizes anyone picks it would cost
   more than it saves.
4. **Inside `/optimize`** (owner), beside the artifact search, sharing the build and rotation
   already chosen there.
5. **The build's equipped weapon is always searched, and is the baseline.** Owner, 2026-09-02:
   *"The default should be the equipped weapon on the build still, I assume this won't be most
   people's default state, at least not first."*

   **This is not a set picker with a weapon in it.** A set is a hypothesis the user opts into;
   the equipped weapon is what they are wearing, and it is the thing every candidate is being
   compared *against*. So it is not an entry in the picker that can be unticked — it is the
   row the others are measured from, and with the feature off the search is exactly what it is
   today: one weapon, the equipped one, no extra cost, no extra UI.

   Opting in **adds** candidates beside it. Two weapons on screen means the equipped one plus
   one alternative, which is the common case and ~5 minutes.
6. **Tiered, recommended first and highlighted** (owner). See below.

## Tiering

**Both have a source, and it is the same one.** Owner, 2026-09-02: *"For sets it can be
'recommended' sets rather than an 'order'. Which I think KQMS provides."* It does.

`app/data/kqm/weapons.json` (#185) already carries KeqingMains weapon recommendations with
`position`, the weapon id, KQM's own sentence verbatim, the page and the retrieval date.
Coverage is **three characters** — Nahida (13), Furina (11), Kaedehara Kazuha (10) — captured
on the owner's ruling of *"manual, cited, small first"*.

Sets sit behind an `id="Artifact_Sets"` anchor on the same pages, in a table the existing
capture script's own comment already warns about reading by accident. Read for Furina,
2026-09-02:

| Artifact | DPS% | Notes |
|---|---|---|
| 4pc Golden Troupe | 100% | *"by far Furina's best set for her own personal damage…"* |
| 2pc HP% / Skill% / ER / Hydro% | ~83-89% | *"second-best option for her personal damage…"* |
| 4pc Tenacity of the Millileth | ~80% | *"far worse for Furina's personal damage than 4pc Golden Troupe…"* |

Richer than the flat "recommended" the owner asked for: a relative DPS figure and a note, from
the same anchored-table discipline. It also **independently corroborates the ranking this app
already produces** for that build — Golden Troupe first, Tenacity well behind.

**Prydwen is the other source, and is not the one to start with.** Owner, 2026-09-02:
*"prydwen also has this for a select subset of Genshin characters, but it's far less
exhaustive."* Recorded so a later chunk does not rediscover it and does not reach for it
first: a second source is worth adding where KQM has no page, and worth **attributing
separately** when it disagrees — two recommendations merged into one list without saying which
came from where is the citation failure this repo already refuses.

So:

- **A character with KQM data** gets a *Recommended* tier — weapons ordered by `position`, sets
  in the table's own order — each entry carrying its citation, then everything else below.
- **A character without** gets one flat list and **no invented tier**. A "recommended" heading
  above an ordering this repo derived itself would be a citation-shaped thing with no citation,
  which is the failure mode the BRIEF names as the one not to import from fairy.
- **A row that is not a named set is kept verbatim and not mapped.** `2pc HP% / Skill% / ER /
  Hydro%` describes a 2+2 with stat priorities; resolving it to a catalogue id would be
  inventing a set KQM did not name. It is shown as KQM's text, next to the sets that do map.

## Widening the capture, and what "unresolvable" has to mean

Owner, 2026-09-02: *"Why only those three characters? KQM has a quickguide for almost all
characters"* — and that is right. Three is not a limit of the source or of the script, which
already takes slugs:

    cd backend && python -m scripts.capture_kqm_weapons nahida furina

It is what got captured under the owner's own *"manual, cited, small first"* ruling, to prove
the pipeline before scaling it. The pipeline works, so this chunk widens it. **Tiering that
covers three characters is not the feature that was asked for.**

Two things do not scale linearly, and one of them is the owner's next note.

### "Unresolvable names should be intuitive"

The intuitive transforms already exist and are not guesses: `named()` strips KQM's own
parenthetical abbreviation and lifts an `R5` prefix into a number, then `gcsim_keys.normalise`
removes case, spacing and punctuation — so `A Thousand Floating Dreams (TFD)` and
`Kagura's Verity` with a curly apostrophe both resolve today.

**What is not intuitive is the refusal.** Today an unresolved cell is dropped and reported by
name, which at three characters is a short list somebody reads and at a hundred and fifty is a
wall of mystery strings. The rule this chunk adds:

> A refusal names **the nearest candidate in the catalogue** and its distance, so the human
> reading it answers *"yes, that one"* rather than going to look it up.

`Sacrificial Jade` against a catalogue holding `Sacrificial Fragments` should say so. That is
the difference between a report and a chore, and it is the same discipline the rotation
importer already follows: **name every line you could not express**, because that list *is* the
answer to "why did this not import".

**It still never guesses, and it has somewhere to go.** Owner, 2026-09-02: *"If you really
can't resolve any abbreviations or names, you can pass them by me."* So the refusal list is an
**escalation**, not a dead end: the capture reports what it could not resolve with its nearest
candidate, and the owner rules. A name resolved that way is recorded as a decision with its
ruling, the same as any other curated entry.

A nearest match is shown for a human to confirm, never applied.
Fabricated citations in curated data is the failure `CLAUDE.md` names as fairy's worst, and an
automatic fuzzy match is exactly how one gets written.

### The other thing that does not scale

Widening is **~150 page fetches**, one per character, run once and committed. Rate-limited and
deliberate, like every other capture in this repo — the output is a snapshot read from disk,
never a live fetch, because *"a recommendation that silently became a different one between two
page loads would be unciteable"*.

## Colour-coding the 2-piece selector

Owner, 2026-09-02:

> *"If they're 2P recommendations highlight them in the 2P selector, preferably with color
> coding that identifies the stat (red for attack, blue for hp, yellow for defense, silver for
> dmg%)"* … *"ER can be green, give other random weird 2P sets another color"*

**This is what resolves the unmapped row.** `2pc HP% / Skill% / ER / Hydro%` is not a set and
must not be mapped to one — but it is not unstructured either. In Genshin a "2pc HP%" is
*every set whose two-piece bonus grants HP%*, and this catalogue already knows which those
are. `artifact_set_affixes.add_props` carries the stat, so KQM's row resolves to a **class of
sets** rather than to a name it never wrote.

Read from the catalogue, 2026-09-02 — sets by their 2-piece stat:

| stat | sets | colour |
|---|---|---|
| `ATTACK_PERCENT` | 13 | red |
| `ELEMENT_MASTERY` | 6 | purple |
| `CHARGE_EFFICIENCY` | 5 | green |
| `*_ADD_HURT` (elemental and physical DMG%) | 11 across 7 elements | silver |
| `HP_PERCENT` | 2 | blue |
| `DEFENSE_PERCENT` | 2 | yellow |
| healing, shield cost, flat HP, flat DEF | 6 | grey |

**EM gets its own colour rather than the "weird" bucket.** Six sets and a stat half the roster
scales on is not an oddity; the grey bucket is for the genuinely odd — healing bonus, shield
cost reduction, and the two sets whose 2-piece is a *flat* stat.

### The colour tokens are new, and must be

The palette has no red, blue, yellow or green. What it has that is close is
`--element-hydro`, `--element-geo`, `--element-dendro` and `--element-pyro` — **and using
those would be a bug.** Those colours already mean *elements* everywhere else in this app, so a
blue chip would mean "HP%" in the 2-piece selector and "Hydro" three components away. Same
pixel, two vocabularies.

So this adds `--stat-atk`, `--stat-hp`, `--stat-def`, `--stat-dmg`, `--stat-er`, `--stat-em`
and `--stat-other`, sampled to sit beside the existing palette rather than borrowed from it.
`npm run check:tokens` is what stops one of them being referenced before it exists — the check
that exists because `var(--accent)` once drew a badge as dark text on a dark tile with a clean
build, a passing lint and a unit test asserting its content.

**Colour is never the only signal.** Each chip carries the stat's name as text. A palette that
encodes meaning in hue alone is unreadable to a colour-blind user and invisible in a
screenshot pasted into chat.

## Open questions

**OQ-W1 — resolved, 2026-09-02.** Sets do have a source: the `Artifact_Sets` table on the
same KQM pages, read by the same anchored capture. What remains is work, not a question —
`capture_kqm_weapons.py` grows a second table reader and the snapshot grows a `sets` key.

**OQ-W2 — should an unowned weapon be selectable?** The comparison is meaningful for a weapon
the user does not have (*"is the signature worth pulling?"*), and `owned_weapons` is what the
picker would otherwise filter to. Leaning yes, marked, and off by default.

**OQ-W3 — how are cross-weapon results presented?** One list of `(weapon, artifacts, damage)`
rows, or a winner per weapon with the artifact detail behind an expander. The second is closer
to how the question is asked and is the current lean.
