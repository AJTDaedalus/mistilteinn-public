"""Formula layer: symbolic computation graph (Pando-style DAG).

The ``formula`` package defines the IR used to describe ZZZ damage formulas
as a tree of operations (``sum``, ``prod``, ``thres``, ``read`` …) tagged
with coordinates (``{src: "Anby", q: "atk_"}``). The IR is consumed by:

* ``app.pando.calculator`` — single-shot evaluator (port of Pando's
  ``Calculator`` class). Replaces the old procedural ``stat_calculator``
  and ``damage_calculator`` when fully migrated.
* ``app.pando.solver`` (Phase 6.3+) — candidate-pool solver with interval
  arithmetic pruning + Numba-compiled hot loop.
"""
