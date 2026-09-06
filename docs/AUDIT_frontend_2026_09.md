# Frontend usability & visual audit — 2026-09

> **Status, 2026-09-03: all fifteen findings addressed, across two PRs.**
>
> **#254** took the systemic half — the ones that were a pattern nothing owned, so every page
> decided separately: app-wide scrollbars (§4, §9), a `:disabled` rule that **did not exist**
> (§7, §11), checkboxes drawn from the palette (§11), the `/builds` filter row that read as
> *forbidden* (§10), `/optimize`'s mode toggle moving above the fields it governs and its
> zero-option `Hit` select (§6, §8), a missing icon that no longer collapses its card (§12),
> and the results table's header (§1, §2).
>
> **#256** took the four that were features rather than restyles: the artifact picker (§3),
> the inventory's page size (§5), `/calculate`'s empty state and its per-target reaction rows
> (§14), and the picker dialog's size (§15).
>
> **Two findings were withdrawn or declined after checking**, and both are recorded where they
> stand rather than quietly dropped: §7's import claim (a two-step confirmation already
> existed at `artifacts.ts:486-500`) and the "underlined like a link" note under *Smaller
> things* (it is `border-bottom: 1px dotted` with `cursor: help`, the conventional tooltip
> affordance).
>
> **Two of the four in #256 turned out to be different problems than they looked**, which is
> the entry worth carrying out of this document: §14's duplicate `bloom` rows were **three
> enemies**, discarded at parse time — no table styling could have fixed it; and §3's picker
> was fixed once, shipped with the sort silently discarded by the control, and had to be
> looked at again to notice.

A fresh-eyes pass over every reachable page and dialog, grounded entirely in screenshots taken
during this session. Nothing here was inferred from reading source: every finding names the
image it was seen in. Where something looked wrong at one size, it was re-checked at another
before being written down; two candidate findings (a heading rule "overlapping" the search box
on `/rotations`, and a clipped accent rule on `/builds`) were dropped after a crop showed them
fine.

## Method

- `cd backend && python -m scripts.shoot` for the 14 routes, then Playwright (adapted from
  `/root/erwork/shoot_builder.py`) to open the dialogs, drive a real `/calculate` run and a real
  single-hit `/optimize` search.
- Viewports: **1440×1000** (shoot default), **1440×900**, **1280×800**, **1100×700**,
  **1920×1200**. Dialogs were re-shot at 1440×900, 1920×1200 and 1100×700.
- All new images are under `/root/mistilteinn/screenshots/` (route shots) and
  `/root/mistilteinn/screenshots/audit/` (dialogs, driven flows, evidence crops).

### Pages checked

| Route | Shot | Also driven |
|---|---|---|
| `/` | `screenshots/landing.png`, `audit/landing_1100.png` | — |
| `/inventory` | `screenshots/inventory.png` (11,664px) | import panel, set picker |
| `/my-weapons` | `screenshots/my-weapons.png` (6,615px) | — |
| `/builds` | `screenshots/builds.png` | build editor, artifact panel, hover state |
| `/teams` | `screenshots/teams.png` | new-team dialog |
| `/rotations` | `screenshots/rotations.png` | rotation builder, 3 viewports |
| `/optimize` | `screenshots/optimize.png` | single-hit search run to completion |
| `/calculate` | `screenshots/calculate.png` | team+rotation picked, run to a result |
| `/teapot` | `screenshots/teapot.png` (6,968px) | — |
| `/characters` | `screenshots/characters.png` (8,918px) | — |
| `/weapons` | `screenshots/weapons.png` (13,044px) | — |
| `/artifact-sets` | `screenshots/artifact-sets.png` (6,866px) | — |
| `/enemies` | `screenshots/enemies.png` (14,808px) | — |
| `/login`, `/pending` | `screenshots/login.png`, `pending.png` | **see "could not reach"** |

### Could not reach

- **The signed-out login and pending screens.** Both routes redirect to the landing page for an
  authenticated session, so `login.png` and `pending.png` are byte-identical to `landing.png`.
  The harness's own rule is that photographing the wrong page under the right name is worse than
  erroring; these two are exactly that case and should be excluded or shot with a cleared token.
- **First-run empty states** (no builds, no teams, no artifacts). The screenshot account is
  seeded from the owner's GOOD export, so every list had content. The one empty state I did see
  (`/optimize` "No saved runs yet") reads well.
- **The `DETAILS` / "why this won" pane** on an optimize result — one more click than I had
  budget for.

### Console errors

Only one page logged anything across every route and every driven flow:

```
/artifact-sets   HTTP 404  http://localhost:4201/icons/UI_RelicIcon_15004_4.webp
```

That is finding 12 below. Every driven interaction — build editor, artifact panel, team dialog,
rotation builder, a full `/calculate` run, a full single-hit `/optimize` search — logged **zero**
console errors.

---

## Findings, ranked by user impact

### 1. The optimize result does not show what distinguishes one result from another
**Page** `/optimize`, results table · `screenshots/audit/optimize_result.png`,
crop `screenshots/audit/crop_optimize_rows.png`

A real single-hit search on Nahida returned ten ranked rows. **All ten are visually identical**:
every row reads `HP 4,780 · ATK 311 · ATK% 46.6% · Dendro DMG Bonus 46.6% · CRIT Rate 31.1%`,
because the main stats are the same across candidates. The only thing that differs between rank 1
and rank 10 is the **22px artifact icon** on each tile. No set names, no substats, no roll values
— all of which the Inventory page renders for these exact same pieces.

There is also **no header row**: the score column shows `745.2` and a delta `0.0% / -0.1%` with
no label and no unit anywhere on the page. A reader cannot tell whether 745.2 is DPS, damage per
hit, or an index.

Why it matters: this is the product's answer — the screen the whole app exists to produce. As
drawn, a user cannot say what they are choosing between, cannot tell that the top ten span only
1.2%, and cannot verify the recommendation. It also silently contradicts the landing page's
promise that "every number [is] able to show its working".

### 2. Disabled primary buttons are indistinguishable from enabled ones
**Page** `/calculate` (and any `.btn-primary` in a disabled state) ·
`screenshots/audit/calc_picked.png`

With a team chosen but no rotation, the purple **CALCULATE** button is `disabled`. Measured on
the live element: `background-color: rgb(73,51,106)`, `opacity: 1`, `cursor: pointer` — byte for
byte the enabled appearance, right down to the hand cursor. Nothing on the page says a rotation
is still required.

A user picks a team, clicks the big purple button, and **nothing happens, with no message**. This
is the failure mode that reads as "the app is broken". It is a token/state problem rather than a
one-page problem, so it likely repeats wherever a primary button gates on input.

### 3. Equipping an artifact — the app's central action — is five raw `<select>` dropdowns
**Page** build editor → Artifacts · `screenshots/audit/artifact_panel_empty.png`

For a build with empty slots (Kaeya), the Artifacts fieldset renders five **native OS selects**,
each defaulted to "Empty". The Flower select holds **360 options**, each a single line of text
(`Set · +level · main stat`). No search, no sort, no roll value, no substats, no artifact art —
none of the information the Inventory page shows for the same pieces, and no way to find the good
one in three hundred.

They are also the only native controls in a dialog whose character and weapon fields are rich
custom card pickers, so the most important control in the dialog is the least designed one.

### 4. The rotation builder clips its own move palette, with no scroll affordance
**Page** rotation builder · `screenshots/audit/rotation_builder.png`,
crop `screenshots/audit/crop_rotation_palette_clip.png`, `audit/rotation_1100.png`

At 1440×900 and 1100×700 the character move palette (`OL.runs`) overflows its column —
1136px of content in a 788px box — and **the fourth character's card is sliced through the middle
of an icon**. It is `overflow-x: auto`, so the moves are technically reachable, but there is no
visible scrollbar, no fade, no arrow: the only cue is a half-drawn icon. A rotation author trying
to add a Skirk ability has no reason to believe more exist. It fits only at 1920×1200.

At **1100×700** the same dialog is worse: its content is 1427px tall in a 642px box, so the
entire 16-step rotation you are editing sits below the fold while you edit it.

Also in this dialog: nearly half the step names are truncated (`Soloist's Solici…`,
`Low-Temperat…`, `Havoc: Su…`) while ~120px of the same row sits empty; the dialog title is just
"EDITING" with no rotation name (the build editor says "EDITING AINO"); nine buttons in two rows
are all the same weight, including labels that mean nothing out of context (`PASTE 0`,
`GROUP ×2`).

### 5. Inventory paginates 2,369 pieces 120 at a time, with the control at the bottom of an 11,664px page
**Page** `/inventory` · `screenshots/inventory.png`,
crop `screenshots/audit/crop_inventory_showmore.png`

"Showing 120 of 2369 pieces." The only way forward is a **SHOW MORE (2249 LEFT)** button at the
very bottom of an eleven-screen page. Reaching piece 500 means four full-page scrolls; reaching
the end means twenty. There is no page-size control, no jump, and no indication near the top that
more exists beyond the count sentence.

### 6. `/optimize` renders an empty 40px `<select>` before a build is chosen
**Page** `/optimize`, single-hit mode · `screenshots/audit/optimize_singlehit.png` vs
`audit/optimize_running.png`

Switching to **FOR A SINGLE HIT** with no build selected draws a `Hit` select that is **40px wide
and contains zero options** (verified on the live element: `option` count 0). It sits next to
populated `Element` and `Scope` selects and reads as a broken control. Nothing says "choose a
build first".

Once a build is chosen the same select becomes **660px wide** and the whole control bar reflows
onto two lines. A field that changes width sixteen-fold on selection makes the panel feel
unstable.

Related, same row: the mode toggle (**WITH A ROTATION / FOR A SINGLE HIT**) sits *below* the
fields it governs, so you read the consequence before the choice.

### 7. Destructive actions are not distinguishable from safe ones — four separate instances
- **Build cards**: the delete `×` appears **only on hover**, ~10px, mid-grey, drawn on top of the
  character's face. `screenshots/audit/builds_hover.png`
- **Artifact cards**: a pale blue `×` on the gold header band — the lowest-contrast element on the
  card. `screenshots/inventory.png`
- **Team cards**: a bare `×` top-right, identical in weight to a dialog close button.
  `screenshots/teams.png`
- **Optimize results**: **EQUIP** (re-equips five artifacts) is the same size, border and colour
  as **DETAILS** (reads), sitting flush beside it, ten times down the page.
  `screenshots/audit/optimize_result.png`

~~And one worse than any of them: the GOOD import panel's **MODE select defaults to
"Replace"**, directly above a purple IMPORT button, with no wording anywhere about what Replace
does to 2,369 existing pieces.~~

**Withdrawn on verification, 2026-09-03 — this one is already handled.** Clicking IMPORT with
`mode === 'replace'` and pieces present does **not** import: `runImport` returns early and the
button becomes **"Yes — delete 2,369 and import"** with a **Cancel** beside it
(`artifacts.ts:486-500`). The resting screenshot shows step one of a two-step confirmation, and
the flow was not driven. The `replace` default is also a recorded owner ruling with a stated
reason — GOOD carries no stable per-artifact id, so appending a re-scan duplicates every piece —
and the explanatory prose was removed by a second ruling ("Less is more with text").

Kept visible rather than deleted, because an audit that quietly loses its wrong findings teaches
nobody which kinds of finding need driving before they are believed.

### 8. The energy checkbox is detached from its own label
**Page** `/optimize`, Artifact Sets panel · crop `screenshots/audit/crop_optimize_energy.png`

The bold title **"Wait for energy instead of skipping the burst"** sits on one line, indented,
with nothing to its left. The checkbox sits on the *next* line, to the left of the explanatory
paragraph, vertically aligned to the paragraph rather than the title. It reads as a checkbox
belonging to the body copy, and the title reads as a heading with no control.

It is also a raw unstyled native checkbox (bright white square) on a dark panel — see finding 11.

Immediately above it, **"gcsim cannot simulate: Heart of the Furnace, Scarlet Proof."** is plain
muted body text, flush to the left edge, outside the fieldset it refers to and with no warning
styling. It appears before you have picked any set, so it warns about something you have not done.

### 9. Dialogs cut their content off with no scroll affordance, and hide the primary action
**Pages** build editor, build picker, set picker ·
`screenshots/audit/build_editor.png`, `editor_1100_fold.png`, `optimize_build_picker.png`,
`inventory_setpicker.png`

The build editor is `overflow-y: auto` but paints no scrollbar and no edge treatment. At 1440×900
it shows 790 of 1024px and slices the Circlet row in half; at **1100×700** it shows 614px and cuts
off inside the *first* artifact row, leaving **SAVE CHANGES ~400px below the visible edge with no
hint it exists**. Both card-picker overlays (builds, artifact sets) do the same thing: a third row
of cards sliced horizontally, no scrollbar.

The mid-row slice is the only cue that anything scrolls, and it is the same cue in all four
places, so it is a systemic pattern rather than one dialog's bug.

### 10. The same filter control is drawn three different ways, and is illegible on `/builds`
**Pages** `/builds`, `/teams`, `/characters`, `/weapons` ·
crop `screenshots/audit/crop_builds_filters.png`

- `/builds` — bare 20px icons, no labels, no borders. The five **weapon-type** glyphs are dark
  grey on dark navy and each carries a diagonal slash, so the row reads as *disabled* or
  *forbidden* rather than *filter by weapon type*. The `5★ 4★` filters beside them are bare text
  with no border at all.
- `/teams` — the same elements as bordered 60px tiles.
- `/characters` — bordered tiles again, plus bordered `5★ / 4★` chips.
- `/weapons` — the identical weapon glyphs, but **with their names next to them**
  (`SWORD  BOW  POLEARM  CLAYMORE  CATALYST`), which is what makes the `/builds` version legible
  by comparison and proves the labels already exist.

Four pages, four drawings of one idea. The `/builds` version is the one that fails outright.

### 11. Native and custom controls are mixed inside single panels; four checkbox styles exist
Seen in one session:

- `/optimize` — two custom card pickers, three native selects, one number input and one raw white
  native checkbox, all in the same two panels.
- `/inventory` filter bar — one custom picker (SET) and three native selects (MAIN STAT,
  EQUIPPED, SORT), with SORT flung 620px to the right of the group it belongs to, breaking one
  row into two unrelated clusters. `screenshots/audit/inventory_import.png`
- Import panel — the browser's default **"Choose File | No file chosen"** widget beside a styled
  purple button.
- Checkboxes: styled blue (build editor "I have this character"), raw white (`/optimize`
  wait-for-energy), raw white (`/teapot`, dozens of them), native blue ("Reimport builds").

Individually small; together they make the app read as three products.

### 12. A missing icon silently collapses a card and misaligns its whole row
**Page** `/artifact-sets` · crop `screenshots/audit/crop_sets_missing_icon.png`

`UI_RelicIcon_15004_4.webp` 404s (the one console error in the whole sweep). **Glacier and
Snowfield** therefore renders with no icon — and because the icon is hidden rather than reserved,
its title sits ~44px higher than every sibling in the row. The card looks like a different
component. This is the repo's own "icons hide themselves so nothing looks broken" behaviour
producing a visible layout defect, and the status code cannot catch it.

### 13. Catalogue grids waste enormous vertical space and leak internal ids
**Pages** `/artifact-sets`, `/enemies`, `/weapons`, `/my-weapons`

- Every row is as tall as its tallest card. On `/artifact-sets`, *Emblem of Severed Fate* and
  *Gambler* carry ~250px of dead space each because *Finale of the Deep Galleries* in the same row
  runs to 800px. `screenshots/artifact-sets.png`
- Every set and enemy card ends with a bare number — `15044`, `10010`, `22020201` — in muted grey
  with no label. These are nanoka ids; to a user they are noise.
- Card heights are ragged wherever a name wraps: on `/weapons` the substat line of *A Teaspoon of
  Transcendence* sits 20px below its neighbours' in the same row; same on `/my-weapons` for
  *Fleuve Cendre Ferryman*. `screenshots/weapons.png`, `screenshots/my-weapons.png`
- `/enemies` is 14,808px of cards that each repeat nine resistances at `10%`. The one value that
  differs (`anemo 50%`, `hydro 70%`, `physical 70%`) is set in the same size, weight and colour as
  the eight that do not, so nothing about the page distinguishes one enemy from another. Two
  cards named *Angelic Sea Hare* and two named *Armored Crab* sit side by side with identical
  text. There is no filter beyond the name search. `screenshots/enemies.png`

### 14. `/calculate` is a page-sized empty state that explains nothing
**Page** `/calculate` · `screenshots/calculate.png`

Before a team is chosen the page is one select and one button in the top-left corner, above
**~700px of empty viewport**. No description, no example, no "what this does". The landing page
sells it as "Every multiplier in a hit, in order, with its source — and what is *not* modelled";
the page itself says nothing at all. (700px of empty viewport under a lone control is the exact
shape of a defect this repo has already shipped once.)

The result, once run, is decent — big DPS number, per-character contribution, an honest
"Not shown:" caveat at the end. Two problems in it:

- The **REACTIONS** table lists `bloom` three times (`1`, `2.6 ±0.5`, `2`) and `quicken` twice,
  with no column distinguishing them. `screenshots/audit/calc_result.png`
- **REACTIONS** rows are 30px tall and **AURA UPTIME** rows beside them are 75px, so two adjacent
  tables in one section have wildly different rhythms and their rules do not line up.

### 15. The card-picker overlay is not attached to the field that opened it
**Pages** `/calculate`, `/optimize`, `/inventory` ·
`screenshots/audit/calc_rotation_picker.png`

Clicking the 320px **ROTATION** field opens a **1020px** panel, centred in the page, 85px *below*
the field, with no tether, arrow or alignment relating the two. In the rotation case it then shows
a single 135px option card in that 1020px panel — 85% dead space. It behaves as a modal but is
triggered like a dropdown.

---

## Smaller things worth a line each

- **Landing hero**: 430px tall, text confined to the left 40%, right 60% empty. At 1100×700 it
  plus the header consume the entire first screen, pushing "THE WAY THROUGH" — the actual
  navigation — below the fold. `screenshots/audit/landing_1100.png`
- **Nav labels do not match page titles**: `MY WEAPONS` → "WEAPONS", `SETS` → "ARTIFACT SETS",
  `TEAPOT` → "TEAPOT SETS". And two different pages are titled "WEAPONS".
- **New-rotation panel** shows *"That team has no builds yet, so there is nobody to act."* while
  the team select still reads "CHOOSE A TEAM…" — an error about a team you have not picked.
  `screenshots/rotations.png`
- **New-team dialog** labels its four members `1 2 3 4` with placeholder "Select", gives no
  portraits, no element preview and no composition feedback — while the teams list filters by
  reaction. `screenshots/audit/team_new.png`
- **Build editor field grid** does not form columns: `Character level [70]` and `Refinement [5]`
  put their inputs at different x, as do `Ascension` and `Constellation`, and row 2 has no third
  column, leaving a hole. `screenshots/audit/build_editor.png`
- **Build editor**: the character `<select>` is disabled ("A saved build keeps its character")
  but still draws a dropdown caret. And an unlabelled card showing the character sits *between*
  the WEAPON field and a hint about weapons.
- **Inventory substat bars**: 4–6px coloured bars beside each substat, plus an unexplained
  percentage (`292%`), plus `ROLL VALUE 842% / 900%` — three encodings of one idea, no legend,
  quality carried by colour alone.
- **Inventory cards** say "Equipped" but never say *to whom*.
- **`/teapot`** greys out some character chips in italics with no legend saying what grey means.
  ~~and runs three statistics together on one line separated only by spaces
  (`2,920 primogems still on the table  146 characters still to invite  0 sets done`)~~ —
  **fixed 2026-09-06** to the owner's own wording, one sentence:
  `2,920 primos available, 146 characters left, 0 sets complete`. The double space was the
  flex row's gap rather than markup, so the three spans became one.
- **`1 calibration`** floats unlabelled beside the 2-PIECE select on `/optimize`, and
  `Pick at least one set. Roughly six seconds each.` appears *below* the button it constrains.
- **`1,419,857 combinations scored`** on the optimize result is underlined like a link.
- **Icon-only buttons carry no visible label** in the rotation step list (`↑ ↓ ⧉ ×`) and in the
  move palette (grey glyphs with no text, one carrying an unexplained `×3`).

## Pages that are fine

- **`/teams`** list view reads well: clear grouping, four members per row with portrait, level,
  weapon and refinement, nothing truncated. Its only defect is the `×`.
- **`/characters`** catalogue is the best-looking page in the app — full-bleed art, consistent
  card heights, element and weapon chips in a stable position.
- **`/optimize`'s** empty state ("No saved runs yet — finish a search and save it to see it here")
  and the calculate result's closing caveat are both models of how the rest of the app should
  explain itself.
