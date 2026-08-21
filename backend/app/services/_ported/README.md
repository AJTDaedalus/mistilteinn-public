# `_ported/` — read-only porting source

These files are **not runtime code.** They are fairy's ZZZ implementations, kept only so the
Genshin ports can be written *against* them instead of from memory. Nothing in `app/` imports
from this directory, and nothing should.

Staged in Task B.1 (`docs/TASKS_mistilteinn.md`), per DESIGN §3 Chunk B and the §2.2
disposition table.

| File | Lines | Consumed by | Becomes |
|---|---:|---|---|
| `optimizer_pipeline.py` | 1826 | Chunk G (G.3) | ported in place — top-K / Pareto / budget-K machinery is game-agnostic |
| `disc_optimizer.py` | 1525 | Chunk G (G.1) | `artifact_optimizer.py` — 6 slots → 5, two with fixed main stats |
| `damage_dag_service.py` | 984 | Chunk F (F.4) | ported — DAG assembly is game-agnostic, the sheets it assembles are not |
| `rank_pipeline.py` | 743 | Chunk G (G.4) | ported — slot-count and stat-vocabulary edits |
| `build_damage_service.py` | 707 | Chunk F/G | ported |
| `modifiers.py` + `buff_resolver.py` | 1168 | Chunk H | the modifier DSL — `attack_scope` vocabulary retargeted, not replaced |

## Rules

1. **Delete each file when its port lands.** A file still sitting here after its chunk closes is
   a leak: the BRIEF names ZZZ shapes bleeding into the Genshin domain as this fork's main
   long-term hazard, and stale reference code is how that happens. Chunk G.8 deletes the
   optimizer set explicitly; do the same for the rest.
2. **Do not import from here.** There is deliberately no `__init__.py`, so setuptools'
   `packages.find` does not install it and it is not a package.
3. **Do not edit these files to make anything run.** They are a historical record. Read them,
   write the new thing next to the new domain model, delete these.
4. Excluded from `ruff` and from `pytest` in `backend/pyproject.toml` — they lint against
   deleted ZZZ modules and would otherwise be permanent noise.

Everything here also exists in `/root/fairy` and in the fairy repo at `76909c4`; this directory
is a convenience, not the only copy.
