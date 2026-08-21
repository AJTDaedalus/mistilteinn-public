# Crossval against gcsim

gcsim is this project's oracle for damage numbers and its **citation target** for every
game constant. This file pins the version those citations point at and records the rules
that make a comparison meaningful.

Read `docs/DECISIONS.md` first if you are wondering why the code does not look like gcsim's:
gcsim is the reference for *correctness and feature scope*, deliberately not for structure
(DESIGN §1 A6).

## The pin

| | |
|---|---|
| **Repository** | `github.com/genshinsim/gcsim` |
| **Commit** | `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa` |
| **Dated** | 2026-08-14 |
| **Title** | `Add Stellar-Conduct (#2711)` |
| **Pinned** | 2026-08-21, Chunk F |

**A citation names a file, a line range, and this commit.** A citation that names only a
file is a citation to a moving target: gcsim refactors, and "see `pkg/core/attributes`" ages
into "see wherever that went". Re-pinning is a deliberate, reviewed step that re-checks the
citations it invalidates — the same rule the YuanShenResources snapshot follows.

## What has been cited so far

| Constant or rule | Source at the pin | Used by |
|---|---|---|
| stat vocabulary | `pkg/core/attributes/stats.go:12-40` | `formula/genshin/tags.py` |
| `MaxHP`/`TotalATK`/`TotalDEF` are **single-stage** | `pkg/core/attributes/stats.go:44-46` | `formula/genshin/stats.py` |
| element list | `pkg/core/attributes/element.go:13-27` | `formula/genshin/tags.py` |
| attack-tag (scope) list | `pkg/core/attacks/attack.go:5-20` | `formula/genshin/tags.py` |
| strike types | `pkg/core/attacks/attack.go:52-59` | `formula/genshin/tags.py` |

Extend this table in the same commit that adds the citation. A constant whose row is missing
here is a constant nobody can re-check.

## Tolerance

**Not yet set — F.8 sets it, with its justification, and this section is where it goes.**

The number will not be zero and the reason is structural: gcsim simulates a rotation frame
by frame with its own rounding at each step, while this project evaluates a single
configured hit. What has to be argued is *why* a given tolerance is small enough that a real
formula error could not hide inside it. "It matched to 3 decimal places" is a measurement,
not a justification.

## The rule that is pre-paid

`CROSSVAL_REQUIRE_DB=1` makes a skipped crossval level a **hard failure** from the first
commit of the harness (F.7), not a retrofit.

fairy's crossval suite was green-by-absence on CI for months — the DB it needed was not
there, the levels skipped, and the summary said green — and it shipped a stale golden
fixture on the strength of it. That is the single most expensive bug in this project's
lineage, and it is the reason this paragraph exists before the harness does.
