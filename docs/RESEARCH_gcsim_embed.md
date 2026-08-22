# RESEARCH: embedding gcsim as the simulation engine

**Chunk S, the spike OQ-M2 authorised.** Timebox ~2–3 sessions; this is session 1.

**Verdict: integration is clean.** gcsim's simulation core builds for WebAssembly, runs
inside Python, and returns results bit-identical to the native binary and to the crossval
oracle already committed in this repo. The BRIEF's success condition — *"if integration is
clean, it collapses the hardest phase"* — is met on the technical question.

It also surfaced a question the technical result cannot answer, in §6. That one is the
owner's.

| | |
|---|---|
| **gcsim pin** | `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa` — the same pin `docs/CROSSVAL_gcsim.md` already carries |
| **Go** | 1.23.4 |
| **WASI host** | `wasmtime` (Python bindings) |
| **Measured on** | this dev box, 2026-08-22 |

---

## 1. Can gcsim be driven programmatically? — yes

`pkg/simulator.Run(ctx, Options{ConfigPath}) (*model.SimulationResult, error)` is the whole
entry point. `cmd/wasm/main.go` is a ~325-line binding exposing `validateConfig`,
`initializeWorker`, `simulate` and the aggregators to a JS host — which is the useful
evidence: **the core is already separated from its front end upstream**, so writing another
thin front end is the intended shape rather than a fork.

Upstream's WASM target is `//go:build js && wasm` and imports `syscall/js`, so it is for the
browser and cannot be hosted from Python. That is a binding, not a limit.

## 2. WASI builds, and runs from Python

A **30-line** `main.go` calling `simulator.Run`, built with `GOOS=wasip1 GOARCH=wasm`:

```
$ GOOS=wasip1 GOARCH=wasm go build -o probe.wasm ./cmd/wasiprobe
$ ls -lh probe.wasm    # 40M
```

Hosted with `wasmtime`, preopening the config directory:

```
{"dps_mean":21.706079870465302,"iterations":1}
```

**That is the committed crossval fixture's number to the last digit** —
`ayaka_normal_1.json` says `21.706079870465302`, the freshly built native binary says
`21.706079870465302`, and the WASI module says `21.706079870465302`.

Two practical notes:

- Go's `runtime.exit(0)` surfaces through wasmtime as an `ExitTrap` with code 0. It is a
  normal successful exit and has to be caught, not treated as a failure.
- Cold `Module.from_file` costs **9.7 s**. `Module.serialize()` / `deserialize` drops it to
  **0.15 s**, so the compile is a build-time artifact, not a per-request cost.

## 3. Throughput — and the number that settles what gcsim can and cannot be

A realistic case: Ayaka + Kazuha, 90-second rotation, 100 Monte Carlo iterations.

| | per run |
|---|---|
| gcsim **native** binary | **0.238 s** (parallel — 1.11 s CPU across cores) |
| gcsim **WASI** in-process | **2.6 – 3.2 s** |
| this repo's Chunk F chain | **5.5e-4 s** per *combination* (`SECONDS_PER_COMBINATION`) |

WASI is **11–13× slower than native** because `wasip1` has no threads: gcsim parallelises its
Monte Carlo across cores and WASI serialises it. The gap is structural, not tuning.

**The decisive comparison is the third row.** A gcsim run costs ~4,700× one combination in
the artifact search, and even the native binary is ~430×. **gcsim cannot be the optimizer's
inner loop** — a 9,000-combination search would take 35 minutes natively and seven hours
under WASI, against five seconds today.

Nothing proposed it for that. But it means embedding gcsim is **not** a replacement for the
Chunk F damage chain; it is a second tier above it. The chain stays as the search's scoring
function; gcsim answers "what does this build actually do over a rotation".

## 4. Coverage — the finding that matters most

At the pin, gcsim implements **106 characters** and **53 artifact sets**. This repo's nanoka
catalogue holds 150 character entries, of which 28 are Traveler variants — so gcsim covers
substantially the whole released roster.

**That is the kit corpus Chunk H exists to build** — the chunk this project's own BRIEF names
as its highest-risk, because it is where fabricated citations did fairy the most damage.
Adopting gcsim does not merely collapse the gauge-sim phase. It puts a community-validated,
MIT-licensed, upstream-maintained kit corpus in place of one this project would otherwise
curate character by character.

## 5. What integration would still cost

Real, bounded, and none of it novel:

1. **Config generation.** Emitting gcsim config text from our DB models — character/weapon/
   set keys, levels, refinement, constellation, artifact stats. Mechanical.
2. **A character-key mapping.** ~~Naive normalisation matches 111 of 150; the 39 misses are
   mostly surname-prefixed names — gcsim calls Kamisato Ayaka `ayaka`.~~ **Corrected in B.3:
   that read gcsim's *directory* names, which are not its keys.** The authority is
   `pkg/core/keys/*.dm.go`, and the real keys are the **full** names — `kamisatoayaka`,
   `kaedeharakazuha`, `raidenshogun`. There is no surname alias table.

   Measured against the real keys: **105 of 150** match by normalisation. The 45 misses are
   **28 Traveler variants**, which are structured rather than aliased (body id + element →
   `aetherpyro`; gcsim has six elements, with no Cryo Traveler), and **17 characters released
   after the pin**. The second group is refused — gcsim cannot simulate what it does not
   implement, and a re-pin is what changes that. Weapons match 231/284 and artifact sets
   53/65, with the same character: the misses are things gcsim has no key for.

   **The `refuse rather than guess` rule from G.6b still applies**, and matters more here: a
   wrong-but-plausible key makes gcsim simulate *a different character* and return a number
   that looks entirely reasonable.
3. **Action lists.** gcsim needs a rotation to simulate. The BRIEF already plans for this
   (*"rotation corpus (community action-list DB → default rotations per team archetype)"*).
4. **Re-pinning discipline.** gcsim becomes a dependency whose upgrades change results. The
   repo already has the machinery — `docs/CROSSVAL_gcsim.md`'s pin, and the fixture's
   `sim_version` assertion.

## 6. What the spike cannot decide

**If gcsim supplies both the simulation and the kits, what is mistilteinn?**

The BRIEF's stated niche is *"builds through a stateful reaction sim — with fairy's DB-backed
kit-validation rigor behind the kit corpus"*. Two of those three clauses are things gcsim
already has. What would remain is genuinely valuable and genuinely narrower: the artifact
optimizer (which gcsim has no equivalent of, and which is 430× too fast to give up), the GOOD
inventory, the DB-as-truth catalogue, and a UI.

That is a strategy question, not an engineering one, and it is above the tier that ran this
spike.

**Answered 2026-08-22 (owner).** The artifact optimizer and its explainability are the
product; gcsim is infrastructure beneath them. The bar is `fribbels/hsr-optimizer`, not
"GO + gcsim in one site" — and the opening against Fribbels is that it runs **entirely in the
browser** (GitHub Pages, WebGPU) and therefore cannot precompute, retrieve, or hold state,
while this project is backend-first and can. Retrieval serves both the search and the
explanation over one shared corpus of simulated runs. Full entry in `DECISIONS.md`.

## 7. Recommendation

**Adopt gcsim as a sidecar, not as WASM, and keep the Chunk F chain.**

- **Sidecar over WASM.** WASM's advantages are deployment simplicity and sandboxing; its cost
  is 11–13× throughput and no threads. This project already runs Docker Compose, already has
  a `JobRunner` for out-of-band work (G.10), and gains nothing from sandboxing code it pins by
  commit. A subprocess or a small HTTP service gets native speed for free.
- **Keep the Chunk F chain.** It is the optimizer's scoring function and nothing else can be —
  see §3. The crossval harness proving it agrees with gcsim to 1.3e-8 becomes *more* valuable,
  not less, because the two tiers must not disagree.
- **Keep the WASM path documented** rather than discarded: it is the fallback if a sidecar
  becomes unacceptable, and this document is enough to rebuild it in an hour.

### Either way, the spike already paid for itself

Per the BRIEF, *"if not, walk away with better crossval tooling"*. It did: the crossval fixture
committed in F.7 has now been **independently regenerated from the pin and matched digit for
digit**, which is the first time anything has demonstrated that recipe actually runs.
`backend/tests/fixtures/crossval/PROVENANCE.md` claims reproducibility; this is the evidence
for the claim.

## Reproducing this

```bash
curl -sSL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xz
export PATH=$PATH:/usr/local/go/bin
git clone https://github.com/genshinsim/gcsim /tmp/gcsim && cd /tmp/gcsim
git checkout 3647a07a7cc3004bc1e79d9bb5f7444de20dceaa

go build -o gcsim-native ./cmd/gcsim                             # native, 34 MB
GOOS=wasip1 GOARCH=wasm go build -o probe.wasm ./cmd/wasiprobe   # WASI, 40 MB
```

`cmd/wasiprobe/main.go` is 30 lines: read `os.Args[1]`, call
`simulator.Run(ctx, simulator.Options{ConfigPath: ...})`, marshal
`result.Statistics.DPS.Mean`. It is deliberately not committed here — it belongs to gcsim's
tree, and re-deriving it is a smaller cost than carrying a Go file in a Python repo that
nothing builds.
