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
(#170). Remaining, in the order above: optimize team, optimize sets, rotation team, rotation
database search.

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
- **Curate recommended weapons per character from KeqingMains quick guides**, with rankings,
  where they exist. The owner notes this is a lot of scraping and expects agents to manage it.
  *Treat the citation rule as binding here* — this is exactly the shape of the failure
  `CLAUDE.md` names as fairy's worst.
- **"Why do we need to save a build before attaching artifacts?"** — a real question about the
  flow, not a styling note. Worth answering before redesigning around it.
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

### One build per character, and a priority order — *later*

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

- "New Rotation" pop-up like the others.
- ~~**"I don't know what 'Compile' is so users won't either."**~~ **Done (#166)** — the
  button says "Show gcsim config", which is what it does.
- ~~**Two levels**, search over teams.~~ **Done (#166)** — team cards with their party's
  faces and a rotation count; expanding lists that team's rotations. Search matches a team's
  name *or its characters*, since "which of my teams has Nahida" is how anyone looks for a team
  they named "Bloom 2".

  The summary reads **"8 steps · 11 actions"** rather than the audit's *"x hits, y seconds"*:
  hits and seconds are gcsim's answer and need a run, while a step's `repeat` is the closest
  thing this model holds. Naming it "steps" is the difference between a summary and a claim.
- **The rotation library is missing from the UI entirely**: there is no way to search for
  rotations for a team. It belongs as the last option inside an expanded team, opening a
  card-and-filter pop-up.
- **The rotation builder gets its own design pass**, after the smaller items. The owner: *"I
  want a very extensive and easy to use rotation builder, it's one of our key distinctions from
  gcsim."*

## 6. Optimize

- Drop "Searched in your browser…".
- **Start from a team** (card search), then pick the build within it.
- Drop "The rotation objective adds…" — redundant once the objectives are named properly.
- Objectives become **"Best single hit"** and **"Best across rotation"**. Users know the
  trade-off.
- ~~Remove **flower and plume** from the main-stat filters.~~ **Done (#163)** — a slot with one
  possible value gets no control. This reverses #146's reasoning, which is recorded in
  `stat-order` rather than dropped.
- ~~Order the main stats as in §2~~ **Done (#163)**; icons still to do.
- **An "Equip" button on the results** (owner, 2026-08-29): put the winning five onto the build
  that was searched for. `ScoredBuild` already carries `artifactIds`, so this is an equip call
  and a confirmation rather than a search problem. Worth doing when this page is next opened.
- **Set filters, from Fairy.** 4-piece and 2-piece mutually exclusive; selecting one 2-piece
  **requires** a second, because a lone 2-piece never constrains anything. 4-piece gets the
  first selector, being far the commoner. Card grid, not a drop-down.

## 7. Compare

The owner is unsure it deserves a tab — possibly **Optimize split into artifact and weapon
tabs** — and unsure of its value, but wants to see it through. Untestable for them right now
without a rotation. Apply whatever from the other tabs fits, and drop "Simulated with gcsim…".

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

- **Character**: move the weapon icon down beside the element, and match the element chip's
  style — icon plus the weapon class name in a bubble. Element filters get icons.
- **Nation filter**, if the data and icons exist. Not a priority if they do not — *check before
  building.*
- **Weapon**: icons on the filter.
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
