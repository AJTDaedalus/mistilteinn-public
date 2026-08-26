# TASKS: porting weapon passives from gcsim's Go

**Companion:** `docs/DESIGN_passive_port.md` — read §3 (the primitives already exist) and §6
(the port is proved, not trusted) before starting.
**Decision:** `docs/DECISIONS.md`, 2026-08-26. **Evidence:** `docs/RESEARCH_gcsim_speed.md`.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**

- Verify `git branch --show-current` before every commit. **`gh pr merge --delete-branch`
  checks out `dev`** — branch immediately after a merge, before anything else. That is exactly
  how W.6 landed on `dev` unreviewed.
- **Run each gate standalone and check its exit code.** Not chained behind `&&`, not piped
  through `tail`.
- Lint with **CI's own argument list** — copy the `run:` line out of
  `.github/workflows/test.yml`.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise.**
- **Cite the gcsim source path and the pin for every ported passive.** A coefficient without
  one is indistinguishable from a remembered one, which is the failure this whole approach
  exists to avoid.
- **Never transcribe a coefficient without a crossval case behind it.** Reading Go removes the
  derivation risk, not the typo risk: `.21 + 0.07*r` mistyped is as wrong as an invented
  number and looks exactly as plausible.

---

### [ ] P.0 — Branch setup **(gate)**
- **Do:** branch `feat/passive-port` off `dev`.
- **Accept:** `git branch --show-current` is not `dev` or `main`.

### [ ] P.1 — Survey gcsim's weapons and tier them for real **[Planner]**
- **Do:** read gcsim's `internal/weapons/**` at the pin and classify every weapon by the
  primitives it needs, not by its English text.
- **Accept:** a table in `docs/RESEARCH_passive_tiers.md` — per weapon, the gcsim source path
  and which of Tier 1 / 2 / 3 it lands in, with the primitive it needs named.
- **Why this is not N.5's tiering:** that was regex over refinement prose, an explicit
  **proxy**. This reads the implementation. **Expect the numbers to move**, and say by how
  much — N.5's "20 static" is the thing being checked, not the thing being assumed. (OQ-P4)

### [ ] P.2 — The passive record, and one evaluator **[Planner]**
- **Do:** design the record shape — effects, conditions, refinement scaling as `base + step*r`
  — and the single evaluator that reads it. Settle **OQ-P1** (where records live).
- **Accept:** the shape expresses `The Stringless` **and** `Redhorn Stonethresher` with no
  weapon-specific code path, written out in the DESIGN before any of it is built.
- **The constraint that decides this:** 260 weapons must not become 260 branches. DESIGN §1 A6
  binds weapons the same way it binds characters.

### [ ] P.3 — The evaluator, over Tier 1
- **Do:** implement the evaluator and the Tier 1 records.
- **Accept:** `Redhorn Stonethresher` produces a DEFP stat mod **and** flat damage of
  `TotalDEF × (0.3 + 0.1r)` on normal and charged hits only, via `Hit.flat_damage`. Every
  coefficient cites `internal/weapons/claymore/redhorn/redhorn.go` at the pin.

### [ ] P.4 — Crossvalidate every ported passive
- **Do:** a committed gcsim run per ported weapon, recomputed by this chain.
- **Accept:** each matches inside the tolerance `docs/CROSSVAL_gcsim.md` argues, and CI runs it
  with `CROSSVAL_REQUIRE_DB=1` so a skip is a failure. **A passive with no crossval case is
  not ported, it is claimed** — and P.4 is what makes P.3 true rather than plausible.

### [ ] P.5 — Wire it into the search, and report what is still missing
- **Do:** the artifact search applies Tier 1 passives; unported weapons are **named**.
- **Accept:** a search for a `Redhorn Stonethresher` build **considers DEF pieces**, proved by
  a test that fails against today's chain. Settle **OQ-P2** and **OQ-P3**.
- **This is the task the whole plan is for.** Everything before it is groundwork; a port the
  optimizer does not read changes no answer a user sees.

---

## Open questions

**OQ-P1** where the records live (P.2) · **OQ-P2** unported weapons in the optimizer (P.5) ·
**OQ-P3** whether a Tier 3 weapon's search is refused or flagged (P.5) · **OQ-P4** the real
size of Tier 1 (P.1).

## Not in this chunk

- **Tier 3 — target-state passives.** `KernelTarget` cannot express aura, enemy type or weak
  spots. Those are unaskable questions, and growing the target model is its own decision.
- **Making gcsim faster.** `RESEARCH_gcsim_speed.md` put the ceiling at ~4× against a ~8,900×
  gap. The stats-collector fork is unmeasured and remains available for the **comparison
  page**, which is a different problem with a different budget.
- **Replacing the gcsim comparison tier.** It ships, it works, and it is the oracle this port
  is checked against. Porting Tier 1 does not retire it.
