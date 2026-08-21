"""Formula layer: symbolic computation graph (Pando-style DAG).

The ``formula`` package defines the IR used to describe damage formulas as a
tree of operations (``sum``, ``prod``, ``thres``, ``read`` …) tagged with
coordinates (``{src: "<character>", q: "atk_"}``). The IR is consumed by
``app.pando.calculator`` — a single-shot evaluator, port of Pando's
``Calculator`` class.

**Port state.** ``formula/zzz/`` (1,455 lines: the ZZZ tag vocabulary, stat and
damage graphs, agent sheets, and the sheet-loading DSL) was deleted in B.3. The
IR itself — ``builder``, ``nodes``, ``tags`` — is game-agnostic and survives
untouched. Its Genshin sibling ``formula/genshin/`` is written in Chunk F
(F.1 tags, F.2 stats, F.4 sheets + damage) and feeds the same calculator.
"""
