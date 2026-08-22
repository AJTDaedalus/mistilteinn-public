# gcsim crossval fixtures

Each case is a **gcsim config** and the **JSON gcsim produced from it**, both committed
verbatim. The harness in `backend/tests/crossval/` recomputes the same build through this
repo and compares.

| | |
|---|---|
| **Oracle** | `github.com/genshinsim/gcsim` |
| **Commit** | `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa` — the pin in `docs/CROSSVAL_gcsim.md` |
| **Recorded** | 2026-08-21, task F.7 |

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
git checkout 3647a07a7cc3004bc1e79d9bb5f7444de20dceaa
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
