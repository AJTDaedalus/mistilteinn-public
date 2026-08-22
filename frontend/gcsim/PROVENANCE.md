# gcsim browser build

The simulator this project runs **in the user's browser** (DESIGN_client_optimizer §1).

| | |
|---|---|
| **Repository** | `github.com/genshinsim/gcsim` |
| **Commit** | the single pin in `docs/CROSSVAL_gcsim.md` — never restated here |
| **Target** | `GOOS=js GOARCH=wasm ./cmd/wasm` — upstream's own browser binding |
| **Build** | `./scripts/build-gcsim-wasm.sh` |

## Why the artifact is not committed

40 MB (7 MB gzipped), and `-ldflags="-w -s"` saves about 1 MB at a performance cost upstream
documents in `cmd/wasm/build.sh`. Committing it would add a fresh multi-megabyte blob on
every re-pin, permanently.

Two precedents in this repo already point the other way:

- `backend/tests/fixtures/crossval/PROVENANCE.md` — *"gcsim is not vendored: it is a 35 MB
  Go binary and building it needs a Go toolchain"*, committing the **output** instead.
- `backend/app/data/yuanshen/` — `snapshot/` is committed, `cache/` is gitignored, and the
  54 MB TextMap lives only in the cache.

So: **the pin and the recipe are committed; the artifact is built.** That is not a live
fetch of *data* — it is a build from source at a reviewed commit, which is what the snapshot
rule protects and what the re-pin discipline in `CROSSVAL_gcsim.md` already governs.

## The pin is not restated here

`build-gcsim-wasm.sh` reads it out of `docs/CROSSVAL_gcsim.md`, and
`tests/unit/test_gcsim_pin_is_single.py` asserts nothing else declares one. Two pins that
can drift apart are two definitions of what "correct" means — and this repo's crossval
fixtures assert `sim_version` for exactly that reason.

## What it is verified to do

Driven through its own JS bindings — `initializeAggregator` → `initializeWorker` →
`simulate` → `aggregate` → `flush` — against the committed `ayaka_normal_1.txt`, this build
returns

```
dps mean : 21.706079870465302
```

which is the value the committed fixture, the native binary and the WASI probe all report,
**to the last digit**. Four independent paths agreeing is what makes the browser the place
this project is willing to run its simulator.

Measured on a realistic two-character 90-second rotation: **31.35 ms per Monte Carlo
iteration**, single-threaded. The browser runs these across Web Workers, so wall-clock
divides by the worker count.
