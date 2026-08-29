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

Adopted so far: **inventory set filter**. Remaining, in the order above: build character, build
weapon, optimize team, optimize sets, rotation team, rotation database search.

**A second recurring pattern:** several tabs put "new X" in a left panel and the saved items in
a narrow right column. The owner wants that inverted everywhere — the saved things are the page,
in a card grid with filters, and "New X" is a button opening a pop-up.

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

- Character picker: card grid, not a list.
- Weapon picker: card grid with filters in the pop-up.
- **Curate recommended weapons per character from KeqingMains quick guides**, with rankings,
  where they exist. The owner notes this is a lot of scraping and expects agents to manage it.
  *Treat the citation rule as binding here* — this is exactly the shape of the failure
  `CLAUDE.md` names as fairy's worst.
- **"Why do we need to save a build before attaching artifacts?"** — a real question about the
  flow, not a styling note. Worth answering before redesigning around it.
- Builds list becomes a card grid below the menu, with filters on element, weapon and rarity
  plus the existing search. **Search should cover characters only, not weapons.**
- "New Build" and "Build Priority" become tabs opening card-based pop-ups.

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
- **By reaction — BLOCKED, and this is the blocker.** This repo has **no reaction-to-element
  data**. `app/formula/genshin/damage.py` carries the four *amplifying* reactions and states in
  its own docstring that transformative and additive ones are deliberately absent, because
  gcsim computes them on a different path. Bloom, Hyperbloom, Overload, Quicken and the rest
  simply do not exist here.

  Writing the eleven-odd mappings from memory is the fabricated-citation failure `CLAUDE.md`
  calls fairy's worst. **They are derivable**: `pkg/reactable/*.go` at the pinned commit has a
  file per reaction, and `bloom.go` names `attributes.Hydro` and `attributes.Dendro` in its
  trigger switch. But it is tangled with aura-durability logic — `Quicken` and `BurningFuel`
  appear in the same switch — so a naive regex over-collects, and a subtly wrong table
  mis-classifies teams **silently**.

  So it is a snapshot script like `build_key_snapshot.py`, and its own task. Not attempted.

## 5. Rotations

- "New Rotation" pop-up like the others.
- **"I don't know what 'Compile' is so users won't either."**
- **Two levels.** The page lists *teams* as cards, each showing how many rotations it has.
  Expanding one lists that team's rotations with a card and high-level stats — *"x hits, y
  seconds"* — beside the user's own name for it. **Search is over teams, not rotations.**
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
- **Set filters, from Fairy.** 4-piece and 2-piece mutually exclusive; selecting one 2-piece
  **requires** a second, because a lone 2-piece never constrains anything. 4-piece gets the
  first selector, being far the commoner. Card grid, not a drop-down.

## 7. Compare

The owner is unsure it deserves a tab — possibly **Optimize split into artifact and weapon
tabs** — and unsure of its value, but wants to see it through. Untestable for them right now
without a rotation. Apply whatever from the other tabs fits, and drop "Simulated with gcsim…".

## 8. Explain → **Calculate**

Rename. Calculate damage for a rotation, every point explainable. Drop the subtitle. Start from
a **team**, then a **rotation** — and unlike Optimize there is no build to pick, because the
rotation already says who does what.

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
