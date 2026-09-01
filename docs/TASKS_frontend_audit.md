# TASKS: the frontend audit

**Status, 2026-08-31.** Findings and method are in `DESIGN_frontend_audit.md`. Order of work is
that doc's closing section; this file tracks what landed.

## Done

| task | what |
|---|---|
| **A.1** | Teams' delete `×` pinned to the row title. It stretched to card height and centred beside an arbitrary member, so removing Bennett deleted the team |
| **A.2** | `scripts/shoot.py` derives its routes from `app.routes.ts`. It photographed `/compare` (removed) as the landing page, `/explain` (a redirect), and had never seen `/calculate` or `/my-weapons` |
| **A.3** | One name for one feature — the landing card said "Explain" where the nav says "Calculate" |
| **A.4** | Seven `(s)` plurals replaced with real ones |
| **A.5** | `/optimize`: objective is chips, rotation is `mist-combobox`. `.chip--on` was scoped to `.slot-stats`, so the new chips had **no active state at all** |
| **A.6** | `CLAUDE.md`'s four counts re-derived; `BACKLOG_optimize.md` §8 closed — the code had closed it already |
| **A.7** | Teams builder is a `<dialog>` (§4). Saved teams take the full width; the editor dialog is shared rather than copied a third time |
| **A.8** | One placeholder convention per dialog on `/builds` |

## Open

| task | why it is not done |
|---|---|
| **B.4 — `/optimize` prose** | **Examined and declined.** The 417-word figure was a measurement artifact: it counts every conditional branch as though all rendered at once, when most are empty states that appear one at a time and say what to do. The three long passages each carry information needed to trust a number — *"a swap that would drop you below four of the set is scored without the set bonus"* is not obvious and is what makes the ranking believable. The genuine slop on that page was the `(s)` plurals, now fixed. Recorded as declined rather than left open, because an item that reads as pending work when it was decided is the same failure as §8 reporting finished work as open |
| **B.5 — §11 "sets and enemies are broken"** | **Blocked on detail.** Both routes render and answer 200. Needs: did the link do nothing, or did the page load and its cards do nothing? |

## Done since

| task | what |
|---|---|
| **B.3** | **Closed by owner ruling, `DECISIONS.md` §31** (2026-09-01): *"Convention is to keep T1.a, because each user's account only has one of each character."* §3 asked to reinstate the uniqueness constraint T.1a dropped; the ruling stands, so nothing is built and nothing reverted. An account holds one copy of a character, so two builds of it are hypotheticals about one owned character rather than two equippable things — and pieces are contested *between* characters, which is what #212's ranking already orders |

| task | what |
|---|---|
| **B.1** | Build priority. `PUT /builds/priority` takes the whole order; `optimizer_priority` reaches the API for the first time since the column was added. A short ranked list with drag **and** arrows, not a draggable 75-card grid |
| **B.2** | The optimizer takes a contested piece when this build outranks the holder, names whose it was, and refuses — naming them — when it does not. An **unranked build takes from nobody**: without a rank there is no claim, and preferring whichever build is open is the surprise a ranking exists to remove |
