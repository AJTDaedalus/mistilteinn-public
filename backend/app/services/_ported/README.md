# `_ported/` — read-only porting source

These files are **not runtime code.** They are fairy's ZZZ implementations, kept only so the
Genshin ports can be written *against* them instead of from memory. Nothing in `app/` imports
from this directory, and nothing should.

Staged in Task B.1 (`docs/TASKS_mistilteinn.md`), per DESIGN §3 Chunk B and the §2.2
disposition table. `translator.py` joined them in B.3 — see the note below the table.

| File | Lines | Consumed by | Becomes |
|---|---:|---|---|
| ~~`optimizer_pipeline.py`~~ | 1826 | Chunk G (G.3) | **deleted in G.8.** Its bulk was ZZZ combo machinery; what ported was the *shape* — lossless-then-lossy ordering, bisection for auto-K, solo-score ranking against a filler build, cooperative cancellation — into `artifact_prefilter.py`. Its time constant was **not** ported; `scripts/bench_optimizer.py` measures this codebase instead. |
| ~~`disc_optimizer.py`~~ | 1525 | Chunk G (G.1) | **deleted in G.8** → `artifact_optimizer.py` + `artifact_prefilter.py` (6 slots → 5). The Pareto layer and `_CONSTRAINT_STAT_ALIASES` were the parts worth having; missing the second cost a review finding. |
| `damage_dag_service.py` | 984 | Chunk F (F.4) | ported — DAG assembly is game-agnostic, the sheets it assembles are not |
| ~~`rank_pipeline.py`~~ | 743 | Chunk G (G.4) | **deleted in G.8** → `artifact_ranker.py`, which C.6 then deleted too once its endpoint went (`b16dbbd`). Its process-pool fan-out and potential-scoring never ported: the first became G.10's job runner, also gone in C.6, and the second needs a roll schedule this repo cannot cite (G.9). |
| `build_damage_service.py` | 707 | Chunk F/G | ported |
| `modifiers.py` + `buff_resolver.py` | 1168 | Chunk H | the modifier DSL — `attack_scope` vocabulary retargeted, not replaced |
| `translator.py` (was `app/pando/translator.py`) | 152 | Chunk F (F.1/F.4) | modifier → DAG translation, rewritten against `formula/genshin/tags.py` |

### Why `translator.py` is here

DESIGN §2.3 lists `app/pando/translator.py` as *"confirmed game-agnostic (zero ZZZ-term hits),
keep untouched"*, and §2.4 calls the `formula` + `pando` pair the least risky part of the port.
The vocabulary audit was right and the conclusion was too broad: translator.py contains no ZZZ
*words*, but it imports `app.formula.zzz.tags`, `app.services.modifiers`, and
`app.services.buff_resolver`. Converting the ZZZ modifier DSL into DAG entries **is** its whole
job, so it belongs to the modifier layer, not to neutral ground.

`app/pando/calculator.py` genuinely is free-standing, and `app/pando/__init__.py` never imported
translator — so moving it out leaves `import app.pando` clean, which is what B.3 has to accept on.

## Rules

1. **Delete each file when its port lands.** A file still sitting here after its chunk closes is
   a leak: the BRIEF names ZZZ shapes bleeding into the Genshin domain as this fork's main
   long-term hazard, and stale reference code is how that happens. **G.8 deleted the
   optimizer set**; do the same for the rest as their chunks close.
2. **Do not import from here.** There is deliberately no `__init__.py`, so setuptools'
   `packages.find` does not install it and it is not a package.
3. **Do not edit these files to make anything run.** They are a historical record. Read them,
   write the new thing next to the new domain model, delete these.
4. Excluded from `ruff` and from `pytest` in `backend/pyproject.toml` — they lint against
   deleted ZZZ modules and would otherwise be permanent noise.

Everything here also exists in `/root/fairy` and in the fairy repo at `76909c4`; this directory
is a convenience, not the only copy.
