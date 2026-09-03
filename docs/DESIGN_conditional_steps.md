# DESIGN — conditional steps in a rotation

**Status:** built 2026-09-02, the import half. `group` is a path, `group_condition` rides
beside `group_repeat`, the compiler emits nested `if` blocks and the parser reads them back.
The owner's config (`gcsim.app/db/bgHjR7MP7Fkn`) imports as **180 steps, 12 guarded**, and
the round trip is stable: import, compile, import again returns identical steps.

**OQ-C1 is still open** — nothing authors a condition in the builder yet, so a guarded
rotation can be imported and edited around but not written from scratch. **OQ-C2 is answered**
(2026-09-02): a guard does not break the ladder's monotonicity, it compresses the ER signal,
and the compression is the honest score of the rotation as written. OQ-C3 (a general `else`)
is still open.

## Branch policy

`feat/conditional-steps`, off `dev`. **No direct commits to `dev` or `main`** — merged by PR
after review like every other feature. Task 0 of the TASKS file is the branch-setup gate.

## The ask

Owner, 2026-09-02, on a real community config (`gcsim.app/db/bgHjR7MP7Fkn`):

> *"We need a way to express this in our rotation"*

Four constructs were refused. **Three needed no model change** and are fixed in #233: the
`is_even(i)` branches are arithmetic and unroll into explicit cycles, and an
`if .x.burst.ready { A } else { A-minus-burst }` *is* a gated step. What is left is one block:

```
if .flins.status.manifest-flame {
  flins skill;
  if .flins.energy >= 30 {
    flins burst;
  }
}
```

A status guard with a nested energy threshold. Neither is statically resolvable and neither
reduces to readiness.

## The decision this design exists to make

The cheap model is a **condition per step**, ANDed:

| step | conditions |
|---|---|
| `flins skill` | `status.manifest-flame` |
| `flins burst` | `status.manifest-flame`, `energy >= 30` |

emitting `if A { skill; } if A && B { burst; }`.

**It is wrong, and this config is the proof.** gcsim evaluates a block's condition **once, on
entry**; the flattened form evaluates `A` again before the burst. And `A` changes in between —
`internal/characters/flins/skill.go:56` is `c.DeleteStatus(skillKey)`, so **Flins's skill
deletes the very status the block is guarded on**.

So under flattening the burst would never fire, the import would succeed, and the rotation
would carry the author's name and simulate to a different number. That is precisely the
failure `rotation_parser` refuses configs to prevent, arrived at by a different road.

**Conditions are therefore blocks, not step fields.** Evaluated once on entry, and nestable.

## Shape

The model already has `group` and `group_repeat` carried on every member of a run. Conditions
extend the same idea rather than adding a second grouping concept:

- `group` becomes a **path** — `"flame"`, `"flame/energy"` — so nesting is expressible without
  the field changing type. A step's path names every block it is inside, outermost first.
- `group_condition` is carried per member like `group_repeat` is, and the schema requires the
  members of a block to agree.
- The compiler walks the path and emits nested `if`s, one per segment, in order.
- The parser reads nested `if` blocks into paths, and **still refuses a condition it cannot
  read** — the vocabulary below is a subset, and everything outside it is named rather than
  approximated.

## The condition vocabulary

Only what gcsim publishes and this repo can round-trip:

| form | example |
|---|---|
| readiness | `.flins.burst.ready` |
| energy | `.flins.energy >= 30` |
| status | `.flins.status.manifest-flame` |

**Deliberately not included:** arithmetic on the loop index (resolved by unrolling, #233),
`is_even`, user-defined functions, and anything comparing two characters. Each is refused by
name. A grammar that accepts what it cannot faithfully re-emit is how a rotation silently
becomes a different one.

## Open questions

**OQ-C1 — does the builder author these, or only import them?** A condition is the first part
of a rotation that is not a list of moves, and the builder's whole argument is that gcsim's
syntax is the wrong authoring surface. Importing them while offering no way to write one is a
defensible first step and should be a deliberate choice rather than an omission.

**OQ-C2 — what does a conditional step do to the energy ladder? — ANSWERED 2026-09-02. It does
not break monotonicity; it compresses the signal, and it does so for a reason worth keeping.**

Measured on the owner's own config, which carries exactly the guard in question, against a
control that is the same config with the threshold dropped to `>= 0` so the block's shape can
no longer depend on ER. `ENERGY_LADDER`'s six rungs, 60 iterations, subject `flins`:

| flins ER | 0.20 | 0.30 | 0.45 | 0.60 | 0.80 | 1.00 | span |
|---|---|---|---|---|---|---|---|
| **guarded** (`>= 30`) DPS | 126,250 | 134,219 | 136,696 | 137,883 | 137,632 | 137,352 | **+8.8 %** |
| guarded duration | 133.2 s | 116.2 s | 117.0 s | 117.2 s | 117.0 s | 117.1 s | |
| **control** (`>= 0`) DPS | 111,218 | 130,378 | 137,056 | 137,123 | 137,412 | 137,315 | **+23.5 %** |
| control duration | 208.2 s | 122.9 s | 116.9 s | 117.2 s | 117.3 s | 117.1 s | |

**Monotonicity survives.** Every reversal in both curves is between 0.07 % and 0.20 %, which is
the noise floor of a 60-iteration mean already documented on `dpsAt` (0.12 % and 0.14 % there).
The rung spacing needs no change and the running maximum is safe. That half of the question is
closed and the answer is *nothing to do*.

**The shape does change, and only at the bottom.** Above 0.45 the two curves agree to within
noise — 136,696 against 137,056, and so on. The whole difference is the first rung: guarded
gives 126,250 at 133.2 s where the control gives 111,218 at **208.2 s**. The guard is doing
precisely its job there, skipping a burst the character cannot fund instead of standing still
for seventy extra seconds waiting for it.

**So an energy guard is a local skipping model inside a waiting-model run**, and it
under-prices ER by the same mechanism and for the same reason: *a skipped action costs no
time*. The rotation reports ER as worth a third of what the unguarded one does.

**That is not an artifact to correct.** `DESIGN_waiting_for_energy.md` establishes waiting as
an option because a player at a keyboard waits; a `.energy >= 30` guard is an author saying, in
this one block, that they would rather skip. The lower number is the honest score *of the
rotation as written*. What matters is that it is not mistaken for a fact about the character —
which is why it is recorded here rather than left for someone to rediscover as a discrepancy
between two rotations for the same team.

**OQ-C3 — `else`.** #233 reduces the one `else` shape that is a gated step. A general `else`
needs a second block on the same condition, and nothing in this design covers it yet.
