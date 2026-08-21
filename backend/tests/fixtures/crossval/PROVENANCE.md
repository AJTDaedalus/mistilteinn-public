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
git clone https://github.com/genshinsim/gcsim && cd gcsim
git checkout 3647a07a7cc3004bc1e79d9bb5f7444de20dceaa
go build -o gcsim ./cmd/gcsim
./gcsim -c ayaka_normal_1.txt -nb -out ayaka_normal_1.json
```

`sample_seed` and `build_date` are stripped from the committed copy: both change on every
run and carry no information, and leaving them in would make the fixture diff every time
anyone regenerated it for an unrelated case.

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
