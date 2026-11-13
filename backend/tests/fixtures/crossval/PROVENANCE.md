# gcsim crossval fixtures

Each case is a **gcsim config** and the **JSON gcsim produced from it**, both committed
verbatim. The harness in `backend/tests/crossval/` recomputes the same build through this
repo and compares.

| | |
|---|---|
| **Oracle** | `github.com/genshinsim/gcsim` |
| **Commit** | `b107b5dc5cb88977bed5270e5d83e64934730d4d` — the pin in `docs/CROSSVAL_gcsim.md` |
| **Recorded** | 2026-08-21, task F.7 · regenerated 2026-08-31, 2026-09-19 and 2026-11-13, each at the new pin |

**The 2026-11-13 re-pin to `b107b5dc` (v2.50.0) changed one field: `sim_version`.** 76 Go
commits, including an engine change to hitlag and gcsim's whole performance series, and both
cases — `ayaka_normal_1` and `traveler_normal_1` — regenerate identical in every other field
after stripping the per-run noise. Totals **108.53039935232651** and **117.49423396988159**,
unchanged to the last digit; `_nocrit` agrees. Diffed field by field, not eyeballed.

**The 2026-09-19 re-pin to `caf738dc` (v2.47.2) changed two fields, and neither is a
number.** `sim_version`, and a new `target_details[].particle_element` of `"none"` —
gcsim `61f578730` renumbered its element enum and gave the empty element a name. Every
damage figure and every statistic is byte-identical, and the total is still
**108.53039935232651**. Diffed field by field after stripping the per-run noise, not eyeballed.

**The earlier re-pin from `3647a07a` changed nothing but `sim_version`.** Regenerated through the
recipe below and diffed field by field after stripping the per-run noise: every damage
figure, every statistic and the embedded config are byte-identical. That is the result a
re-pin should produce for a case chosen to isolate the damage chain, and it is recorded
because "the oracle did not move" is only worth anything if someone checked.

The JSON carries its own provenance: `sim_version` is the commit that produced it and
`modified` says whether the working tree was dirty. **The harness asserts both**, so a
fixture generated from a patched or unpinned gcsim cannot pass as an oracle.

## Regenerating

Not automated, and deliberately so — the same rule the YuanShenResources snapshot follows.
A regenerated oracle is a new claim about what is correct, and it should arrive as a
reviewable diff rather than as a side effect of running the tests.

```bash
# gcsim is not vendored: it is a 35 MB Go binary and building it needs a Go toolchain.
CASES=$(pwd)/backend/tests/fixtures/crossval      # run this from the repo root
git clone https://github.com/genshinsim/gcsim /tmp/gcsim && cd /tmp/gcsim
git checkout b107b5dc5cb88977bed5270e5d83e64934730d4d
go build -o gcsim ./cmd/gcsim
./gcsim -c "$CASES/ayaka_normal_1.txt" -nb -out "$CASES/ayaka_normal_1.json"
```

The config lives in this directory and not in the clone, so the paths have to be absolute —
the first version of this recipe `cd`-ed into the clone and then named the config by its bare
filename, which fails with "no such file". A regeneration recipe that does not run is worse
than none, because it reads as though the oracle is reproducible on demand.

**Strip the per-run noise before committing**: `sample_seed`, `build_date`, every
`statistics.*_seed` field, and `statistics.dev_debug.seeded_dps[].seed`. All change on every
run and carry no information, and leaving them in makes the fixture diff on every
regeneration — including regenerations done for an unrelated case. (The first version of
this note claimed two fields were enough; six more were still in the file.)

## The cases

### `traveler_normal_1` — the same shape, for the story buffs

Pyro Aether 90/6, **Dull Blade** 70/4, no artifacts, one normal attack: deliberately the
same minimal shape as the case below, so the tolerance argued there applies unchanged
rather than needing a new one.

**It exists because gcsim gives every Traveler three permanent story-quest buffs by
default** (`storybuffs.go:26-57`) and this repo modelled none of them until 2026-09-19.
The case pins them where they are visible without any curve in the way: crit rate
**0.15**, crit DMG **0.7** and energy recharge **1.2** are each only correct if a buff
landed — an unbuffed Traveler reads 0.05, 0.5 and 1.0 — and they are asserted exactly.

It is also the harness's **first non-zero elemental mastery** (75 = 15 from Skirk's story
quest + 60 from True Moon). `ayaka_normal_1` has none, so that snapshot slot was asserted
against nothing, and the module said so rather than pretending it was covered.

The Traveler is **Pyro Aether**, which is the Traveler whose payload this repo commits
(`tests/fixtures/nanoka_gi/detail/character_10000005-2.json`). The buffs do not vary by
element.

### `ayaka_normal_1` — one normal attack, nothing else

Kamisato Ayaka 90/6, **Dull Blade** 70/4, no artifacts, against a level-90 target at 10%
resistance in every channel. One first-hit normal attack. gcsim reports
**108.53039935232651** total damage.

Every choice here is about removing everything that is not the damage chain:

* **Dull Blade has no substat and no passive.** A weapon passive is kit text, which is
  Chunk H's, so a weapon with one would have measured this repo's missing feature rather
  than its arithmetic. (Aquila Favonia — the obvious choice — grants +20% ATK, and using it
  would have made the case fail for a reason that is not a formula error.)
* **No artifacts**, so nothing depends on the artifact value tables.
* **A normal attack**, which is Physical for Ayaka, so the case does not depend on elemental
  application or on any reaction.
* **One hit**, so there is no rotation, no ICD, and no crit averaging: the number is exact
  rather than a mean over iterations, which is what makes a tight tolerance arguable at all.

Later cases should add exactly one of those back at a time. A case that changes four things
tells you only that something is wrong.


### `ayaka_normal_1_nocrit` — the same case with crit forced off

`ayaka_normal_1.txt` plus one line:

```
ayaka add stats cr=-1;
```

**Why it exists.** gcsim *rolls* crit (`damage.go:101`), so re-running a config is not
deterministic. The committed `ayaka_normal_1.json` is one recorded roll that happened not to
crit, which is fine for a fixture and fatal for a **live** check: anything that re-runs gcsim
and compares to that number passes about 95% of the time and fails the rest.

That is exactly what happened. `frontend/scripts/verify-gcsim-wasm.mjs` re-runs the browser
build on every CI job, and it passed five times before returning **40.894** against an
expected 21.706 — a ratio of 1.884, which is precisely `1 + Ayaka's crit DMG at 90/6`
(0.5 base + 0.384 ascension). It had rolled a crit.

Forcing crit rate below zero clamps it to zero, so every hit is non-crit and the run is
reproducible: **108.53039935232651**, five runs out of five, and the same total the
crit-rolled fixture recorded.

**Use this one for anything that re-runs gcsim.** Use `ayaka_normal_1.json` for anything
comparing against a recorded run — and there, compare `non_crit`, as
`test_the_crossval_hit_did_not_crit_in_gcsim` explains.

No JSON is committed for this variant: its whole point is that it can be recomputed on
demand and get the same answer.
