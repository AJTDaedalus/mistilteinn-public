# TASKS: artifacts

**Companion:** `docs/DESIGN_artifacts.md` — read §2 (what the backend already has) before A.1.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- `ruff check` and the relevant tests pass before each commit.
- Every new authed route joins the 401 sweep **in the same commit**.
- Any API change regenerates `frontend/openapi.json` and leaves the contract test green.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise** — that was true all three times it happened in the last chunk.
- Frontend list loaders go through `allPages`; page sizes come from `MAX_PAGE_LIMIT`.

---

### [ ] A.0 — Branch setup **(gate)**
- **Do:** per-task branches off `dev`; merge by PR.
- **Accept:** `git log --first-parent dev` is merge commits only.

### [x] A.1 — Equipping — **done**
- **Do:** `PATCH /artifacts/{id}` setting `build_id`, and clearing it to unequip.
- **Files:** `app/schemas/artifact.py`, `app/api/v1/artifacts.py`, tests.
- **Accept:** equip, unequip, and three refusals — a build that is not the caller's (answered
  as absent, not as forbidden), a slot already filled on that build (**422 naming the piece
  that holds it**, per OQ-A2), and an artifact that is not the caller's. Each CAUGHT under
  `scripts.inject`.
- **Why it is first:** nothing sets `build_id` today, so an imported inventory cannot be
  attached to anything. It gates A.4 and, next chunk, the optimizer writing its result.
- **Done.** `PATCH /artifacts/{id}` takes **only** `build_id` — an artifact's
  `main_stat_value` is *derived* from the committed value table, and a patch accepting `level`
  would let the one number this repo derives be typed in by hand. Five mutations run: four
  CAUGHT, and the fifth exposed a guard that was **removed rather than tested** — see the LOG.
- **`ArtifactSlot.value` is `equip_bracer`**, so the refusal read "already has a equip_bracer
  equipped". `display` moved onto a shared `SourceSpelled` base that `WeaponType` and
  `ArtifactSlot` both inherit, rather than being written twice.

### [x] A.2 — The GOOD import form — **done**
- **Do:** a page that takes a GOOD file and posts it, and renders the result in full.
- **Accept:** `mode` is **chosen, never defaulted** — `replace` and `append` are different
  intentions and GOOD has no stable per-artifact id to merge on, so a default would be the UI
  deciding whether to delete an inventory. Every rejection is listed with its reason; a
  409 from a `replace` that resolved nothing is shown verbatim; a failed load is surfaced
  rather than rendered as "no artifacts".

### [x] A.3 — The inventory — **done**
- **Do:** the list — every piece, filtered by slot and set, equipped ones marked (OQ-A3).
- **Accept:** filters are the **server's** (`GET /artifacts` already takes `slot`, `set_id`,
  `equipped`); `total` matches what the filter returned; the list goes through `allPages`.
- **Why with A.2:** an import form with nothing to show afterwards cannot be checked by the
  person using it.
- **Done, with a backend half the design did not anticipate.** `slot`, `rarity` and
  `main_stat_type` are all source spellings, and the stored values are **units-dependent** —
  `4780.0` flat HP against `0.466` HP%. `GET /artifacts/options` publishes the vocabulary
  once (26 stats with `display` + `percentage`, 5 slots in worn order, 5 rarities with
  `stars`); `ArtifactRead` gains `set_name`, which is per-piece. `StatType.display` is
  **derived** from the member name rather than a 26-entry table, and `is_percentage` is
  checked against the committed value table rather than trusted.
- Twelve mutations run; two survived and both were tests that could not distinguish — a
  five-star-only fixture, and a redundant re-read. See the LOG.

### [ ] A.4 — The build's artifact panel
- **Do:** five slots on the build editor, each showing the equipped piece or offering the
  inventory filtered to that slot.
- **Accept:** the picker offers only pieces that would be accepted — right slot, not already
  equipped elsewhere — the picker-matches-validator guarantee this repo now applies
  everywhere; equipping and unequipping both work from here.

### [ ] A.5 — Upgrade potential **(closes G.9)**
- **Do:** the scoring function over `app/data/yuanshen/snapshot/artifact_roll_schedule.json`,
  returning **the parts, not just a figure**: rolls remaining, which substats can still grow,
  and the level the piece would reach.
- **Accept:** a 4-star and a 5-star at the same level differ (their schedules differ); a maxed
  piece has zero potential; the schedule is *read*, not restated — deleting a rarity from the
  JSON fails a test rather than silently defaulting.
- **OQ-A1 is answered:** with no build there are no substat weights, so this is **potential,
  not value**. A build-relative score arrives with the optimizer, where the weights come from.

### [ ] A.6 — Showing it
- **Do:** the potential beside each piece in the inventory.
- **Accept:** the parts are visible, not only a number — a score whose derivation is hidden is
  the "confident number computed for something else" failure with better presentation.

---

## Open questions

- ~~**OQ-A1**~~ **Answered in DESIGN §6: potential, not value — no build means no weights.**
- ~~**OQ-A2**~~ **Answered in DESIGN §6: equipping into a filled slot refuses, naming the holder.**
- ~~**OQ-A3**~~ **Answered in DESIGN §6: equipped pieces are shown, marked.**

## Not in this chunk

Manual artifact entry, editing imported pieces, the optimizer UI, and artifact art.
DESIGN §5 says why for each.
