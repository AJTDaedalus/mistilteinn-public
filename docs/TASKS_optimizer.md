# TASKS: the optimizer surface

**Companion:** `docs/DESIGN_optimizer.md` — read §2 (the one thing the browser cannot work out
for itself) before O.1.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- **Run each gate standalone and check its exit code.** Not chained behind `&&`, not piped
  through `tail`. M.2 merged a lint failure because a `&&`-chained commit short-circuited and
  the next line printed something that looked like success.
- Lint with **CI's own argument list**, not `ruff check app/ tests/`.
- Every new authed route joins the 401 sweep in the same commit; any API change regenerates
  `frontend/openapi.json` and leaves the contract test green.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise** — true seven times out of nine across this session.
- Frontend list loaders go through `allPages`; page sizes come from `MAX_PAGE_LIMIT`.
- Tests that read a row through an API **expire the session first**.

---

### [ ] O.0 — Branch setup **(gate)**
- **Do:** per-task branches off `dev`; merge by PR.
- **Accept:** `git log --first-parent dev` is merge commits only.

### [ ] O.1 — The search context
- **Do:** `POST /builds/{id}/search-context` — base contributions, set bonuses, target,
  character level, damage-bonus quantity, and the hit resolved from a named talent (M.2).
  Everything the kernel needs except the inventory.
- **Accept:** the context agrees with what `/explain` computes for the same build and hit —
  **the same server, asked twice, must not disagree with itself**; a build with no character
  or no talent level is refused with its reason; the route is in the 401 sweep.
- **Why it is first:** O.3 has nothing to search without it.

### [ ] O.2 — Kernel-ready inventory
- **Do:** `GET /artifacts/inventory` returns candidates — id, slot, set id, and `stats`
  already translated by `_quantity_for_prop` — rather than `ArtifactRead` (OQ-O1).
- **Accept:** every piece's stats round-trip against the mapping; **a prop the mapping refuses
  is reported, never dropped** (OQ-O2) — a silently omitted piece is an inventory the user
  cannot see is incomplete; the ETag still changes when and only when the inventory does.
- **Why not the client's job:** `_quantity_for_prop` decides what every stat *means* and
  refuses rather than guessing. A TypeScript copy would be a second definition of that, and
  the failure is silent: a mis-mapped substat optimises for a stat the character does not have.

### [ ] O.3 — The optimizer page
- **Do:** pick a build, pick a hit, run `search()` **in the browser**, show the top N.
- **Accept:** reachable from the shell nav — `app.routes.spec.ts` fails otherwise; the page
  runs the real kernel over a known inventory and picks the known winner; **`isExact`,
  `evaluated` and `paretoRemoved` are displayed** (DESIGN §3.2) — a search over 40
  combinations and one over 4 million look identical when only the winner is shown.

### [ ] O.4 — Explain the winner
- **Do:** hand the winning five to `POST /builds/{id}/explain` via `artifact_ids`.
- **Accept:** the explained damage equals the search's damage for that combination, **within
  the f32/f64 divergence C.2 measured (3.4e-07)** — outside it is a real disagreement between
  two implementations of the chain, not a rounding artefact.
- **Why it closes the chunk:** a ranking whose winner cannot be explained is a ranking nobody
  can verify. This is the reason M.3 came before it.

---

## Open questions

- ~~**OQ-O1**~~ **Answered in DESIGN §6: the snapshot returns kernel-ready candidates.**
- ~~**OQ-O2**~~ **Answered in DESIGN §6: a refused prop is reported, never dropped.**
- ~~**OQ-O3**~~ **Answered in DESIGN §6: top N, defaulting to 10.**

## Not in this chunk

Rotation optimization, constraint editing, the GPU path in the page, and saving a search
result. DESIGN §5 says why for each.
