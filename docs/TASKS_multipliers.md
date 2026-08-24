# TASKS: talent multipliers, and a damage number that shows itself

**Companion:** `docs/DESIGN_multipliers.md` — read §2 (the data, counted) before M.1.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- `ruff check` and the relevant tests pass before each commit.
- Every new authed route joins the 401 sweep **in the same commit**; any API change
  regenerates `frontend/openapi.json` and leaves the contract test green.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise** — true five times out of six across the last three chunks,
  and the sixth was a guard that should not have existed.
- Frontend list loaders go through `allPages`; page sizes come from `MAX_PAGE_LIMIT`.
- Tests that read a row through an API **expire the session first**. Without it the identity
  map serves the handler and a missing eager load emits no SQL.

---

### [ ] M.0 — Branch setup **(gate)**
- **Do:** per-task branches off `dev`; merge by PR.
- **Accept:** `git log --first-parent dev` is merge commits only.

### [x] M.1 — The talent parser — **done**
- **Do:** `desc` + `param` → structured hits. A pure function over two lists; no session.
- **Files:** `app/services/talent_scaling.py`, tests.
- **Accept:**
  - all three shapes from DESIGN §2.1: `×N` keeps its count separate (OQ-M2), `A+B` sums,
    `A/B` returns **two hits** (OQ-M1). Summing a low and a high plunge would be a multiplier
    for a hit nobody can perform.
  - a `DMG` row whose param index is past the end of `param` is **refused, not defaulted** —
    a zero there is a real multiplier for a hit that does no damage.
  - non-DMG rows (`CD`, `Energy Cost`, `Duration`, the thresholds) are not mistaken for
    damage; the four format codes and five tails in the fixtures are all handled.
  - `Energy Cost|{paramN:I}` is extracted too — it is what `Character.burst_energy_cost` has
    been nullable for since Chunk D.
- **Why it is first:** every other task reads what it produces.
- **Done.** `app/services/talent_scaling.py`. Every one of the **91 promote rows** in the
  committed fixtures parses — **345 hits, no errors** — which is the test the hand-written
  cases cannot be: a parser exercised only on rows someone chose is tested against its own
  author's imagination. A second test asserts the fixtures still *contain* `×N`, `A+B` and
  `A/B`, so that sweep cannot pass by exercising nothing. Seven mutations, seven caught.

### [ ] M.2 — Resolve a hit from a build
- **Do:** `HitSpec` gains the `talent` field its own `TODO(chunk-H)` names, resolving the
  multiplier from the build's character and that talent's level.
- **Accept:** a build at talent 9 resolves level 9's row, not level 1 — the bug this is most
  likely to have; the explicit `multiplier` still works, because asking about a hypothetical
  hit is legitimate; a character with no such talent refuses with its reason. The
  `TODO(chunk-H)` markers this closes are removed in the same commit.

### [ ] M.3 — The explain page
- **Do:** pick a build, pick a talent and which of its hits, see the damage **and its
  derivation** — which `/builds/{id}/explain` already returns and nothing displays.
- **Accept:** in the nav; the multipliers that produced the number are shown, not just the
  total (DESIGN §1 A6 — a number must be able to explain itself); a failed load surfaced
  rather than rendered as a zero.

### [x] M.4 — Crossval the parse against gcsim — **done, and brought forward**
- **Do:** compare parsed multipliers against gcsim's generated `zz_*.dm.go` tables, over the
  characters both implement.
- **Accept:** a disagreement **fails**; coverage is reported; **a run that compared nothing is
  a failure, not a pass**. That last clause is the whole point — a crossval silently matching
  zero characters is the green-by-absence failure fairy shipped a stale golden fixture behind.
- **Why it matters more than an ordinary test:** DESIGN §2.2's "a damage row is one whose
  label contains DMG" is an English-language heuristic. A heuristic that agrees with an
  independent implementation across a hundred characters is not resting on the heuristic.
- **Brought forward ahead of M.2/M.3**, because until it ran the parser's correctness rested
  on my own reading of 91 rows — and M.2 and M.3 build on it.
- **It found three things immediately, and the first was a real bug.**
  1. **`A+B` was summed and should be two hits.** Venti's `1-Hit DMG|{param1}+{param1}` is two
     arrows of 0.20382; we produced 0.40764. Summing applies crit and DEF once to a doubled
     figure — *the same mistake the parser already refused to make for `×3`*.
  2. **`Elemental Mastery-Based Swirl DMG Increase` is not a hit.** gcsim's comment for it
     ends `per Point`. 50 of the catalogue's 430 `DMG` labels are bonuses, shields,
     reductions or per-point coefficients, and all are excluded now.
  3. **A repeat binds to the alternative it follows.** M.1 refused `{a}/{b}/{c}×3` rather than
     guess; gcsim models Clorinde's three lunges as three tables of which only the third
     repeats, which answered it.
- **Result: 105 characters, 18,611 hits, 0 mismatches, 0 refusals.** The committed test runs
  the same comparison over the fixtures with no database and no clone, so it cannot skip.
  Four mutations against the comparison itself, all caught — including "a run that compared
  nothing reports success".

---

## Open questions

- ~~**OQ-M1**~~ **Answered in DESIGN §8: a `/` row is two hits, and the caller picks.**
- ~~**OQ-M2**~~ **Answered in DESIGN §8: `×3` is one hit with a count, not a tripled multiplier.**
- ~~**OQ-M3 — what happens when gcsim and nanoka disagree?**~~ **It did not arise, and that
  is the answer for now.** Every one of the 18,611 comparable hits agrees exactly. The three
  apparent disagreements were all *ours*: a summing bug, a label that is not a hit, and a
  shape M.1 had refused to guess at. Where gcsim has no table for a row we parse, that is
  recorded as coverage rather than disagreement — 2,944 such hits — because gcsim does not
  model every published row.

## Not in this chunk

Constellation and passive effects on multipliers, reaction/infusion inference, the optimizer
UI, and non-English locales. DESIGN §7 says why for each.
