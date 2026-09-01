# DESIGN: the full-site frontend audit

**Owner brief, 2026-08-31.** *"A full-site front-end audit. Areas of focus: ease of
use/navigation, removing AI slop/overly verbose text, colour/design adherence to the Mitya
theme (without going overboard), missing features we've discussed before, and anything else
front-end you find that needs fixing. Also check our backlog and ensure everything we've
marked has been implemented, even if it was deferred."*

## Branch policy

Work happens on `feat/frontend-audit` and sub-branches per chunk; **no direct commits to `dev`
or `main`**, which are updated only by reviewed PR. Task 0 in `TASKS_frontend_audit.md` is the
branch-setup gate.

## Method — what was actually looked at

Three passes, none of them impressionistic:

1. **Every route rendered and read.** `python -m scripts.shoot` over the SPA, PNGs read
   directly. Dialogs are invisible to that harness, so the rotation builder and the team
   editor were driven with Playwright.
2. **Prose measured, not eyeballed.** Tags, bindings, control flow and comments stripped from
   every template; the remainder counted. **1,478 words across 22 templates.**
3. **Both backlogs re-read against the tree**, marking each item implemented / open / stale.

## Findings

### A. Navigation and naming

| | |
|---|---|
| **A1** | The landing page advertises an **Explain** card; the nav says **Calculate**; `/explain` is a `redirectTo: 'calculate'`. One feature, two names, and the name a new user meets first is the one that no longer exists. |
| **A2** | **`/compare` is not a route** — it was removed on the owner's ruling. It resolves through the `**` catch-all to the landing page. |
| **A3** | `CLAUDE.md` says the SPA has *"17 routes plus a catch-all"*. It has **14 routes, 2 redirects and a catch-all**. |

### B. Theme adherence

The palette itself is not the problem — `_tokens.scss` is sampled from the references and
`check:tokens` keeps it honest. The problem is **two control vocabularies on one page**.

| | |
|---|---|
| **B1** | Native `<select>` survives where `shared/card-picker` is the house style: the four **team slots**, the teams **reaction filter**, and optimize's **objective** and **rotation** pickers. `BACKLOG_frontend.md` §1 says the card-grid picker *"applies everywhere"*; these are what is left. On `/optimize` a brass-bordered uppercase card-picker sits directly beside a lowercase browser `<select>`. |
| **B2** | **Enemy level** is a bare number input in the same row as two card-pickers. |

*Not* in scope: restyling for its own sake. `/builds` is the reference for what right looks
like — card grid, art, element badge, real denominators — and the work is bringing the
stragglers to it, not inventing a third style.

### C. Verbosity

| | |
|---|---|
| **C1** | **`/optimize` carries 417 of the app's 1,478 words** — 28 % of all visible prose, and nearly triple the next page. The owner has already asked for *"less is more"* here twice. |
| **C2** | `1 calibration(s)`. |

### D. Defects found by looking

| | |
|---|---|
| **D1** | **Teams: the "delete team" `×` renders beside an arbitrary member row.** It is `[aria-label]="'Delete ' + team.name"` and it deletes the whole team, but it is vertically centred in a four-member card, so it lands next to whichever member happens to be level with it. A user removing Bennett from a team deletes the team. Same shape as the delete-button defect `FINDINGS_frontend_validation.md` already records. |
| **D2** | **Teams: the "New team" form is permanently inline**, occupying the left half of the viewport and roughly 300 px of a 1,200 px column, with the rest empty. |

### E. The backlogs, re-checked

| item | state |
|---|---|
| `BACKLOG_frontend.md` §4 — "New Team" becomes a button with a pop-up builder | **open** (D2) |
| §3 — one build per character, Build Priority, artifact stealing | **open**, owner-deferred; the brief says deferred items count |
| §11 — "sets and enemies are broken" | **still unreproduced.** Both routes render and answer 200. One benign console 404 on `/artifact-sets` for a set icon nanoka does not publish |
| §1 — the shared card-grid picker | **built and partly adopted**; B1 is the remainder |
| `BACKLOG_optimize.md` §8 — *"Open: the number"* | **stale text.** `energySweep` is passed, `minimumEnergyRecharge` is read by `energyShortfall`. The doc says it is open; the code says otherwise |

### F. The harness is blind in four places

**`scripts/shoot.py`'s route list has drifted from `app.routes.ts`.** It screenshots
`/compare` (gone — it captures the landing page and files it under `compare.png`) and
`/explain` (a redirect), and it **never visits `/calculate`, `/my-weapons`, `/login` or
`/pending`**. Two of those are in the main nav. A visual harness that silently photographs the
wrong page is worse than one that errors, and this is the repo whose lesson is that rendering
a page and looking at it is the check nothing else performs.

## Order of work

Defect first, then the harness that would have caught it, then the cheap correctness items,
then the design work, then the deferred feature.

1. **D1** — the destructive control.
2. **F** — route list derived from `app.routes.ts` rather than repeated, so it cannot drift.
3. **A1, A3, C2** — naming and counts.
4. **B1, B2** — card-picker adoption.
5. **D2 / §4** — the teams pop-up builder.
6. **C1** — the optimize prose pass.
7. **§3** — one build per character and Build Priority.
