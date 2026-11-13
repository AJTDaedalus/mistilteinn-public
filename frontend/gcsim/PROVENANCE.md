# gcsim browser build

The simulator this project runs **in the user's browser** (DESIGN_client_optimizer §1).

| | |
|---|---|
| **Repository** | `github.com/genshinsim/gcsim` |
| **Commit** | the single pin in `docs/CROSSVAL_gcsim.md` — never restated here |
| **Target** | `GOOS=js GOARCH=wasm ./cmd/wasm` — upstream's own browser binding |
| **Build** | `./scripts/build-gcsim-wasm.sh` |
| **Notices** | `gcsim.LICENSE.txt` (gcsim's own, AGPLv3), `gcsim-mit.LICENSE.txt` (gcsim's retained MIT notice) and `go.LICENSE.txt` (Go's, for `wasm_exec.js`), written by the build and served beside the artifacts |
| **Provenance** | `BUILT_FROM`, the commit built — served too, and read by `/about` to link gcsim's source at exactly that commit |

## The licence travels with the artifact

Both files are downloaded into every visitor's browser, which is redistribution, and both
licences require their notice to be retained. gcsim's is **AGPLv3 at this pin**, with its MIT
notice retained for code contributed before the relicence — so two files, and both ship;
`wasm_exec.js` is Go's, BSD-3-Clause, and is the easier one to miss because neither this
project nor gcsim wrote it. The build writes both beside the artifacts, `angular.json` copies them into the
bundle, and the production image **refuses to build** if either is missing — an asset glob
that matches nothing otherwise succeeds silently, which is exactly how this bundle once
shipped with no simulator at all.

**gcsim relicensed to AGPLv3 on 2026-09-19** (`05f01a733`), whose §13 covers network use.
The pin stayed on v2.47.2, the last MIT release, until the owner decided to cross that line;
**v2.50.0 crosses it (2026-11-13)**. What that obliges — the notices here, and a source offer
on every page of the site — is in `docs/CROSSVAL_gcsim.md` §The pin and `docs/DECISIONS.md`
§37, and `tests/unit/test_gcsim_licence_ships_with_the_wasm.py` holds the build to it.

**`wasm_exec.js` must come from the toolchain that built the wasm.** The build asks
`go env GOROOT` from *inside* the gcsim clone: with `GOTOOLCHAIN=auto` and a host Go older
than gcsim's `go.mod`, asking from anywhere else named the host's GOROOT, and the loader
shipped from Go 1.23 beside a binary from Go 1.27 (found at the v2.50.0 re-pin).

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
