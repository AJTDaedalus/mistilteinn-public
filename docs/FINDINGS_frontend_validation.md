# Frontend validation — ease of use and beauty

**2026-08-28.** A pass over the whole client surface, on the owner's brief: *validate the
frontend for ease of use and beauty, and find a way to get the character/weapon graphics from
nanoka the way fairy does for ZZZ.*

Branch `feat/frontend-validation`. Everything below is either **fixed** in that branch or
**left, with a reason**. The method is stated because it is the finding: the build was clean
and 418 tests passed at every point in this pass, and none of the layout faults in §3 were
visible to either. They were found by rendering the pages and looking at them.

---

## 1. The headline: production had no art at all, and nothing could tell

`/icons/*.webp` on `mistilteinn.aetherus.dev` answered **`200 text/html`** — nginx's SPA
fallback serving `index.html` for a path with no file behind it. Every `<img>` failed, and
`CatalogueIcon` hid each one *exactly as designed*. The site had been art-free since K.

Four layers behaved correctly and the compound result was silence:

| layer | did the right thing | which meant |
|---|---|---|
| `.gitignore` | kept ~10 MB of build assets out of the repo (OQ-N1) | `Dockerfile.prod`'s `COPY . .` copied a tree with no `icons/` |
| `docs/DEPLOY.md` §5a | said the download is manual and deliberate | nobody ran it on the prod box |
| nginx | served the SPA for unknown paths, as an SPA must | a missing image returned `200`, not `404` |
| `CatalogueIcon` | hid a failed load so a row survives without art | the failure had no symptom |

**The status code could never have caught this.** A basename that exists and one that does not
both return `200`; the `content-type` is the only tell. Any check built on `curl -o /dev/null
-w %{http_code}` would have reported green forever.

**Fixed** — the art is committed (446 files, 9.6 MB). The measurement that settled it: fairy
commits **207 files at 27 MB**. The rule that ignored these compared *file counts* — 475
against 207 — and concluded this set was the heavier one. It is about a third of the one
already committed a repository over. `scripts/download_icons.py` remains the reproduction and
`--check` remains the audit; `tests/unit/test_catalogue_art_is_committed.py` asks git whether
the files are tracked, so it needs no database and cannot go green by absence.
`docs/DECISIONS.md` §4 records the reversal.

## 2. The art reached only the pages nobody works on

`/characters`, `/weapons` and `/artifact-sets` — the three read-only catalogue pages — drew
icons. Builds, teams, rotations, optimize, compare and explain rendered every character,
weapon and set as bare text.

**This was never a data problem.** `BuildRead.character` is a `CharacterSummary` and has
carried `icon` since the schema was written. Nothing drew it, because no component owned the
pattern: each page decided separately whether to write an `<img>`, and the pages where the
time is spent decided no.

**Fixed** — three shared components, so a new surface reaches for one rather than making the
call again:

- `shared/icon` — the raw image, unchanged.
- `shared/token` — art beside a name, with an optional second line.
- `shared/element` — a vision as a coloured chip.

An `<option>` cannot contain an `<img>`, which is why six pages had no obvious way in. Where a
`<select>` stays, the art sits beside it as an adornment (teams' slots, rotations' steps);
`/compare` replaced its control outright.

### Element colours did not exist

Seven visions rendered as seven identical words. The palette had no tokens for them.

**Fixed**, with the distinction stated in the token block: these are **chosen, not sourced**.
Every number in this repo is cited because a fabricated multiplier is a wrong answer wearing a
right one's clothes; a hue is not that kind of claim — nothing reads these, and being a shade
off is a taste disagreement. Seven tokens and not eight: Physical is a damage type, and a
swatch beside these would draw the equivalence `models/enums.py:Element` refuses by name.

## 3. Ease of use

| finding | state |
|---|---|
| **Two nav links both read "Artifacts"** — the game's set catalogue and the caller's own inventory, distinguishable only by clicking | **Fixed.** "Sets" and "Inventory", in two groups: your work, then reference data. `/artifacts` redirects to `/inventory` |
| **`/compare` took its candidates as a comma-separated list of catalogue ids** — the one opaque-identifier input in the app, on the page whose whole job is telling weapons apart | **Fixed.** A picker over what the build's character can hold, with art. `shared/combobox` was built, tested and used by nothing; this is what it was for |
| **`/compare`'s Simulate button was enabled whenever a run was not in flight** — pressing it with no candidates did nothing and said nothing | **Fixed.** Disabled for a stated reason |
| **The landing page offered one card, to `/characters`** — while the app has a strict chain (inventory → build → team → rotation → optimize) that each page enforced only on arrival, with a "make one first" read *after* clicking | **Fixed.** The chain is numbered on the landing page, because the order is the point |
| **`/compare` rendered its full form for an account with no builds**, then explained underneath | **Fixed.** Gated up front like every other page |
| **The inventory `<h1>` said "Artifacts"** after its nav link was renamed | **Fixed** |

## 4. Beauty — what the stylesheets were actually doing

| finding | state |
|---|---|
| **`.muted`, `.hint`, `.error`, `.warn` were defined nine times**, with `#ff8080` and `#ffc966` spelled out by hand in each — so the two colours the app uses to say *something is wrong* were the only ones not in the palette and the only ones nobody could restyle | **Fixed.** One global definition on `--danger` / `--warning` |
| **`.saved` was three near-identical copies** across builds, teams and rotations | **Fixed.** One global definition |
| **The delete `×` rendered outside its own row.** `.pick` and `.drop` are both `<button>`, so both took the global button surface; the flex `li` drew them as two boxes with a gap, the × floating in the margin | **Fixed.** The row is the card; both buttons are transparent regions of it |
| **The login card was pinned to the top of a `100vh` grid**, leaving ~700px of empty viewport below it — the first screen anybody sees | **Fixed.** Centred |
| **`app.scss`'s `.brand` hover block had a rule pasted into the middle of it**, so `.brand__emblem` was being re-positioned on hover | **Fixed** |
| The landing rail wrapped its fifth numbered step alone onto a second row | **Fixed** |
| An empty artifact grid put its message inside one 200px column | **Fixed** |
| **`shared/icon-url.ts` was pure ZZZ** — `wEngineIconUrl`, `specialtyIconUrl`, `factionIconUrl` — and referenced by nothing | **Deleted.** The BRIEF's rule is to remove ZZZ concepts, not alias them |
| **`frontend/CLAUDE.md` still called the design system "inherited from fairy and not yet re-decided"** long after Chunk J decided it | **Rewritten**, with the two-accent structure and the art components documented |

---

## 5. Left, deliberately

- **Artifact set art is one basename per set, shown on every slot.** `artifact_sets.icon` is a
  single column and set icons expand per slot upstream; drawing the flower on a circlet is a
  known simplification, not an oversight. Fixing it means a per-slot column and a re-seed.
- **The artifacts page joins `/artifact-sets` client-side** rather than widening
  `ArtifactRead` with a `set_icon`. There are 65 sets and several hundred pieces; putting the
  value on every piece is the more expensive of the two. `RosterCharacter` *did* gain `icon`,
  because there the alternative was a client-side walk from team to build to character —
  which is the walk `/rotations/options` exists to prevent.
- **`shared/combobox` is still single-select.** `/compare` composes it with a chip list rather
  than making it multi-select, which keeps the component the same one the rest of the app can
  use.
- **The remaining `<select>`s were not converted to comboboxes.** Art beside the control
  solves the "which character is this" problem at a fraction of the churn, and a native
  `<select>` is better on a phone than anything hand-rolled.
- **The three catalogue pages were not restyled.** They already had art and they read fine.

## 6. How the authenticated pages were checked

`chrome-headless-shell` cannot run script before navigation, and the session token lives in
`localStorage`, so a temporary page under `frontend/public/` set the token and redirected —
same origin, one navigation, deleted afterwards. Worth recording because the obvious approach
fails silently: **the Angular dev server serves the SPA for an unknown `.html` path**, so a
newly added file in `public/` returns `index.html` until the container is restarted, and the
screenshot looks like an auth failure rather than a missing file.

A validation account (`uivalidation@example.com`) with four builds and one team was created
against the dev database to give the pages something to draw. It is dev-only and unreferenced
by anything in the tree.
