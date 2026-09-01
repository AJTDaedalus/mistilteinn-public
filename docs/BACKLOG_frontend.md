# BACKLOG: the frontend, from the owner's manual audit

**Owner audit, 2026-08-29.** Recorded as a backlog, to be worked **after the current docket and
after `DESIGN_artifact_ranking.md`** — the owner set that priority explicitly.

Two items are **not** backlog and were handled immediately, because they were questions with
measurable answers rather than requests: the grey bars and the missing denominators. See §10.

`docs/AUDIT_fribbels_handson.md` covers some of the same ground from the other direction; where
they overlap, prefer whichever is more specific and note the other.

---

## 1. A recurring pattern, not a list of tweaks

Four separate notes say the same thing, and it should be built once rather than four times:

> Drop-downs for filters should be pop-up square icon grids with cards for things with images.
> **This applies everywhere.** See Fairy.

So the unit of work is a **shared card-grid picker** — a pop-up, filterable, with art per
option — and then its adoption on: inventory set filter, build character, build weapon,
optimize team, optimize sets, rotation team, rotation database search.

`shared/combobox` is the nearest thing that exists and is a *list*, not a grid. Fairy is the
reference the owner keeps naming; read it before designing.

**Built — `shared/card-picker` (#162).** Fairy has *three* near-identical pickers
(`set-picker`, `agent-picker`, `wengine-picker`); this is one, generic over `CardOption`, and
copying that shape per surface is how the fourth one ends up subtly different.

Adopted so far: **inventory set filter** (#162), **build character** and **build weapon**
(#170), **optimize team** and **optimize build** (#171), **optimize 4-piece and 2+2** (#172),
**compare team and build** (#176), **rotation team** and the **rotation database search**
(#178, #179). **The adoption list is complete.**

`CardOption.icons` was added for the team card (#171): a team's identity is the four characters
in it, and electing one of them to stand for the whole thing is a card that lies about what it
is. The rotation-team adoption wants the same thing, so reach for it rather than adding a
second way.

`clearable` was added to the picker for the build weapon and is worth knowing about before the
next adoption: multi-select always offers "Clear", single-select does not, because you replace
one choice by making another. A build's weapon is the exception — `weapon_id` is nullable by
design, and a picker that could only ever *add* a weapon would quietly delete that state.

**A second recurring pattern:** several tabs put "new X" in a left panel and the saved items in
a narrow right column. The owner wants that inverted everywhere — the saved things are the page,
in a card grid with filters, and "New X" is a button opening a pop-up.

**Done for Builds (#170)**, and the inversion is what makes the rest of §3 possible: the editor
used to hold the left two thirds permanently, so the list beside it could never be a grid. It
is a `<dialog>` now, opened by "New build" or by picking a card. The pickers inside it open
their own dialogs on top, which the top layer stacks correctly — worth knowing, because it is
the thing that looked most likely to break and did not.

## 2. Inventory

- ~~Drop the "Your artifacts…" subtitle.~~ **Done (#163)**
- ~~"IMPORT A GOOD EXPORT" → "IMPORT FROM GOOD FILE".~~ **Done (#163)**
- ~~"Also rebuild builds" → "Reimport builds"; drop both lines of subtext.~~ **Done (#163)** —
  the destructive confirm still says "Deletes all N artifacts", which is where the warning has
  to be.
- ~~Set filter becomes a card grid (§1).~~ **Done (#162)** — 38 owned sets, art-first, with
  how many of each you own on the card.
- ~~**Main-stat selector should be ordered, and flat stats excluded.**~~ **Done (#163)**, in
  `shared/stat-order` so the optimizer uses the same order.

## 3. Builds

- ~~Character picker: card grid, not a list.~~ **Done (#170)** — filtered by vision and by
  weapon class, and by nothing else: a 4★ character is not a worse build subject, and offering
  rarity as a filter implies it is.
- ~~Weapon picker: card grid with filters in the pop-up.~~ **Done (#170)** — rarity only, and
  only when the list holds more than one. There is deliberately **no weapon-class chip**: the
  server already filtered the list to the character's class, so a "Bow" chip on a Sword
  character would be a control whose only possible outcome is an empty grid.
- ~~**Curate recommended weapons per character from KeqingMains quick guides**, with rankings,
  where they exist.~~ **Done (#185)**, on the owner's ruling: *"manual, cited, small first"*.

  **Three characters captured** — Nahida, Furina, Kaedehara Kazuha — 34 recommendations, each
  carrying KQM's own sentence verbatim, the page it came from and the date it was retrieved.
  `scripts/capture_kqm_weapons.py` is the reproduction and the snapshot is committed; re-running
  it is deliberate and the diff is the review.

  **Two things the capture refuses rather than guesses**: a weapon name that does not resolve
  to this catalogue, and a row naming several weapons where any one of them fails — all or
  nothing, so a partial split can never be published as though it were KQM's list. Every
  refusal is kept in the file.

  **It publishes `position`, not `rank`.** KQM's table has an order and no rank numbers, and
  the difference between citing a source and putting words in its mouth is exactly that.
- ~~**"Why do we need to save a build before attaching artifacts?"** — a real question about
  the flow, not a styling note. Worth answering before redesigning around it.~~ **Answered,
  2026-08-29.** Because equipping is a property of the *artifact*, not of the
  build: it is `PATCH /artifacts/{id}` with `build_id`, and a build that has not been saved has
  no id to point at. `ArtifactPanel` takes `buildId` and is inert while it is null; that is not
  a rule someone chose, it is the shape of the write.

  **So it can be removed, and here is the cost.** The panel could hold the choices client-side
  and the page could equip them after `create` returns. What that buys is one fewer step. What
  it costs is a new partial-failure state — build created, some pieces equipped, one refused —
  which is exactly the hazard #173's equip pre-flight exists to avoid on the optimizer, and it
  cannot be pre-flighted here because the build does not exist until the moment before.

  **Not built, and this is a judgement rather than a blocker.** The flow is two steps and both
  are visible; the alternative is one step that can end half-done. If the owner wants it
  anyway, the shape is a `pending` signal on the panel and a loop in `save()` — an afternoon,
  not a chunk.
- ~~Builds list becomes a card grid below the menu, with filters on element, weapon and rarity
  plus the existing search. **Search should cover characters only, not weapons.**~~ **Done
  (#170)** — 75 cards, art first. The chips are drawn from the builds on screen rather than
  from the catalogue, so a chip can never filter to nothing. Rarity is the **character's**,
  not the weapon's: these cards are character-first, and a rarity beside the name that meant
  the weapon's would be reading the wrong number off the same card.

  Dropping the weapon from the search cost a test that asserted the opposite, and its reason
  is worth keeping: *"who has Freedom-Sworn"* is an ordinary question. It is a filter question,
  not a search one — typing "sword" used to return every build holding one.
- ~~"New Build"~~ **Done (#170)** — a button in the header opening the editor pop-up.
  **"Build Priority" is still to do**, and belongs with the *later* section below rather than
  here, since the ranking is what the tab would open.

### ~~One build per character~~, and a priority order — **both answered**

**The ranking shipped (#212); the uniqueness constraint is declined** — owner ruling,
`DECISIONS.md` §31, 2026-09-01: *"Convention is to keep T1.a, because each user's account only
has one of each character."* Limiting one build per character would reinstate what T.1a
dropped on 2026-08-24, five days before this entry was written. The two are reconciled in the
ruling's favour.

Build Priority, artifact stealing and drag-to-reorder are all built. The original note follows.

The owner is explicit that this is a nice-to-have for when there is nothing else: limit one
build per character like Fribbels, add a **Build Priority** ranking, and let a higher-ranked
character "steal" an artifact from a lower-ranked one in the optimizer — the point being to
show that a suggested piece is *owned*. Drag-and-drop for the ranking.

## 4. Teams

- ~~No default name.~~ **Done (#165)**
- ~~Slot placeholder → "Select".~~ **Done (#165)**
- ~~Drop "The first slot must be filled".~~ **Done (#165)** — `canSave()` already greyed the
  button out, so the sentence was saying what the control already said.
- "New Team" becomes a button with a pop-up builder.
- ~~Saved teams become wide cards, four characters each with level and weapon.~~ **Done
  (#165)** — character level plus weapon **without** the weapon's level. Together they read as
  one number repeated; the owner's ruling was to keep the character's and drop the weapon's.
- ~~Filters by element~~ **Done (#165)** — the visions actually fielded, as emblems.
- ~~**By reaction.**~~ **Done (#167) — the blocker was resolved by the owner supplying a
  source.** It had been blocked because this repo has no reaction-to-element data at all:
  `formula/genshin/damage.py` carries the four *amplifying* reactions and states that
  transformative and additive ones are deliberately absent.

  The owner pointed at the Genshin Impact Wiki. `WebFetch` returns **HTTP 402** on that host and
  plain `curl` hits a challenge, but the wiki's own **MediaWiki API** answers 200 with page
  wikitext — so 21 reactions were derived from the source's own wording rather than from
  memory, and committed with their provenance (`docs/RESEARCH_elemental_reactions.md`).

  **Fifteen are offered; six are not.** Shattered is not an element pair at all — the source
  says *"a Blunt or Geo attack"*, and Blunt is Physical — and the five Lunar/Stellar reactions
  are out by owner ruling (2026-08-29): *"just the base reactions (minus shatter) is fine."*
  Four of those were uncertain anyway; **Lunar-Bloom was not**, and is the one the ruling
  actually decides. A filter that mis-classified a team silently is worse than one that offers
  less.

## 5. Rotations

- ~~"New Rotation" pop-up like the others.~~ **Done (#179)** — and the same inversion Builds
  got: the saved teams are the page, the editor is a `<dialog>` opened by the button or by
  picking a rotation. The team `<select>` is a card picker with the party's four faces.
- ~~**"I don't know what 'Compile' is so users won't either."**~~ **Done (#166)** — the
  button says "Show gcsim config", which is what it does.
- ~~**Two levels**, search over teams.~~ **Done (#166)** — team cards with their party's
  faces and a rotation count; expanding lists that team's rotations. Search matches a team's
  name *or its characters*, since "which of my teams has Nahida" is how anyone looks for a team
  they named "Bloom 2".

  The summary reads **"8 steps · 11 actions"** rather than the audit's *"x hits, y seconds"*:
  hits and seconds are gcsim's answer and need a run, while a step's `repeat` is the closest
  thing this model holds. Naming it "steps" is the difference between a summary and a claim.
- ~~**The rotation library is missing from the UI entirely**: there is no way to search for
  rotations for a team. It belongs as the last option inside an expanded team, opening a
  card-and-filter pop-up.~~ **Done (#177, #178)** — it was missing from the *backend* too, so
  #177 built publishing, the character index, likes and copying, and #178 is the pop-up.

  It opens **pre-filtered to the team it was opened from**, because a library reached from
  inside a team is asking "what do people run on *this*" — and widens to everything published,
  or the control is a list rather than a search. The two silences are said differently: nobody
  has published for this party, or nobody has published at all.

  The like is optimistic and reverts on failure: a like is a one-bit opinion, and waiting a
  round trip to see it register is the wrong trade, while a count that stayed after a failure
  would be a number the server does not agree with.
- ~~**The rotation builder gets its own design pass**, after the smaller items.~~ **Done —
  `docs/DESIGN_rotation_builder.md` (#181), and every surface item with it (#181, #184).**

  The design's first job was establishing what *"extensive"* can mean: `DESIGN_rotation.md` §2
  says the model refuses to be a language, so it means *costs less to say*. The owner confirmed
  (OQ-B1, "the surface only") and closed the quick-add line (OQ-B2, "buttons only").

  Shipped: ability names, click-a-face-click-an-action, duplicate-in-place, per-step notes,
  drag to reorder, and a live gcsim preview of **unsaved** steps.

## 6. Optimize

- ~~Drop "Searched in your browser…".~~ **Done (#171)**
- ~~**Start from a team** (card search), then pick the build within it.~~ **Done (#171)** —
  and **optional**: 75 builds against three teams on the owner's account, so requiring one
  would strand most of them. Clearing the team widens the build grid back to everything.

  The trap it walks into is narrowing the *list* without narrowing the *selection*: the page
  would keep answering for a character the user had just filtered away. It moves the selection
  onto the team's first member, and leaves it alone when the team does field it.
- ~~Drop "The rotation objective adds…"~~ **Done (#171)**. The line existed because everything
  that shapes a search lived behind the other objective, and the page looked like a tool that
  could not constrain one. Naming the objectives properly is what makes it redundant, so the
  two changes had to land together.
- ~~Objectives become **"Best single hit"** and **"Best across rotation"**.~~ **Done (#171)**
- ~~Remove **flower and plume** from the main-stat filters.~~ **Done (#163)** — a slot with one
  possible value gets no control. This reverses #146's reasoning, which is recorded in
  `stat-order` rather than dropped.
- ~~Order the main stats as in §2~~ **Done (#163)**; icons still to do.
- ~~**An "Equip" button on the results** (owner, 2026-08-29): put the winning five onto the
  build that was searched for.~~ **Done (#173).** It was not quite "an equip call": equipping
  into a filled slot is *refused* rather than swapped (A.1), and so is moving a piece another
  build holds — so the order is forced (off, then on) and one piece held elsewhere would
  otherwise land its refusal *after* this build had been stripped.

  It reads all five first and aborts with nothing changed. That refusal is the honest one
  until **build priority** exists: "steal it from the lower-ranked character" needs a ranking
  to know which character that is, and doing it without one is the same operation with the
  accountability removed.
- ~~**Set filters, from Fairy.** 4-piece and 2-piece mutually exclusive; selecting one 2-piece
  **requires** a second, because a lone 2-piece never constrains anything. 4-piece gets the
  first selector, being far the commoner. Card grid, not a drop-down.~~ **Done (#172)** — two
  card grids where there was a scrolling checkbox list and a `<details>` holding two
  drop-downs.

  **One reading was made explicit rather than guessed at.** Fairy's rule is about ZZZ's six
  disc slots, where a 4-piece and a 2-piece coexist in one build; Genshin has five, where a
  4-piece and a 2+2 are two *shapes* of the same five slots. So "mutually exclusive" was taken
  per set: a set chosen as a 4-piece is not offered as half of a pair, and the reverse —
  because a set can only be one of them in any build the search returns. Both panels remain
  usable in one search, which is what the engine already did. If the owner meant the stronger
  reading — one panel or the other per search — that is a one-line change to these computeds.

  The pair keeps the **last two** picked rather than refusing a third: a capped multi-select
  that ignores a click looks broken, and someone clicking a third set is swapping, not adding.

## 7. Compare

The owner is unsure it deserves a tab — possibly **Optimize split into artifact and weapon
tabs** — and unsure of its value, but wants to see it through. ~~Untestable for them right now
without a rotation.~~ ~~Apply whatever from the other tabs fits, and drop "Simulated with
gcsim…".~~ **Done (#176)** — the subtitle is gone and the build `<select>` is the team-then-who
pair from Optimize. A rotation now exists, so it is testable.

**Whether it deserves a tab is still open**, and nothing here decides it. What #176 did make
cheaper is the alternative: if Compare becomes a second tab *inside* Optimize, the entry point
is already the same two controls on both.

`shared/team-scope` came out of this — the team card, the slot-ordered party and the build card
were about to exist three times. Extracted at the second use rather than the fourth, which is
the mistake `shared/card-picker` exists to record.

## 8. Explain → **Calculate** — done (#168)

~~Rename. Calculate damage for a rotation, every point explainable. Drop the subtitle. Start
from a **team**, then a **rotation** — and unlike Optimize there is no build to pick.~~

**Not a rename — a different page.** The old one explained *one hit* for one build; this runs a
whole rotation for a whole team, so calling it "Calculate" without the restructure would have
promised the second and delivered the first.

gcsim calibrates once per character against the team's rotation, each recipe is evaluated at
that build's **real equipped gear**, and every recipe hit is one damage point with its own
ability and element. On the owner's Hyperbloom team: **31,782,037** — Furina 31.5%, Nahida
28.8%, Kazuha 21.1%, Kuki 18.6%.

`/explain` redirects rather than 404s.

## 9. Catalogue pages

- ~~**Character**: move the weapon icon down beside the element, and match the element chip's
  style — icon plus the weapon class name in a bubble. Element filters get icons.~~ **Done
  (#174).**

  The class mark had been a corner badge on the art, with a comment saying that *inline beside
  the vision chip it was a faint grey glyph reading as a stray artifact — measured in a
  screenshot, not guessed*. That observation was about a **bare glyph**, and the owner is
  asking for a bubble; `weapon-mark` gained a `chip` mode and the two facts a card states now
  state themselves the same way.

  The portrait grid went from 11rem to 12rem columns, because at 11rem the two chips wrapped
  on some cards and not others and the row heights went ragged.
- ~~**Nation filter**, if the data and icons exist. Not a priority if they do not — *check
  before building.*~~ **Checked, 2026-08-29: the data is not what the filter would need, and
  there are no icons.**

  `CharacterSummary.region` exists and is populated for 148 of 150 characters, but it is
  nanoka's **association type**, not a nation. Fifteen values, and seven of them are not
  nations at all: `ASSOC_TYPE_FATUI`, `HVISION`, `MAINACTOR` (the Traveler), `RANGER`,
  `OMNI_SCOURGE`, `NODKRAI_ZIBAI`, `SNEZHNAYA_STAR`. A "Nation" chip built on it would file
  Childe under Fatui rather than Snezhnaya and the Traveler under nothing recognisable.

  Deriving the real nation means a mapping this repo would be **writing from memory** — the
  exact failure `CLAUDE.md` names as fairy's worst — unless a source is found that publishes
  it. There are no nation emblems in `frontend/public/icons/` either. **Not a priority, and
  now with a reason rather than a guess.**
- ~~**Weapon**: icons on the filter.~~ **Done (#174)** — and the class list is now the
  server's. It had been written out in `weapons.ts`, which would have needed the mark's
  basename built client-side beside it; `GET /weapon-classes` publishes both. The crossbow
  class is absent by the server's decision rather than the page's: it has no mark, so a chip
  for it would be a wide word among five glyphs, finding only two unreleased Traveler
  variants.
- **"Sets and enemies are currently broken, I can't click them."** See §11.

## 10. Answered immediately, because they were questions

> Lots of gray bars still… They manage to get bars on all artifact rolls, why can't we with the
> same data? … Not all artifacts have a denominator for roll value, why is that?

**Both had the same cause, and both are fixed.** Two roundings conspired: the tier tables are
float32, so a true 5.25% ATK% roll is stored as `0.05249999836`; and Python's `round` is
banker's, so it displayed as `5.2` where the game shows `5.3` and the export writes `0.053`.
The line then matched *no* combination and was reported undetermined — which the card draws as
a grey bar with no denominator.

Measured on the owner's 2,370-piece inventory:

| | before | after |
|---|---:|---:|
| substats undetermined | 277 (3.5%) | **1 (0.0%)** |
| pieces with a grey bar | 266 (11.2%) | **1 (0.0%)** |
| pieces fully exact | 84.7% | **95.4%** |

The one survivor is a CRIT DMG value no combination of tiers reaches at any legal count. It
stays unknown, which is the honest answer.

**So the answer to "why can't we, with the same data" is that we can** — GO compares the
*displayed* value, and ours was computing a different display than the game does.

A second, smaller fix went in alongside: the roll budget now uses the **visible substat count**
to constrain the initial count. A `+0` five-star showing three lines must have started with
three, so its budget is `{3}` and not `{3, 4}`.

## 12. ~~Found while verifying #173: the single-hit search freezes the page~~ — fixed (#175)

**Not in the owner's audit, and not caused by any of #170–#173** — `frontend/src/app/sim/search.ts`
has not changed since `68b7f90`, the kernel work. Found while trying to click the new Equip
button, which needs a result to click on.

**Measured, on the owner's 2,370-piece inventory, default settings, no main-stat filters.** From
the moment "Search" is clicked the main thread is blocked solid: a headless browser could not
read the button's own text, count a DOM node, or take a screenshot — **for 227 seconds
continuously**, at which point the run was stopped. No result row ever appeared.

Three things are worth separating:

1. **How long the search takes** is unknown; it did not finish. `isExact` implies pruning
   bounds it, so it should terminate — that it did not inside four minutes is the thing to
   measure first, with `scripts/bench_optimizer.py` as the precedent for how.
2. **That it is synchronous** is the part the user feels. The button reads "Searching…" and
   nothing else happens, because nothing else *can* — no progress, no cancel, no repaint. The
   rotation objective has a progress line; this path has none, and could not show one anyway.
3. **#130 concluded workers were not worth building** — *"no browser penalty on `sample()`"*.
   That measured gcsim's own call, not this enumeration, so it is not evidence about this path
   and should not be cited as though it were.

**This was the one thing on this page a user could not work around.** Fixed in **#175** by
porting budget-K, the lossy layer `artifact_prefilter.py` already had and that `isExact` was
already written to report.

The numbers behind the fix: the raw space is **2.35e13** combinations, the lossless layer
leaves **3.99e10**, and one scored combination costs **3.5 µs** (measured by the committed
`frontend/scripts/bench-search.mjs`, not borrowed from the server's 5.5e-4). That is 39 hours.
With a five-second budget the layer keeps **K = 17** per slot, and the same search that froze
the page for 227 seconds now returns in **4.1 s** — saying, in the result, that it scored
1,419,857 of 23,542,492,548,960 and is therefore not proven optimal.

**The docstring's reasoning for leaving budget-K out was checkable and wrong**: it rests on
DESIGN §2 expecting the GPU to search exhaustively, and `createGpuKernel` has no callers. That
is the sentence to revisit if the GPU is ever wired up.

## 11. Not reproduced: "sets and enemies are broken"

**I could not reproduce this and have not guessed at it.** Tested 2026-08-29:

- both nav links navigate correctly in a headless browser — `/artifact-sets` renders `ARTIFACT
  SETS` with 190 nodes, `/enemies` renders `ENEMIES` with 3,240;
- both routes return `200` in production, as do their APIs;
- one console 404 on `/artifact-sets`, for a set icon nanoka does not publish — benign, and
  `CatalogueIcon` hides it.

**The likeliest explanation is the one thing I can see:** those links sit in
`.shell__group--reference`, styled `--ink-faint`, and render visibly dimmer than the primary nav
group. That reads as *disabled*. It does not explain why Characters and Weapons — in the same
group — were clearly used, so it is a hypothesis and not a finding.

Worth asking the owner for one detail: whether the link did nothing, or the page loaded and its
cards did nothing.
