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
| **B.1 — Build Priority** | Next. `optimizer_priority` exists on `Build`, indexed, and **nothing reads or writes it** — the fifth subsystem in this repo built and wired to nothing. Needs schema exposure, a reorder endpoint, drag-to-reorder UI |
| **B.2 — artifact stealing** | Follows B.1. The optimizer currently *refuses* a piece held elsewhere; with a ranking it can take it from a lower-ranked build and say so |
| **B.3 — one build per character** | **Blocked on an owner decision.** The local data has two Skirk builds and three Xingqiu builds; a uniqueness constraint needs a migration that deletes or merges builds that already exist |
| **B.4 — `/optimize` prose** | Three explanatory paragraphs are genuinely long. The rest of that page's 417 words are conditional empty states that say what to do, and cutting those would cost more than it saves |
| **B.5 — §11 "sets and enemies are broken"** | **Blocked on detail.** Both routes render and answer 200. Needs: did the link do nothing, or did the page load and its cards do nothing? |
