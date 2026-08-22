# DESIGN: the client-side optimizer, and retrieval over a simulated corpus

**Supersedes** the server-side optimize/rank endpoints for interactive use, and **Chunk H**
entirely. Founded on `BRIEF_mistilteinn.md`, `RESEARCH_gcsim_embed.md` (Chunk S), and the
four owner rulings in `DECISIONS.md` dated 2026-08-22.

## Branch policy

- Work happens on `feat/client-optimizer` and sub-branches off it; **never** on `dev` or
  `main`. `dev` is updated only by PR merge after review.
- Sub-branches, because the tracks are genuinely parallel: `feat/client-kernel`,
  `feat/sim-corpus`, `feat/retrieval`, `feat/explain`.
- **Task 0 of `TASKS_client_optimizer.md` is the branch-setup gate.** Nothing else starts
  until it is done.
- `ruff check` and the full backend suite pass before every backend commit; `npm run lint`
  and the kernel's own tests before every frontend commit.

---

## 1. The shape

```
browser    gcsim WASM (upstream js/wasm build)      per-build simulation
           search kernel (WGSL on GPU, TS on CPU)   the permutation search
              |
              |  scores, contribution logs, chosen builds
              v
server     retrieval index · corpus generation · the API   (FastAPI)
              |
              v
postgres   catalogue · inventories · builds · the simulated-run corpus
```

The server never computes damage. The browser never stores anything durable.

## 2. Why the kernel is batched, and what that decides (OQ-S2)

Fribbels' own WebGPU notes report **1.0–2.2 billion permutations/second**, against this
repo's measured server chain at **5.5e-4 s/combination ≈ 1,800/second**. That is a factor of
about **10⁶**.

**Be precise about where that factor comes from**, because it is not all hardware. A
"permutation" in a flat f32 GPU kernel and a "combination" in this repo's Python DAG — which
resolves stats through a node graph and writes a contribution log — are not the same unit of
work. The gap is *Python-DAG-on-a-server* versus *WGSL-on-a-GPU*, and both halves of that
contribute. Treat 10⁶ as the order of the opportunity, not as a benchmark.

Three things follow, and they are the substance of this design:

1. **The kernel evaluates batches, not single candidates.** Each combination in a five-slot
   product is independent, so the search is embarrassingly parallel. Batching is what makes
   a GPU possible, and a GPU is where the factor lives. This answers **OQ-S2**: the fast
   backend is **WGSL compute shaders**; the fallback is **TypeScript** over typed arrays.
   **Not Rust and not Go** — the GPU path carries the performance, so the CPU fallback needs
   to be correct and universally available rather than maximally fast, and TypeScript adds
   no language to a stack that is already Python + TypeScript. (gcsim stays Go/WASM, but
   that is upstream's build, not ours to maintain.)

2. **The lossy prefilter may become unnecessary, and that is a feature.** G.3's budget-K
   exists because a *server* is slow: it trades exactness for finishing, and every response
   has to disclose that it did. At a billion permutations per second an inventory that
   needed budget-K on the server is searched **exhaustively** in the browser. The plan is
   therefore: **port the lossless Pareto layer, and port budget-K but expect `is_exact` to
   be true almost always.** Keep the disclosure machinery — a flag that is nearly always
   true is still the flag that tells you about the case where it is not.

3. **WGSL's limits are load-bearing constraints, not footnotes.** From Fribbels' notes:
   no 64-bit support, so values are `f32` and indices `i32`; and a global permutation id
   exceeds 32 bits, needing 64-bit arithmetic emulated with 32-bit ints. **`f32` is a
   correctness question for this project specifically**, because `tests/crossval` matches
   gcsim to 1.3e-8 in float64 and F.7 already established that float32 curve storage is the
   entire residual. An `f32` kernel cannot hit 1.3e-8. §6 sets the tolerance question out
   properly rather than discovering it at the end.

## 3. The retrieval layer

**What is retrieved is context, not damage.** gcsim produces a simulated run for a *complete*
build. What the search needs from it is the part that does not change much when artifacts
change at the margin: buff and aura uptimes, reaction counts, energy/ER feasibility, and
which conditional effects were live. The kernel then scores candidates with that context
held fixed.

**Key:** `(character, weapon, constellation, refinement, team, rotation)` plus **coarse
buckets** of the stat dimensions that change context rather than just scaling it — energy
recharge above all, then elemental mastery.

**The load-bearing assumption** is that context is far less sensitive to marginal stat
changes than damage is. That is plausible and it is not proven, so:

- **The retrieval layer measures its own error.** For a sample of candidates, score with
  retrieved context *and* run the real simulation, and record the divergence. A score built
  on retrieved context ships with the measured error for its neighbourhood, or it does not
  ship.
- **This is F.5's rule applied one level up.** A damage number must be able to explain
  itself; a *retrieved* damage number must additionally be able to say what it was retrieved
  from and how far that neighbour was. An approximation that cannot report its own error is
  the failure mode this project has spent every chunk avoiding.
- **The top N are verified by real simulation** before they are shown. Retrieval ranks;
  simulation confirms. That bound is what makes the approximation safe to act on.

## 3.5 What compute costs, and where it lands

**An optimization is defined for one team and one rotation.** That is the observation this
section turns on, and it collapses most of what an earlier draft costed.

If team and rotation are *inputs*, then so are character, weapon, refinement and
constellation — every one of those is **the user's build**. The only thing being searched is
the artifacts. So there is no corpus to enumerate: the context of a search is fully
determined before it starts, except for the stats the artifacts themselves change.

### Only one artifact-borne stat feeds back into context

| stat | changes the context? |
|---|---|
| **energy recharge** | **Yes** — burst uptime depends on energy, so the rotation itself executes differently |
| elemental mastery | No — it changes reaction *damage*, which the Chunk F chain scales directly |
| ATK / HP / DEF | No — pure scaling |
| crit rate / crit DMG | No — pure scaling |
| elemental DMG bonus | No — pure scaling |

Everything except ER is a multiplier the kernel applies itself. **ER is the only coupling**,
because it is the only one that can change whether the rotation happens at all — and while
the BRIEF ships amplifying reactions first, it is the only one that matters.

So the runs a search needs are **one per ER bucket**, for that one context:

| ER buckets | gcsim runs | time |
|---:|---:|---|
| 4 | 4 | ~1.0 s |
| 6 | 6 | ~1.4 s |
| 12 | 12 | ~2.9 s |

**In the browser, via gcsim WASM, and cached afterwards.** Seconds, not the 4.7–31.5 hours
an earlier draft of this section projected from enumerating teams × rotations. That draft was
answering a question nobody asks: it costed *"simulate every team and rotation in advance"*,
when a user always arrives with a specific one.

### Which leaves compute landing almost entirely on the user

| Cost | Lands on | Scales with |
|---|---|---|
| Permutation search | the user's GPU | how thorough the user asks for |
| Context runs (one per ER bucket) | the user's browser | ER buckets — a constant |
| Top-N verification | the user's browser | N, which we choose |
| Retrieval | our server | queries, and it is an index lookup |

**Nothing combinatorial lands on the server.** "More compute" is a relocation, not a bill.

### What the server-side corpus is actually for

Not for making the search possible — the browser does that unaided. It accumulates from real
searches and earns its keep elsewhere:

- **Explanation** (§4): grounding "why is this better" in a body of real runs rather than one.
- **Cross-user knowledge**: benchmark builds, what a well-built version of this character
  looks like, which is something no client-side tool can offer.
- **Not recomputing** what another user already simulated at the same pin.

It is **demand-driven by construction**, and **write-once per gcsim pin** — the BRIEF's
observation that Genshin kits are immutable post-release, applied one level up: a simulated
run stays valid until the pin moves, so the corpus is invalidated by a deliberate, reviewed
re-pin rather than by time. `optimization_jobs` (§5) tracks a re-pin's regeneration, which is
now its main remaining job rather than a large upfront batch.

**Optional, not required:** warming the cache for popular contexts ahead of demand. BRIEF
constraint 4's "~20–30 character MVP cut" is the natural definition of *popular* if that is
ever wanted. It is no longer on the critical path.

### Weapon options are cheap, and belong in v1

A user selecting a few candidate weapons to optimize across is **separable**: for each
weapon, find its best artifacts; then compare the winners. N independent problems, not one
problem N times harder — the same structure as everything else here.

| weapons | context runs | browser time | GPU searches |
|---:|---:|---|---:|
| 1 | 6 | ~1.4 s | 1 |
| 3 | 18 | ~4.3 s | 3 |
| 5 | 30 | ~7.1 s | 5 |
| 10 | 60 | ~14.3 s | 10 |

A weapon does have to be a **context** dimension rather than a pure multiplier, because a
passive can change the rotation's feasibility the same way ER does — Favonius generating
particles is the obvious case. So it multiplies the *context* runs, and each `(weapon, ER
bucket)` pair is its own run. At a second and a half per weapon that is affordable, and the
GPU searches are free by comparison.

**This is only cheap because of the collapse above.** Had the corpus been a server-side
enumeration of weapons × teams × rotations, adding a weapon dimension would have multiplied a
combinatorial cost. Since context is per-search and client-side, it multiplies seconds.

Two consequences worth noting:

- **The G.4 ranker generalises to it for free.** "Which weapon should I use" is the same
  marginal-value question as "which artifact should I use" — swap it in, hold the rest
  constant, report the difference against what is equipped. The ranker does not need a new
  concept, only a new axis.
- **The explanation must attribute across weapons**, not just within a build: "this weapon
  wins because its passive raises your burst uptime", not merely "this build scores higher".
  That is §4's job, and it is the more useful answer.

**Recommended for v1**, on the strength of the cost. If it slips, it slips for UI reasons —
comparing results across weapons needs a display concept that comparing artifacts does not —
and not for compute ones.

### The constraint that survives

A search can still arrive with no cached context. That must be a stated outcome, not a silent
fallback: simulate it now (a second or two), or say so. It must never be to retrieve a
distant neighbour and report its score as though it were close — the rule §3 sets, arriving
from the other direction.

### The caveat

This holds because the rotation is **fixed and supplied**. If the rotation itself ever becomes
something to optimize — Chunk I territory — the collapse does not survive, and the cost
question reopens on new terms. Worth knowing before that chunk starts rather than during it.

## 4. Explanation

The same index, read the other way. A build's explanation is assembled from its own
contribution log (which the kernel emits, exactly as `explain.py` does today), the retrieved
simulated runs, and set/talent text from Postgres — and every number in the answer cites the
run or contribution it came from.

**This is why F.5 and G.1's `contributions` were worth their cost.** They were built as a
legibility constraint under DESIGN §1 A6. They turn out to be the corpus for the product's
second differentiator, which is the strongest possible argument that the constraint was not
overhead.

## 5. What survives, what moves, what is deleted

| | |
|---|---|
| **Unchanged** | Domain models, nanoka importer, YuanShen snapshot, GOOD importer, catalogue and inventory APIs, auth, Postgres. Storage and truth do not move. |
| **Moves to the browser** | The damage chain and the artifact search — as a **new** WGSL/TS kernel, not a port of the Python. |
| **Ports as a design** | The lossless Pareto layer (G.3), budget-K (G.3), marginal-value ranking (G.4). Settled algorithms, new implementation. |
| **Kept through the port, then deleted** | `formula/genshin/*`, `services/{stat_calculator,damage_calculator,artifact_optimizer,artifact_prefilter,artifact_ranker}.py`. See §6. |
| **Decided in this design** | `JobRunner` and the 202 contract (G.10). With the search client-side there is no long server-side search to background. **Corpus generation is a genuinely long server-side job**, so `optimization_jobs` is **retargeted** to it rather than deleted — the queueing, cancellation and progress machinery is exactly what a corpus run needs. |
| **Decided in this design** | The disabled CI kit-validation gate (`TODO(chunk-H)` in `test.yml`). Chunk H is superseded, so there is no kit corpus to validate. **The stanza is deleted**, and the commit that deletes it says why — leaving a disabled gate pointing at a superseded chunk is worse than having neither. |

## 6. Testing: the gate that lets the second chain exist

Two damage chains that must agree is the failure mode DESIGN §1 A6 exists to prevent, and
this design creates one deliberately. It is only acceptable with a gate, and the gate is
**differential testing, not the crossval fixtures**.

The committed crossval corpus is **two cases**. It cannot catch a kernel that is right on
Ayaka-with-no-artifacts and wrong on DEF scaling, a capped crit rate, or an absent substat.

- **The Python chain generates expected values for thousands of arbitrary inputs** — random
  builds across every scaling stat, channel, scope, amplifying reaction, and edge case the
  unit suites already know about — and the kernel must match them.
- **gcsim confirms a sample of those**, so the pair is anchored to the oracle rather than to
  each other.
- **Tolerance is set from the f32 constraint, and argued in writing before the kernel is
  written.** `CROSSVAL_gcsim.md` argues 1e-7 for the float64 chain and explains its residual;
  an `f32` kernel needs its own number, derived from f32's ~1e-7 relative precision compounded
  across the chain's operations — and a test must prove the tolerance cannot hide a formula
  error, exactly as `tests/crossval` already does for the Python one.
- **The kernel does not ship until this gate exists.** A second chain without a test binding
  it to the first is the entire hazard.

Only once the kernel passes are the Python modules deleted, under the rule
`app/services/_ported/README.md` already states: *delete each file when its port lands*.

## 7. Open questions

- **OQ-S3:** does the browser hold the artifact inventory, or fetch it per search? Postgres
  is the store, but shipping a 2,000-piece inventory to the client on every search is a
  design choice with a real latency cost and an obvious cache answer.
- **OQ-S4:** WebGPU is unavailable in some browsers and in most CI. The TS fallback covers
  correctness; what it does **not** cover is the GPU kernel being tested at all in CI. This
  repo's rule is that a check which cannot run is not a pass, so the GPU path needs either a
  CI runner that has one or an explicit, recorded exemption.
- **OQ-S2 is answered above** (WGSL + TypeScript). Recorded here rather than left in the
  BRIEF's open list.
